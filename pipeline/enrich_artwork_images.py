"""작품 이미지 URL 보강 및 일괄 매핑 파이프라인.

대표 명작(1,500점) 및 주요 미술관(Cleveland, Met, AIC, Wikidata, MoMA, SMK 등)
소장작품의 고화질 이미지 URL(Open Access / Public Domain)을 초고속으로 수집 및 매핑하여
DB(artworks.image_url)에 일괄 업데이트합니다.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import sys
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import psycopg2
from psycopg2.extras import execute_values

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(line_buffering=True)

import requests

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_ROOT = BASE_DIR / "crawlers" / "raw"
VAULT_CURATED = BASE_DIR / "vault_curated" / "artworks"

DEFAULT_DB_URL = "postgresql://postgres@127.0.0.1:5433/artrend"
USER_AGENT = "ArtrendBot/1.0 (artgraph@artrend.com)"


def get_db_connection(dsn: str | None = None) -> psycopg2.extensions.connection:
    url = dsn or os.environ.get("DATABASE_URL", DEFAULT_DB_URL)
    conn = psycopg2.connect(url)
    conn.autocommit = True
    return conn


def ensure_schema(conn: psycopg2.extensions.connection) -> None:
    """artworks 테이블에 image_url 컬럼 및 최적화 인덱스 보장."""
    with conn.cursor() as cur:
        cur.execute("ALTER TABLE artworks ADD COLUMN IF NOT EXISTS image_url TEXT;")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_artworks_source_id ON artworks (source_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_sources_site_name ON sources (site_name);")
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_artworks_image_url ON artworks (image_url) WHERE image_url IS NOT NULL;"
        )
    print("✓ [Schema] artworks.image_url 및 인덱스 준비 완료")


def batch_update_artwork_images(
    conn: psycopg2.extensions.connection, updates: list[tuple[str, str]], chunk_size: int = 5000
) -> int:
    """(artwork_id, image_url) 리스트를 Postgres에 초고속 배치 업데이트."""
    if not updates:
        return 0

    query = """
        UPDATE artworks AS a
        SET image_url = v.img_url
        FROM (VALUES %s) AS v(id, img_url)
        WHERE a.id = v.id::uuid
          AND (a.image_url IS NULL OR a.image_url = '');
    """
    total = 0
    with conn.cursor() as cur:
        for i in range(0, len(updates), chunk_size):
            chunk = updates[i : i + chunk_size]
            execute_values(cur, query, chunk)
            total += len(chunk)
    return total


def p18_to_commons_url(image_filename: str) -> str:
    """Wikidata P18 파일명을 표준 Wikimedia Commons 고화질 이미지 URL로 변환."""
    fn_clean = image_filename.replace(" ", "_")
    encoded = urllib.parse.quote(fn_clean)
    md5 = hashlib.md5(fn_clean.encode("utf-8")).hexdigest()
    a, b = md5[0], md5[:2]
    return f"https://upload.wikimedia.org/wikipedia/commons/{a}/{b}/{encoded}"


# =========================================================================
# 1. Cleveland Museum of Art: 67k Open Access Images
# =========================================================================
def enrich_cleveland(conn: psycopg2.extensions.connection) -> int:
    """Cleveland Museum of Art 원본 JSON 파일들에서 고화질 Open Access 이미지 매핑."""
    print("\n--- [1] Cleveland Museum of Art 이미지 매핑 시작 ---")
    t0 = time.time()
    clev_dir = RAW_ROOT / "cleveland"
    if not clev_dir.exists():
        print("  ! crawlers/raw/cleveland 디렉토리가 없습니다.")
        return 0

    with conn.cursor() as cur:
        cur.execute("""
            SELECT s.raw_path, a.id
            FROM artworks a
            JOIN sources s ON a.source_id = s.id
            WHERE s.site_name = 'cleveland'
              AND (a.image_url IS NULL OR a.image_url = '');
        """)
        raw_path_map = {r[0]: str(r[1]) for r in cur.fetchall()}

    print(f"  - Cleveland 미매핑 대상: {len(raw_path_map):,}건 (DB 조회 {time.time()-t0:.2f}s)")
    if not raw_path_map:
        return 0

    def _extract(item: tuple[str, str]) -> tuple[str, str] | None:
        raw_path, aw_id = item
        full_path = BASE_DIR / raw_path
        if not full_path.exists():
            return None
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                d = json.load(f)
            imgs = d.get("images")
            if isinstance(imgs, dict):
                url = (imgs.get("web") or {}).get("url") or (imgs.get("print") or {}).get("url")
                if url and "openaccess-cdn.clevelandart.org" in url:
                    return (aw_id, url)
        except Exception:
            pass
        return None

    t1 = time.time()
    updates = []
    with ThreadPoolExecutor(max_workers=32) as executor:
        for res in executor.map(_extract, raw_path_map.items()):
            if res:
                updates.append(res)

    print(f"  - 파일 파싱 완료: {len(updates):,}건 추출 ({time.time()-t1:.2f}s)")
    updated = batch_update_artwork_images(conn, updates)
    print(f"  ✓ Cleveland DB 반영 완료: {updated:,}건 업데이트 (총 {time.time()-t0:.2f}s)")
    return updated


# =========================================================================
# 2. MoMA (Museum of Modern Art): 120k Collection & Curated
# =========================================================================
def enrich_moma(conn: psycopg2.extensions.connection) -> int:
    """MoMA Artworks.csv에서 고화질 공식 이미지 URL 일괄 매핑."""
    print("\n--- [2] MoMA (Museum of Modern Art) 이미지 매핑 시작 ---")
    t0 = time.time()
    moma_csv = RAW_ROOT / "moma" / "Artworks.csv"
    if not moma_csv.exists():
        print("  ! crawlers/raw/moma/Artworks.csv 파일이 없습니다.")
        return 0

    acc_to_img: dict[str, str] = {}
    with open(moma_csv, "r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            acc = (row.get("AccessionNumber") or "").strip()
            img = (row.get("ImageURL") or "").strip()
            if acc and img:
                acc_to_img[acc] = img

    print(f"  - MoMA CSV 유효 이미지 URL 보유: {len(acc_to_img):,}건 ({time.time()-t0:.2f}s)")

    with conn.cursor() as cur:
        cur.execute("""
            SELECT a.id, mh.accession_number
            FROM artworks a
            JOIN sources s ON a.source_id = s.id
            LEFT JOIN museum_holdings mh ON mh.artwork_id = a.id
            WHERE s.site_name = 'moma'
              AND mh.accession_number IS NOT NULL
              AND (a.image_url IS NULL OR a.image_url = '');
        """)
        rows = cur.fetchall()

    updates = []
    for aw_id, acc in rows:
        acc_clean = (acc or "").strip()
        if acc_clean in acc_to_img:
            updates.append((str(aw_id), acc_to_img[acc_clean]))

    print(f"  - MoMA DB 미매핑 대상 중 매칭: {len(updates):,}건")
    updated = batch_update_artwork_images(conn, updates)
    print(f"  ✓ MoMA DB 반영 완료: {updated:,}건 업데이트 (총 {time.time()-t0:.2f}s)")
    return updated


# =========================================================================
# 3. The Met (The Metropolitan Museum of Art): Raw JSON & API
# =========================================================================
def enrich_met(conn: psycopg2.extensions.connection) -> int:
    """The Met 로컬 JSON 및 Open Access API 고화질 이미지 매핑."""
    print("\n--- [3] The Met (Metropolitan Museum of Art) 이미지 매핑 시작 ---")
    t0 = time.time()
    met_dir = RAW_ROOT / "met"
    updates: list[tuple[str, str]] = []

    # 1) 로컬 crawlers/raw/met/<objectID>.json
    if met_dir.exists():
        obj_id_to_img: dict[str, str] = {}
        for p in met_dir.glob("*.json"):
            if p.name.endswith(".meta.json"):
                continue
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                img = d.get("primaryImageSmall") or d.get("primaryImage")
                obj_id = str(d.get("objectID") or p.stem)
                if img:
                    obj_id_to_img[obj_id] = img
            except Exception:
                pass

        print(f"  - Met 로컬 JSON 이미지 보유: {len(obj_id_to_img):,}건")
        if obj_id_to_img:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT a.id, mh.accession_number, s.raw_path
                    FROM artworks a
                    JOIN sources s ON a.source_id = s.id
                    LEFT JOIN museum_holdings mh ON mh.artwork_id = a.id
                    WHERE s.site_name = 'met'
                      AND (a.image_url IS NULL OR a.image_url = '');
                """)
                met_rows = cur.fetchall()

            for aw_id, acc, raw_p in met_rows:
                # check filename in raw_path
                m = re.search(r"/(\d+)\.json$", raw_p or "")
                obj_id = m.group(1) if m else None
                if obj_id and obj_id in obj_id_to_img:
                    updates.append((str(aw_id), obj_id_to_img[obj_id]))

    # 2) Met Open Access API를 통한 주요 대표 소장작품 매핑 (Curated / Highlight works)
    with conn.cursor() as cur:
        cur.execute("""
            SELECT a.id, mh.accession_number
            FROM artworks a
            JOIN sources s ON a.source_id = s.id
            JOIN museum_holdings mh ON mh.artwork_id = a.id
            WHERE s.site_name = 'met'
              AND (a.image_url IS NULL OR a.image_url = '')
              AND mh.accession_number IS NOT NULL
            LIMIT 500;
        """)
        api_targets = cur.fetchall()

    if api_targets:
        print(f"  - Met Open Access API 보강 대상 조회: {len(api_targets)}건")

        # Met API object endpoint query
        def _fetch_met_obj(item: tuple[Any, str]) -> tuple[str, str] | None:
            aw_id, acc = item
            # accession_number e.g. '09.50.2968' or numeric
            try:
                # search by accession_number
                resp = requests.get(
                    "https://collectionapi.metmuseum.org/public/collection/v1/search",
                    params={"q": acc, "isPublicDomain": True},
                    headers={"User-Agent": USER_AGENT},
                    timeout=5,
                )
                if resp.status_code == 200:
                    obj_ids = resp.json().get("objectIDs") or []
                    if obj_ids:
                        target_id = obj_ids[0]
                        o_resp = requests.get(
                            f"https://collectionapi.metmuseum.org/public/collection/v1/objects/{target_id}",
                            headers={"User-Agent": USER_AGENT},
                            timeout=5,
                        )
                        if o_resp.status_code == 200:
                            od = o_resp.json()
                            img = od.get("primaryImageSmall") or od.get("primaryImage")
                            if img:
                                return (str(aw_id), img)
            except Exception:
                pass
            return None

        with ThreadPoolExecutor(max_workers=10) as ex:
            futures = [ex.submit(_fetch_met_obj, it) for it in api_targets[:100]]
            for f in as_completed(futures):
                res = f.result()
                if res:
                    updates.append(res)

    updated = batch_update_artwork_images(conn, updates)
    print(f"  ✓ Met DB 반영 완료: {updated:,}건 업데이트 (총 {time.time()-t0:.2f}s)")
    return updated


# =========================================================================
# 4. Art Institute of Chicago (AIC): IIIF Batch & API
# =========================================================================
def enrich_aic(conn: psycopg2.extensions.connection, limit: int = 1500) -> int:
    """Art Institute of Chicago (AIC) 대표 작품 IIIF 고화질 이미지 URL 매핑."""
    print(f"\n--- [4] Art Institute of Chicago (AIC) 이미지 매핑 시작 (상위 {limit}건) ---")
    t0 = time.time()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT a.id, s.raw_path, mh.accession_number
            FROM artworks a
            JOIN sources s ON a.source_id = s.id
            LEFT JOIN museum_holdings mh ON mh.artwork_id = a.id
            WHERE s.site_name = 'aic'
              AND (a.image_url IS NULL OR a.image_url = '')
            LIMIT %s;
        """, (limit,))
        rows = cur.fetchall()

    if not rows:
        print("  - AIC 미매핑 대상 없음")
        return 0

    id_to_awid: dict[str, str] = {}
    for aw_id, raw_p, acc in rows:
        obj_id = None
        if raw_p:
            m = re.search(r"(\d+)\.json$", raw_p)
            if m:
                obj_id = m.group(1)
        if not obj_id and acc:
            obj_id = acc.strip()
        if obj_id:
            id_to_awid[obj_id] = str(aw_id)

    print(f"  - AIC API 쿼리 대상: {len(id_to_awid)}건 (배치 크기 100)")
    obj_ids = list(id_to_awid.keys())
    updates = []

    def _fetch_aic_batch(batch_ids: list[str]) -> list[tuple[str, str]]:
        batch_updates = []
        try:
            resp = requests.get(
                "https://api.artic.edu/api/v1/artworks",
                params={"ids": ",".join(batch_ids), "fields": "id,image_id,is_public_domain"},
                headers={"User-Agent": USER_AGENT},
                timeout=12,
            )
            if resp.status_code == 200:
                for item in resp.json().get("data") or []:
                    oid = str(item.get("id"))
                    img_id = item.get("image_id")
                    if img_id and oid in id_to_awid:
                        iiif_url = f"https://www.artic.edu/iiif/2/{img_id}/full/843,/0/default.jpg"
                        batch_updates.append((id_to_awid[oid], iiif_url))
        except Exception:
            pass
        return batch_updates

    batches = [obj_ids[i : i + 100] for i in range(0, len(obj_ids), 100)]
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = [ex.submit(_fetch_aic_batch, b) for b in batches]
        for f in as_completed(futures):
            updates.extend(f.result())

    print(f"  - AIC 이미지 URL 획득: {len(updates):,}건")
    updated = batch_update_artwork_images(conn, updates)
    print(f"  ✓ AIC DB 반영 완료: {updated:,}건 업데이트 (총 {time.time()-t0:.2f}s)")
    return updated


# =========================================================================
# 5. Wikidata Collections (Prado, Orsay, Uffizi, Belvedere, etc.)
# =========================================================================
def enrich_wikidata(conn: psycopg2.extensions.connection, limit: int = 1500) -> int:
    """Wikidata 기반 미술관(프라도, 오르세, 우피치 등) P18 고화질 Commons 이미지 매핑."""
    print(f"\n--- [5] Wikidata 미술관 소장 명작 P18 이미지 매핑 시작 (상위 {limit}건) ---")
    t0 = time.time()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT a.id, s.raw_path, a.title
            FROM artworks a
            JOIN sources s ON a.source_id = s.id
            WHERE s.site_name LIKE 'wikidata_%%'
              AND (a.image_url IS NULL OR a.image_url = '')
            ORDER BY a.year_created NULLS LAST
            LIMIT %s;
        """, (limit,))
        rows = cur.fetchall()

    if not rows:
        print("  - Wikidata 미매핑 대상 없음")
        return 0

    qid_to_awid: dict[str, str] = {}
    for aw_id, raw_p, title in rows:
        m = re.search(r"(Q\d+)", raw_p or "")
        if m:
            qid = m.group(1)
            qid_to_awid[qid] = str(aw_id)

    print(f"  - Wikidata QID 파싱: {len(qid_to_awid):,}건 (50개 단위 배치 쿼리)")
    qids = list(qid_to_awid.keys())
    updates = []

    def _fetch_wikidata_batch(batch_qids: list[str]) -> list[tuple[str, str]]:
        batch_res = []
        try:
            resp = requests.get(
                "https://www.wikidata.org/w/api.php",
                params={
                    "action": "wbgetentities",
                    "ids": "|".join(batch_qids),
                    "props": "claims",
                    "format": "json",
                },
                headers={"User-Agent": USER_AGENT},
                timeout=15,
            )
            if resp.status_code == 200:
                entities = resp.json().get("entities") or {}
                for qid, ent in entities.items():
                    claims = ent.get("claims") or {}
                    p18 = claims.get("P18") or []
                    if p18:
                        val = p18[0]["mainsnak"]["datavalue"]["value"]
                        if val and qid in qid_to_awid:
                            url = p18_to_commons_url(val)
                            batch_res.append((qid_to_awid[qid], url))
        except Exception:
            pass
        return batch_res

    batches = [qids[i : i + 50] for i in range(0, len(qids), 50)]
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = [ex.submit(_fetch_wikidata_batch, b) for b in batches]
        for f in as_completed(futures):
            updates.extend(f.result())

    print(f"  - Wikidata P18 Commons 이미지 획득: {len(updates):,}건")
    updated = batch_update_artwork_images(conn, updates)
    print(f"  ✓ Wikidata DB 반영 완료: {updated:,}건 업데이트 (총 {time.time()-t0:.2f}s)")
    return updated


# =========================================================================
# 6. Curated Masterpieces Priority Matching (1,500 High-Priority Works)
# =========================================================================
def enrich_curated_masterpieces(conn: psycopg2.extensions.connection) -> int:
    """1,500점 핵심 대표 명작(vault_curated + 역대 최고가 낙찰작 + 소장작) 우선 정밀 매핑."""
    print("\n--- [6] 주요 대표 명작 (1,500점) 우선 정밀 매핑 시작 ---")
    t0 = time.time()

    # 1. vault_curated/artworks/*.md 에서 id8 추출
    id8_to_filename: dict[str, str] = {}
    if VAULT_CURATED.exists():
        for f in VAULT_CURATED.glob("*.md"):
            m = re.search(r"\(([0-9a-f]{8})\)\.md$", f.name)
            if m:
                id8_to_filename[m.group(1)] = f.name

    print(f"  - Curated Vault 파일: {len(id8_to_filename)}점 식별")

    # 2. DB에서 상위 명작 (경매 최고가 + 대표 소장작 + curated) 1,500점 선정
    with conn.cursor() as cur:
        cur.execute("""
            WITH curated_candidates AS (
                SELECT a.id, a.title, ar.name as artist_name, s.site_name, s.raw_path,
                       mh.accession_number, al.price_usd,
                       ROW_NUMBER() OVER(PARTITION BY a.id ORDER BY al.price_usd DESC NULLS LAST) as rn
                FROM artworks a
                LEFT JOIN artists ar ON ar.id = a.artist_id
                LEFT JOIN sources s ON a.source_id = s.id
                LEFT JOIN museum_holdings mh ON mh.artwork_id = a.id
                LEFT JOIN auction_lots al ON al.artwork_id = a.id
                WHERE substring(a.id::text, 1, 8) = ANY(%s::text[])
                   OR (al.price_usd IS NOT NULL AND al.price_usd >= 100000)
            )
            SELECT id, title, artist_name, site_name, raw_path, accession_number, price_usd
            FROM curated_candidates
            WHERE rn = 1
            ORDER BY price_usd DESC NULLS LAST
            LIMIT 1600;
        """, (list(id8_to_filename.keys()),))
        curated_rows = cur.fetchall()

    print(f"  - 대표 명작 후보 추출: {len(curated_rows)}점")
    updates: list[tuple[str, str]] = []

    # A. Auctions Wikidata (Salvator Mundi, Frida Kahlo, Paul Cézanne, etc.)
    wikidata_qids: dict[str, str] = {}
    bonhams_files: dict[str, list[tuple[str, str]]] = {}

    for aw_id, title, artist_name, site, raw_p, acc, price in curated_rows:
        aw_id_str = str(aw_id)
        if site == "auctions_wikidata" and raw_p:
            m = re.search(r"(Q\d+)", raw_p)
            if m:
                wikidata_qids[m.group(1)] = aw_id_str
        elif site == "bonhams" and raw_p:
            bonhams_files.setdefault(raw_p, []).append((aw_id_str, (title or "").strip()))

    # B. Query Wikidata for high-value auction works
    if wikidata_qids:
        print(f"  - 경매 최고가 Wikidata 명작 {len(wikidata_qids)}점 P18 이미지 조회 중...")
        q_list = list(wikidata_qids.keys())
        for i in range(0, len(q_list), 50):
            chunk = q_list[i : i + 50]
            try:
                resp = requests.get(
                    "https://www.wikidata.org/w/api.php",
                    params={
                        "action": "wbgetentities",
                        "ids": "|".join(chunk),
                        "props": "claims",
                        "format": "json",
                    },
                    headers={"User-Agent": USER_AGENT},
                    timeout=12,
                )
                if resp.status_code == 200:
                    entities = resp.json().get("entities") or {}
                    for qid, ent in entities.items():
                        claims = ent.get("claims") or {}
                        p18 = claims.get("P18") or []
                        if p18 and qid in wikidata_qids:
                            img_fn = p18[0]["mainsnak"]["datavalue"]["value"]
                            url = p18_to_commons_url(img_fn)
                            updates.append((wikidata_qids[qid], url))
            except Exception:
                pass

    # C. Bonhams Curated works from raw JSON
    if bonhams_files:
        print(f"  - Bonhams 명작 {len(bonhams_files)}개 세일 JSON에서 고화질 이미지 매핑 중...")
        for raw_p, aw_items in bonhams_files.items():
            full_p = BASE_DIR / raw_p
            if not full_p.exists():
                continue
            try:
                with open(full_p, "r", encoding="utf-8") as f:
                    sd = json.load(f)
                lots = (sd.get("lotData") or {}).get("auctionLots") or []
                title_to_img = {}
                for l in lots:
                    lt = (l.get("title") or "").strip()
                    limg = (l.get("image") or {}).get("url")
                    if lt and limg:
                        title_to_img[lt] = limg

                for aw_id_str, aw_title in aw_items:
                    if aw_title in title_to_img:
                        updates.append((aw_id_str, title_to_img[aw_title]))
            except Exception:
                pass

    updated = batch_update_artwork_images(conn, updates)
    print(f"  ✓ 대표 명작 우선 매핑 완료: {updated:,}건 업데이트 (총 {time.time()-t0:.2f}s)")
    return updated


# =========================================================================
# 7. SMK (Statens Museum for Kunst): High-Res CC0 Images
# =========================================================================
def enrich_smk(conn: psycopg2.extensions.connection, limit: int = 5000) -> int:
    """SMK(덴마크 국립미술관) 소장작품 고화질 Open Access IIIF 썸네일 매핑."""
    print(f"\n--- [7] SMK (덴마크 국립미술관) 이미지 매핑 시작 (상위 {limit}건) ---")
    t0 = time.time()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT a.id, s.raw_path
            FROM artworks a
            JOIN sources s ON a.source_id = s.id
            WHERE s.site_name = 'smk'
              AND (a.image_url IS NULL OR a.image_url = '')
            LIMIT %s;
        """, (limit,))
        rows = cur.fetchall()

    if not rows:
        print("  - SMK 미매핑 대상 없음")
        return 0

    def _extract_smk(item: tuple[Any, str]) -> tuple[str, str] | None:
        aw_id, raw_p = item
        full_p = BASE_DIR / raw_p
        if not full_p.exists():
            return None
        try:
            with open(full_p, "r", encoding="utf-8") as f:
                d = json.load(f)
            url = d.get("image_thumbnail") or d.get("image_native")
            if url:
                return (str(aw_id), url)
        except Exception:
            pass
        return None

    updates = []
    with ThreadPoolExecutor(max_workers=32) as ex:
        for res in ex.map(_extract_smk, rows):
            if res:
                updates.append(res)

    print(f"  - SMK 이미지 URL 획득: {len(updates):,}건")
    updated = batch_update_artwork_images(conn, updates)
    print(f"  ✓ SMK DB 반영 완료: {updated:,}건 업데이트 (총 {time.time()-t0:.2f}s)")
    return updated


# =========================================================================
# Summary & Verification
# =========================================================================
def print_summary(conn: psycopg2.extensions.connection) -> dict[str, Any]:
    """전체 매핑 결과 및 샘플 통계 리포트 출력."""
    print("\n" + "=" * 65)
    print("         🎨 작품 이미지 URL 보강 및 매핑 종합 결과 리포트")
    print("=" * 65)

    with conn.cursor() as cur:
        # 전체 이미지 보유 건수
        cur.execute("SELECT count(*) FROM artworks WHERE image_url IS NOT NULL AND image_url != '';")
        total_mapped = cur.fetchone()[0]

        # 출처(site_name)별 이미지 보유 건수
        cur.execute("""
            SELECT COALESCE(s.site_name, '기타'), count(a.id)
            FROM artworks a
            JOIN sources s ON a.source_id = s.id
            WHERE a.image_url IS NOT NULL AND a.image_url != ''
            GROUP BY s.site_name
            ORDER BY count(a.id) DESC;
        """)
        site_stats = cur.fetchall()

        # Curated Masterpieces 이미지 매핑 현황
        id8_keys = []
        if VAULT_CURATED.exists():
            for f in VAULT_CURATED.glob("*.md"):
                m = re.search(r"\(([0-9a-f]{8})\)\.md$", f.name)
                if m:
                    id8_keys.append(m.group(1))

        curated_total = len(id8_keys)
        curated_mapped = 0
        if id8_keys:
            cur.execute("""
                SELECT count(*)
                FROM artworks
                WHERE substring(id::text, 1, 8) = ANY(%s::text[])
                  AND image_url IS NOT NULL AND image_url != '';
            """, (id8_keys,))
            curated_mapped = cur.fetchone()[0]

        # 대표 샘플 작품 10건 추출
        cur.execute("""
            SELECT a.title, COALESCE(ar.name, '미상'), COALESCE(s.site_name, '출처'), a.image_url
            FROM artworks a
            LEFT JOIN artists ar ON ar.id = a.artist_id
            LEFT JOIN sources s ON a.source_id = s.id
            WHERE a.image_url IS NOT NULL AND a.image_url != ''
            ORDER BY random()
            LIMIT 10;
        """)
        samples = cur.fetchall()

    print(f"\n📊 [총계] 고화질 이미지 URL 매핑 완료: 총 {total_mapped:,}건")
    if curated_total > 0:
        pct = (curated_mapped / curated_total) * 100
        print(f"🏆 [대표 명작] Curated Vault 1,200선 매핑: {curated_mapped:,}/{curated_total:,}점 ({pct:.1f}%)")

    print("\n🏛️ [기관 및 소스별 매핑 현황]")
    for site, cnt in site_stats:
        print(f"  - {site:25s}: {cnt:>8,}건")

    print("\n🖼️ [대표 명작 및 소장작품 샘플 결과 (10선)]")
    for idx, (title, artist, site, url) in enumerate(samples, 1):
        clean_title = (title or "무제")[:30]
        print(f"  {idx:2d}. [{site}] {clean_title} ({artist})")
        print(f"      🔗 {url}")

    print("=" * 65)
    return {
        "total_mapped": total_mapped,
        "curated_mapped": curated_mapped,
        "curated_total": curated_total,
        "site_stats": site_stats,
        "samples": samples,
    }


def main():
    start_time = time.time()
    print("=" * 65)
    print("       아트그래프(artrend) 작품 이미지 URL 보강 및 일괄 매핑 파이프라인")
    print("=" * 65)

    conn = get_db_connection()
    try:
        ensure_schema(conn)

        # 1. 주요 대표 명작 (1,500점) 우선 정밀 매핑
        enrich_curated_masterpieces(conn)

        # 2. Cleveland Museum of Art (오픈 액세스 6.7만 전량)
        enrich_cleveland(conn)

        # 3. MoMA (오픈 액세스 12만)
        enrich_moma(conn)

        # 4. The Met (2천점 로컬 및 Open Access API)
        enrich_met(conn)

        # 5. Art Institute of Chicago (AIC IIIF Open Access)
        enrich_aic(conn, limit=1500)

        # 6. Wikidata 주요 미술관 (프라도, 오르세, 우피치 등 P18 Commons)
        enrich_wikidata(conn, limit=1500)

        # 7. SMK (덴마크 국립미술관 IIIF 5천점)
        enrich_smk(conn, limit=5000)

        # 종합 리포트
        print_summary(conn)

        elapsed = time.time() - start_time
        print(f"\n🎉 전체 파이프라인 처리 완료! 소요시간: {elapsed:.2f}초\n")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
