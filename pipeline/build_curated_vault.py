"""Curated Obsidian Vault Builder V3 (Cleaned, Aligned, & High Quality).

Key Improvements in V3:
1. Complete separation of Museum Holding vs Auction House in Artwork notes.
2. Filter out Untitled / Drawing / Photograph / Q-ID items from curated Artworks.
3. Enhanced noise filtering for Artists (exclude Century, School of, Follower of, etc.).
4. Accurate Table Alignment & Title Truncation (prevent line wrap and broken markdown tables).
5. Contextual Market Analytics: Differentiate modern major sales (>= 1950) vs historical archive provenance.
6. Clean Auction Status: Do not mark '낙찰' when price is empty or unknown.
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import time
from collections import defaultdict
from pathlib import Path

import psycopg2

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(line_buffering=True)

VAULT_DIR = Path(__file__).resolve().parent.parent / "vault_curated"

MAX_ARTIST_WORKS = 60
MAX_ARTIST_AUCTIONS = 60
MAX_MUSEUM_HIGHLIGHTS = 60
MAX_GALLERY_ARTISTS = 100
MAX_AUCTION_LOTS = 60
MAX_COLLECTOR_PROV = 60


def slugify(name: str, uid: str) -> str:
    name = (name or "무제").strip()
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    name = "".join(c for c in name if c.isprintable())
    name = re.sub(r"\s+", " ", name).strip()
    name = name[:75]
    return f"{name} ({str(uid)[:8]})"


def escape_cell(value) -> str:
    if value is None:
        return ""
    return str(value).replace("|", "\\|").replace("\n", " ").replace("\r", " ").strip()


def truncate_cell(value: str | None, max_len: int = 55) -> str:
    val_clean = escape_cell(value or "-")
    if len(val_clean) > max_len:
        return val_clean[:max_len].rstrip() + "..."
    return val_clean


def format_usd(val: int | float | None) -> str:
    if val is None or val == 0:
        return "-"
    try:
        val_int = int(round(val))
        if val_int >= 1_000_000_000:
            return f"${val_int/1_000_000_000:.2f}B (${val_int:,})"
        elif val_int >= 1_000_000:
            return f"${val_int/1_000_000:.2f}M (${val_int:,})"
        elif val_int >= 1_000:
            return f"${val_int/1_000:.1f}K (${val_int:,})"
        return f"${val_int:,}"
    except (ValueError, TypeError):
        return str(val)


def format_price_with_curr(price: float | None, curr: str | None, usd: float | None) -> str:
    if price is None or price == 0:
        return "-"
    curr_str = curr or "USD"
    price_fmt = f"{int(round(price)):,} {curr_str}"
    if usd and usd > 0 and curr_str.upper() not in ["USD", "US$", "$"]:
        return f"**${int(round(usd)):,}** ({price_fmt})"
    elif usd and usd > 0:
        return f"**${int(round(usd)):,}**"
    return price_fmt


def format_number(val: int | float | None) -> str:
    if val is None:
        return "-"
    try:
        return f"{int(val):,}"
    except (ValueError, TypeError):
        return str(val)


def build_frontmatter(aliases: list[str] | None = None, **fields) -> str:
    lines = ["---"]
    for key, value in fields.items():
        if value is None or value == "":
            continue
        if isinstance(value, (int, float, bool)):
            lines.append(f"{key}: {value}")
        else:
            v_str = str(value).replace('"', "'").replace("\n", " ").replace("\r", " ")
            lines.append(f'{key}: "{v_str}"')
    if aliases:
        clean_aliases = list(dict.fromkeys([a.strip() for a in aliases if a and a.strip()]))
        if clean_aliases:
            lines.append("aliases:")
            for a in clean_aliases:
                a_esc = a.replace('"', "'").replace("\n", " ")
                lines.append(f'  - "{a_esc}"')
    lines.append("---\n")
    return "\n".join(lines)


def write_md(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main():
    start_time = time.time()
    print("==================================================")
    print("  Curated Obsidian Vault Builder V4 (authority/events)")
    print(f"  출력 디렉토리: {VAULT_DIR}")
    print("==================================================")

    # Clean target directory
    if VAULT_DIR.exists():
        print("기존 vault_curated 디렉토리 정리 중...")
        for sub in ["artists", "museums", "galleries", "auction_houses", "collectors", "artworks"]:
            subdir = VAULT_DIR / sub
            if subdir.exists():
                shutil.rmtree(subdir)
        dashboard_file = VAULT_DIR / "00 대시보드.md"
        if dashboard_file.exists():
            dashboard_file.unlink()

    VAULT_DIR.mkdir(parents=True, exist_ok=True)
    for sub in ["artists", "museums", "galleries", "auction_houses", "collectors", "artworks"]:
        (VAULT_DIR / sub).mkdir(parents=True, exist_ok=True)

    conn = psycopg2.connect("postgresql://postgres@127.0.0.1:5433/artrend")
    conn.set_client_encoding("UTF8")
    cur = conn.cursor()

    # -------------------------------------------------------------
    # 1. Selection & Slug Dictionaries
    # -------------------------------------------------------------
    print("\n[1/7] 핵심 엔티티 선별 및 고유 슬러그 맵 생성 중...")

    # 1-1. Museums (400)
    cur.execute("""
        SELECT m.id, m.name, m.name_en, m.country, m.city, m.type, m.website,
               count(mh.id) as holding_cnt
        FROM museums m
        LEFT JOIN museum_holdings mh ON mh.museum_id = m.id
        GROUP BY m.id, m.name, m.name_en, m.country, m.city, m.type, m.website
        ORDER BY holding_cnt DESC
        LIMIT 400;
    """)
    museum_rows = cur.fetchall()
    museum_slugs: dict[str, str] = {}
    museum_names: dict[str, str] = {}
    selected_museum_ids = []
    for r in museum_rows:
        m_id, m_name = str(r[0]), r[1]
        slug = slugify(m_name, m_id)
        museum_slugs[m_id] = slug
        museum_names[m_id] = m_name
        selected_museum_ids.append(m_id)
    print(f"  - 선별된 미술관: {len(museum_rows)}곳")

    # 1-2. Galleries (250)
    cur.execute("""
        SELECT g.id, g.name, g.city, g.country, g.website,
               count(gr.id) as rep_cnt
        FROM galleries g
        LEFT JOIN gallery_representations gr ON gr.gallery_id = g.id
        GROUP BY g.id, g.name, g.city, g.country, g.website
        ORDER BY rep_cnt DESC, g.name
        LIMIT 250;
    """)
    gallery_rows = cur.fetchall()
    gallery_slugs: dict[str, str] = {}
    gallery_names: dict[str, str] = {}
    selected_gallery_ids = []
    for r in gallery_rows:
        g_id, g_name = str(r[0]), r[1]
        slug = slugify(g_name, g_id)
        gallery_slugs[g_id] = slug
        gallery_names[g_id] = g_name
        selected_gallery_ids.append(g_id)
    print(f"  - 선별된 갤러리: {len(gallery_rows)}곳")

    # 1-3. Auction Houses (250)
    cur.execute("""
        SELECT ah.id, ah.name, ah.country,
               count(DISTINCT au.id) as auction_cnt,
               count(al.id) as lot_cnt,
               COALESCE(SUM(al.price_usd), 0) as total_volume_usd
        FROM auction_houses ah
        LEFT JOIN auctions au ON au.auction_house_id = ah.id
        LEFT JOIN auction_lots al ON al.auction_id = au.id
        GROUP BY ah.id, ah.name, ah.country
        ORDER BY lot_cnt DESC, auction_cnt DESC
        LIMIT 250;
    """)
    house_rows = cur.fetchall()
    house_slugs: dict[str, str] = {}
    house_names: dict[str, str] = {}
    selected_house_ids = []
    for r in house_rows:
        h_id, h_name = str(r[0]), r[1]
        slug = slugify(h_name, h_id)
        house_slugs[h_id] = slug
        house_names[h_id] = h_name
        selected_house_ids.append(h_id)
    print(f"  - 선별된 경매사: {len(house_rows)}곳")

    # 1-4. Collectors (500)
    cur.execute("""
        SELECT c.id, c.name, c.bio, c.is_institution, count(pr.id) as prov_cnt
        FROM collectors c
        JOIN provenance_records pr ON pr.owner_collector_id = c.id
        GROUP BY c.id, c.name, c.bio, c.is_institution
        HAVING count(pr.id) >= 3
        ORDER BY prov_cnt DESC
        LIMIT 500;
    """)
    collector_rows = cur.fetchall()
    collector_slugs: dict[str, str] = {}
    collector_names: dict[str, str] = {}
    selected_collector_ids = []
    for r in collector_rows:
        c_id, c_name = str(r[0]), r[1]
        slug = slugify(c_name, c_id)
        collector_slugs[c_id] = slug
        collector_names[c_id] = c_name
        selected_collector_ids.append(c_id)
    print(f"  - 선별된 컬렉터: {len(collector_rows)}명")

    # 1-5. Artists Pre-Metrics & Selection (2,500)
    print("  - 작가 노이즈 정밀 필터링 및 상위 2,500명 선별 중...")

    cur.execute("""
        SELECT a.artist_id, count(mh.id)
        FROM museum_holdings mh
        JOIN artworks a ON a.id = mh.artwork_id
        WHERE a.artist_id IS NOT NULL AND a.attribution_qualifier IS NULL
        GROUP BY a.artist_id
    """)
    artist_holdings_count = {str(r[0]): r[1] for r in cur.fetchall()}

    # 2026-09-16 V4: artist_market_metrics 삭제 후 경매 축이 0으로 죽어 있었음 → auction_lots에서 직접 집계(귀속 한정 작품 제외)
    cur.execute("""
        SELECT a.artist_id, count(al.id)
        FROM auction_lots al JOIN artworks a ON a.id = al.artwork_id
        WHERE a.artist_id IS NOT NULL AND a.attribution_qualifier IS NULL
        GROUP BY a.artist_id
    """)
    artist_lots_count = {str(r[0]): r[1] for r in cur.fetchall()}
    cur.execute("SELECT artist_id, count(*) FROM exhibition_artists GROUP BY artist_id")
    artist_exh_count = {str(r[0]): r[1] for r in cur.fetchall()}

    cur.execute("""
        SELECT artist_id, count(gallery_id)
        FROM gallery_representations
        GROUP BY artist_id
    """)
    artist_reps_count = {str(r[0]): r[1] for r in cur.fetchall()}

    # Fetch market metrics for artists
    # 2026-09-15 §W2: artist_market_metrics는 db/migrations/0004에서 DROP됨
    # (가짜 시장지표 — 역사 통화 임의 환율 기반). 테이블이 없으면 빈 dict로 폴백.
    artist_market_map = {}
    try:
        cur.execute("""
            SELECT
                artist_id,
                total_lots_offered,
                total_lots_sold,
                sold_rate_pct,
                total_turnover_usd,
                avg_price_usd,
                record_price_usd,
                record_price_original,
                record_currency,
                record_artwork_id,
                record_artwork_title,
                record_auction_house_name,
                record_sale_date
            FROM artist_market_metrics;
        """)
        for r in cur.fetchall():
            artist_market_map[str(r[0])] = {
                "offered": r[1],
                "sold": r[2],
                "sold_rate": float(r[3] or 0),
                "turnover_usd": float(r[4] or 0),
                "avg_price_usd": float(r[5] or 0),
                "record_usd": float(r[6] or 0),
                "record_orig": float(r[7] or 0) if r[7] else None,
                "record_curr": r[8],
                "record_art_id": str(r[9]) if r[9] else None,
                "record_art_title": r[10],
                "record_house": r[11],
                "record_date": r[12],
            }
    except Exception:
        conn.rollback()
        print("  [경고] artist_market_metrics 테이블 없음 — 시장 지표 없이 진행")

    cur.execute("""
        SELECT id, name, name_en, birth_year, death_year, nationality, bio, wikidata_qid, ulan_id
        FROM artists
        WHERE entity_kind = 'person'   -- 2026-09-16 V4: 익명/문화권/기업/귀속 스텁은 entity_kind(0007)로 분류됨 — 이름 ILIKE 필터 대체
          AND name NOT ILIKE '%anoniem%' 
          AND name NOT ILIKE '%unknown%'
          AND name NOT ILIKE '%anonymous%'
          AND name NOT ILIKE '%unidentified%'
          AND name NOT ILIKE '%unbekannt%'
          AND name NOT ILIKE '%anonyme%'
          AND name NOT ILIKE '%maker%'
          AND name NOT ILIKE '%various%'
          AND name NOT ILIKE '%photographer%'
          AND name NOT ILIKE '%unbek%'
          AND name NOT ILIKE '%Jahrhundert%'
          AND name NOT ILIKE '%Century%'
          AND name NOT ILIKE '%School of%'
          AND name NOT ILIKE '%Follower of%'
          AND name NOT ILIKE '%Circle of%'
          AND name NOT ILIKE '%Manner of%'
          AND name NOT ILIKE '%After %'
          AND name NOT ILIKE '%Style of%'
          AND name NOT ILIKE '%Workshop of%'
          AND length(trim(name)) >= 2
    """)
    candidate_artists = cur.fetchall()

    scored_artists = []
    for r in candidate_artists:
        a_id = str(r[0])
        h_cnt = artist_holdings_count.get(a_id, 0)
        r_cnt = artist_reps_count.get(a_id, 0)
        m_info = artist_market_map.get(a_id, {})
        a_cnt = artist_lots_count.get(a_id, 0)
        e_cnt = artist_exh_count.get(a_id, 0)
        has_auth = bool(r[7] or r[8])

        if h_cnt == 0 and r_cnt == 0 and a_cnt == 0 and e_cnt == 0:
            continue

        # V4 scoring: 관계 축 수(소장·경매·갤러리·전시)를 우선. 단일 소스 대량(Turner 4만 점 유증 등)이 카운트만으로 상위를
        # 차지하지 않게 소장·경매 기여는 300건 상한. authority(ULAN/QID) 보유는 정본화된 작가라 가산.
        axes = sum(1 for v in (h_cnt, a_cnt, r_cnt, e_cnt) if v > 0)
        score = (r_cnt * 100.0) + (min(a_cnt, 300) * 3.0) + min(h_cnt, 300) * 1.0 + (min(e_cnt, 30) * 20.0) + (axes - 1) * 300.0
        if has_auth:
            score += 50.0

        if axes >= 2 or h_cnt >= 10 or r_cnt >= 1 or a_cnt >= 10 or e_cnt >= 3:
            scored_artists.append((r, h_cnt, r_cnt, a_cnt, score, m_info))

    scored_artists.sort(key=lambda x: x[4], reverse=True)
    selected_artists = scored_artists[:2500]

    artist_slugs: dict[str, str] = {}
    artist_names: dict[str, str] = {}
    selected_artist_ids = []
    for r, h_cnt, r_cnt, a_cnt, score, m_info in selected_artists:
        a_id = str(r[0])
        a_name = r[1]
        slug = slugify(a_name, a_id)
        artist_slugs[a_id] = slug
        artist_names[a_id] = a_name
        selected_artist_ids.append(a_id)
    print(f"  - 선별된 핵심 작가: {len(selected_artists)}명")

    # 1-6. Curated Artworks Selection (Top ~1,200 Verified Masterpieces)
    print("  - 엄선된 대표 명작(Verified Masterpieces) 선별 중...")

    # Top auction record works with clean title filter
    cur.execute("""
        SELECT a.id, a.title, a.year_created, a.medium, a.dimensions, a.artist_id, ar.name,
               al.price_usd, al.hammer_price, al.currency, al.lot_number, au.auction_date, ah.id, ah.name,
               a.image_url
        FROM auction_lots al
        JOIN artworks a ON a.id = al.artwork_id
        JOIN auctions au ON au.id = al.auction_id
        JOIN auction_houses ah ON ah.id = au.auction_house_id
        LEFT JOIN artists ar ON ar.id = a.artist_id
        WHERE al.price_usd IS NOT NULL AND al.price_usd >= 50000
          AND (al.sold = TRUE OR al.sold IS NULL)
          AND a.title IS NOT NULL
          AND length(trim(a.title)) >= 3
          AND a.title NOT ILIKE '%(제목 없음)%'
          AND a.title NOT ILIKE '%untitled%'
          AND a.title NOT ILIKE '%no title%'
          AND a.title NOT ILIKE '%sans titre%'
          AND a.title NOT ILIKE '%drawing%'
          AND a.title NOT ILIKE '%photograph%'
          AND a.title NOT ILIKE '%print%'
          AND a.title !~ '^Q[0-9]{6,}$'
        ORDER BY al.price_usd DESC
        LIMIT 600;
    """)
    top_auction_artworks = cur.fetchall()

    # Top museum masterpieces from curated museums & artists
    cur.execute("""
        SELECT a.id, a.title, a.year_created, a.medium, a.dimensions, a.artist_id, ar.name,
               mh.museum_id, m.name, a.image_url
        FROM museum_holdings mh
        JOIN artworks a ON a.id = mh.artwork_id
        JOIN museums m ON m.id = mh.museum_id
        JOIN artists ar ON ar.id = a.artist_id
        WHERE mh.museum_id = ANY(%s::uuid[])
          AND a.artist_id = ANY(%s::uuid[])
          AND a.title IS NOT NULL
          AND length(trim(a.title)) >= 3
          AND a.title NOT ILIKE '%%(제목 없음)%%'
          AND a.title NOT ILIKE '%%untitled%%'
          AND a.title NOT ILIKE '%%no title%%'
          AND a.title NOT ILIKE '%%sans titre%%'
          AND a.title NOT ILIKE '%%drawing%%'
          AND a.title NOT ILIKE '%%photograph%%'
          AND a.title NOT ILIKE '%%print%%'
          AND a.title !~ '^Q[0-9]{6,}$'
        ORDER BY a.year_created NULLS LAST
        LIMIT 600;
    """, (selected_museum_ids, selected_artist_ids))
    top_museum_artworks = cur.fetchall()

    artwork_slugs: dict[str, str] = {}
    artwork_names: dict[str, str] = {}
    selected_artwork_rows = {}

    for r in top_auction_artworks:
        aw_id = str(r[0])
        aw_title = r[1].strip()
        if aw_id not in selected_artwork_rows:
            slug = slugify(aw_title, aw_id)
            artwork_slugs[aw_id] = slug
            artwork_names[aw_id] = aw_title
            selected_artwork_rows[aw_id] = {
                "id": aw_id,
                "title": aw_title,
                "year": r[2],
                "medium": r[3],
                "dims": r[4],
                "artist_id": str(r[5]) if r[5] else None,
                "artist_name": r[6],
                "price_usd": r[7],
                "hammer": r[8],
                "curr": r[9],
                "lot": r[10],
                "sale_date": r[11],
                "house_id": str(r[12]) if r[12] else None,
                "house_name": r[13],
                "museum_id": None,
                "museum_name": None,
                "image_url": r[14],
            }

    for r in top_museum_artworks:
        aw_id = str(r[0])
        aw_title = r[1].strip()
        img_url = r[9]
        if aw_id not in selected_artwork_rows:
            slug = slugify(aw_title, aw_id)
            artwork_slugs[aw_id] = slug
            artwork_names[aw_id] = aw_title
            selected_artwork_rows[aw_id] = {
                "id": aw_id,
                "title": aw_title,
                "year": r[2],
                "medium": r[3],
                "dims": r[4],
                "artist_id": str(r[5]) if r[5] else None,
                "artist_name": r[6],
                "price_usd": None,
                "hammer": None,
                "curr": None,
                "lot": None,
                "sale_date": None,
                "house_id": None,
                "house_name": None,
                "museum_id": str(r[7]),
                "museum_name": r[8],
                "image_url": img_url,
            }
        else:
            selected_artwork_rows[aw_id]["museum_id"] = str(r[7])
            selected_artwork_rows[aw_id]["museum_name"] = r[8]
            if img_url and not selected_artwork_rows[aw_id].get("image_url"):
                selected_artwork_rows[aw_id]["image_url"] = img_url

    selected_artwork_ids = list(selected_artwork_rows.keys())
    print(f"  - 선별된 대표 명작(Artworks): {len(selected_artwork_ids)}점")

    total_curated_entities = (
        len(selected_artists) + len(museum_rows) + len(gallery_rows) + len(house_rows) + len(collector_rows) + len(selected_artwork_ids)
    )
    print(f"  -> 총 큐레이션 지식 그래프 엔티티 수: {total_curated_entities:,}개")

    # Helpers for link creation
    def artist_link(a_id: str | None, a_name: str | None, in_table: bool = True) -> str:
        if not a_id:
            return escape_cell(a_name or "작자 미상")
        p = "\\|" if in_table else "|"
        if a_id in artist_slugs:
            return f"[[{artist_slugs[a_id]}{p}{escape_cell(a_name)}]]"
        return escape_cell(a_name or "미상")

    def artwork_link(aw_id: str | None, aw_title: str | None, max_len: int = 45, in_table: bool = True) -> str:
        if not aw_id:
            return truncate_cell(aw_title or "무제", max_len)
        display_t = truncate_cell(aw_title or "무제", max_len)
        p = "\\|" if in_table else "|"
        if aw_id in artwork_slugs:
            return f"[[{artwork_slugs[aw_id]}{p}{display_t}]]"
        return display_t

    def museum_link(m_id: str | None, m_name: str | None, in_table: bool = True) -> str:
        if not m_id:
            return escape_cell(m_name or "-")
        p = "\\|" if in_table else "|"
        if m_id in museum_slugs:
            return f"[[{museum_slugs[m_id]}{p}{escape_cell(m_name)}]]"
        return escape_cell(m_name or "-")

    def gallery_link(g_id: str | None, g_name: str | None, in_table: bool = True) -> str:
        if not g_id:
            return escape_cell(g_name or "-")
        p = "\\|" if in_table else "|"
        if g_id in gallery_slugs:
            return f"[[{gallery_slugs[g_id]}{p}{escape_cell(g_name)}]]"
        return escape_cell(g_name or "-")

    def house_link(h_id: str | None, h_name: str | None, in_table: bool = True) -> str:
        if not h_id:
            return escape_cell(h_name or "-")
        p = "\\|" if in_table else "|"
        if h_id in house_slugs:
            return f"[[{house_slugs[h_id]}{p}{escape_cell(h_name)}]]"
        return escape_cell(h_name or "-")

    def collector_link(c_id: str | None, c_name: str | None, in_table: bool = True) -> str:
        if not c_id:
            return escape_cell(c_name or "-")
        p = "\\|" if in_table else "|"
        if c_id in collector_slugs:
            return f"[[{collector_slugs[c_id]}{p}{escape_cell(c_name)}]]"
        return escape_cell(c_name or "-")

    # -------------------------------------------------------------
    # 2. Export Artworks (Bridge Notes)
    # -------------------------------------------------------------
    print("\n[2/7] 대표 명작(Artworks) 브릿지 마크다운 생성 중...")

    # Fetch provenance for selected artworks
    cur.execute("""
        SELECT pr.artwork_id, pr.owner_type,
               COALESCE(c.name, m.name, g.name, ah.name, pr.note) as owner_name,
               pr.acquired_date, pr.disposed_date,
               pr.acquired_method, pr.owner_collector_id, pr.owner_museum_id, pr.owner_gallery_id
        FROM provenance_records pr
        LEFT JOIN collectors c ON c.id = pr.owner_collector_id
        LEFT JOIN museums m ON m.id = pr.owner_museum_id
        LEFT JOIN galleries g ON g.id = pr.owner_gallery_id
        LEFT JOIN auction_houses ah ON ah.id = pr.owner_auction_house_id
        WHERE pr.artwork_id = ANY(%s::uuid[])
        ORDER BY pr.acquired_date NULLS LAST;
    """, (selected_artwork_ids,))
    artwork_provenance = defaultdict(list)
    for aw_id, o_type, o_name, p_s, p_e, meth, c_id, m_id, g_id in cur.fetchall():
        artwork_provenance[str(aw_id)].append({
            "type": o_type,
            "name": o_name,
            "start": p_s,
            "end": p_e,
            "method": meth,
            "collector_id": str(c_id) if c_id else None,
            "museum_id": str(m_id) if m_id else None,
            "gallery_id": str(g_id) if g_id else None,
        })

    for aw_id, d in selected_artwork_rows.items():
        title = d["title"]
        slug = artwork_slugs[aw_id]
        a_id = d["artist_id"]
        a_name = d["artist_name"]
        yr = d["year"]
        med = d["medium"]
        dims = d["dims"]
        p_usd = d["price_usd"]
        hammer = d["hammer"]
        curr = d["curr"]
        lot = d["lot"]
        s_date = d["sale_date"]
        h_id = d["house_id"]
        h_name = d["house_name"]
        m_id = d["museum_id"]
        m_name = d["museum_name"]

        aliases = [title]
        if a_name:
            aliases.append(f"{a_name} - {title}")

        img_url = d.get("image_url")

        fm = build_frontmatter(
            aliases=aliases,
            type="artwork",
            title=title,
            artist=a_name,
            year_created=yr,
            medium=med,
            dimensions=dims,
            price_usd=p_usd,
            currency=curr,
            current_location=m_name if m_name else (f"{h_name} (경매 출품)" if h_name else None),
            image_url=img_url if img_url else None,
        )

        body = [f"# {title}\n"]

        badges = []
        if a_name:
            badges.append(f"**작가**: {artist_link(a_id, a_name)}")
        if yr:
            badges.append(f"**제작연도**: {yr}")
        if med:
            badges.append(f"**매체**: {med}")
        if p_usd and p_usd > 0:
            badges.append(f"**낙찰가**: {format_price_with_curr(hammer, curr, p_usd)}")
        if badges:
            body.append("> " + " | ".join(badges) + "\n")

        # High-res Image Embedding
        if img_url:
            body.append(f"![{title}|550]({img_url})\n")

        # Museum Holding Section
        if m_id or m_name:
            body.append("## 🏛️ 소장 미술관")
            body.append(f"- **소장기관**: {museum_link(m_id, m_name)}")
            body.append("")

        # Auction Details Section
        if h_id or h_name or p_usd:
            body.append("## 🔨 경매 낙찰 기록")
            body.append(f"- **경매사**: {house_link(h_id, h_name)}")
            if s_date:
                body.append(f"- **경매일자**: {s_date}")
            if lot:
                body.append(f"- **Lot 번호**: #{lot}")
            if p_usd and p_usd > 0:
                body.append(f"- **최종 낙찰가**: {format_price_with_curr(hammer, curr, p_usd)}")
            body.append("")

        # Provenance Timeline
        prov_list = artwork_provenance.get(aw_id, [])
        if prov_list:
            body.append("## 📜 소장 및 이전 이력 (Provenance)")
            body.append("| 시기 | 소유자 / 기관 | 이전 방식 | 분류 |")
            body.append("|---|---|---|---|")
            for p in prov_list:
                period = f"{p['start'] or ''} ~ {p['end'] or ''}".strip(" ~") or "-"
                owner_str = truncate_cell(p["name"], 40)
                if p["collector_id"]:
                    owner_str = collector_link(p["collector_id"], p["name"])
                elif p["museum_id"]:
                    owner_str = museum_link(p["museum_id"], p["name"])
                elif p["gallery_id"]:
                    owner_str = gallery_link(p["gallery_id"], p["name"])

                meth_str = truncate_cell(p["method"] or "-", 25)
                type_str = truncate_cell(p["type"] or "-", 20)
                body.append(f"| {period} | {owner_str} | {meth_str} | {type_str} |")
            body.append("")

        write_md(VAULT_DIR / "artworks" / f"{slug}.md", fm + "\n".join(body))

    print(f"  -> 대표 명작 마크다운 {len(selected_artwork_rows)}개 생성 완료")

    # -------------------------------------------------------------
    # 3. Export Artists
    # -------------------------------------------------------------
    print("\n[3/7] 작가(Artists) 마크다운 생성 중...")

    cur.execute("""
        SELECT gr.artist_id, g.id, g.name
        FROM gallery_representations gr
        JOIN galleries g ON g.id = gr.gallery_id
        WHERE gr.artist_id = ANY(%s::uuid[])
    """, (selected_artist_ids,))
    artist_to_galleries = defaultdict(list)
    for a_id, g_id, g_name in cur.fetchall():
        artist_to_galleries[str(a_id)].append((str(g_id), g_name))

    # Fetch holdings works for selected artists
    cur.execute("""
        SELECT a.artist_id, a.id, a.title, a.year_created, a.medium, mh.museum_id, m.name
        FROM artworks a
        JOIN museum_holdings mh ON mh.artwork_id = a.id
        JOIN museums m ON m.id = mh.museum_id
        WHERE a.artist_id = ANY(%s::uuid[])
    """, (selected_artist_ids,))
    artist_to_works = defaultdict(list)
    artist_to_museum_stats = defaultdict(lambda: defaultdict(int))
    for a_id, aw_id, title, yr, med, m_id, m_name in cur.fetchall():
        a_id_str = str(a_id)
        artist_to_museum_stats[a_id_str][(str(m_id), m_name)] += 1
        if len(artist_to_works[a_id_str]) < MAX_ARTIST_WORKS:
            artist_to_works[a_id_str].append((str(aw_id), title, yr, med, str(m_id), m_name))

    # Fetch auction lots for selected artists
    cur.execute("""
        SELECT a.artist_id, ah.id, ah.name, au.auction_date, al.hammer_price, al.currency, al.sold, a.id, a.title, al.price_usd
        FROM artworks a
        JOIN auction_lots al ON al.artwork_id = a.id
        JOIN auctions au ON au.id = al.auction_id
        JOIN auction_houses ah ON ah.id = au.auction_house_id
        WHERE a.artist_id = ANY(%s::uuid[])
        ORDER BY al.price_usd DESC NULLS LAST
    """, (selected_artist_ids,))
    artist_to_auctions = defaultdict(list)
    for a_id, ah_id, ah_name, a_date, hammer, curr, sold, aw_id, aw_title, p_usd in cur.fetchall():
        a_id_str = str(a_id)
        if len(artist_to_auctions[a_id_str]) < MAX_ARTIST_AUCTIONS:
            artist_to_auctions[a_id_str].append((str(ah_id), ah_name, a_date, hammer, curr, sold, str(aw_id), aw_title, p_usd))

    # V4: 전시·수상 이력(0009) — 최신순
    cur.execute("""
        SELECT ea.artist_id, e.title, e.start_date, e.end_date, coalesce(m.name, g.name, e.venue_name), e.url
        FROM exhibition_artists ea JOIN exhibitions e ON e.id = ea.exhibition_id
        LEFT JOIN museums m ON m.id = e.museum_id LEFT JOIN galleries g ON g.id = e.gallery_id
        WHERE ea.artist_id = ANY(%s::uuid[])
        ORDER BY e.start_date DESC NULLS LAST
    """, (selected_artist_ids,))
    artist_to_exhibitions = defaultdict(list)
    for a_id, title, sd, ed, venue, url in cur.fetchall():
        if len(artist_to_exhibitions[str(a_id)]) < 20:
            artist_to_exhibitions[str(a_id)].append((title, sd, ed, venue, url))
    cur.execute("""
        SELECT artist_id, event_date, detail FROM artist_events
        WHERE event_kind = 'award' AND artist_id = ANY(%s::uuid[]) ORDER BY event_date DESC NULLS LAST
    """, (selected_artist_ids,))
    artist_to_awards = defaultdict(list)
    for a_id, d, detail in cur.fetchall():
        if len(artist_to_awards[str(a_id)]) < 15:
            artist_to_awards[str(a_id)].append((d, detail))

    for idx, (r, h_cnt, r_cnt, a_cnt, score, m_info) in enumerate(selected_artists, 1):
        a_id = str(r[0])
        name = r[1]
        name_en = r[2]
        birth = r[3]
        death = r[4]
        nat = r[5]
        bio = r[6]
        qid, ulan = r[7], r[8]
        slug = artist_slugs[a_id]

        aliases = [name]
        if name_en:
            aliases.append(name_en)

        rec_usd = m_info.get("record_usd", 0)
        rec_title = m_info.get("record_art_title")
        rec_art_id = m_info.get("record_art_id")
        rec_house = m_info.get("record_house")
        rec_date = m_info.get("record_date")
        turnover = m_info.get("turnover_usd", 0)
        sold_rate = m_info.get("sold_rate", 0)
        sold_cnt = m_info.get("sold", 0)

        fm = build_frontmatter(
            aliases=aliases,
            type="artist",
            name=name,
            name_en=name_en,
            birth_year=birth,
            death_year=death,
            nationality=nat,
            holdings_count=h_cnt,
            auction_count=a_cnt,
            gallery_count=r_cnt,
            exhibition_count=len(artist_to_exhibitions.get(a_id, [])),
            wikidata_qid=qid,
            ulan_id=ulan,
            market_record_usd=rec_usd if rec_usd > 0 else None,
            total_turnover_usd=turnover if turnover > 0 else None,
            sold_rate_pct=sold_rate if a_cnt > 0 else None,
            curated_score=int(score),
        )

        lifespan = ""
        if birth or death:
            lifespan = f" ({birth or ''} ~ {death or ''})"

        body = [f"# {name}{lifespan}\n"]

        meta_badges = []
        if nat:
            meta_badges.append(f"**국적**: {nat}")
        if h_cnt > 0:
            meta_badges.append(f"**소장품**: {h_cnt:,}점")
        if a_cnt > 0:
            meta_badges.append(f"**경매기록**: {a_cnt:,}건")
        if r_cnt > 0:
            meta_badges.append(f"**전속/취급 갤러리**: {r_cnt}곳")
        if artist_to_exhibitions.get(a_id):
            meta_badges.append(f"**전시 기록**: {len(artist_to_exhibitions[a_id])}건")
        if qid or ulan:
            meta_badges.append("**정본 ID**: " + " / ".join(x for x in (f"Wikidata {qid}" if qid else None, f"ULAN {ulan}" if ulan else None) if x))
        if meta_badges:
            body.append("> " + " | ".join(meta_badges) + "\n")

        # Refined Market Analytics Summary
        rec_year = None
        if rec_date:
            try:
                rec_year = int(str(rec_date).split("-")[0])
            except Exception:
                pass

        if rec_usd >= 10000 and (rec_year is None or rec_year >= 1950):
            rec_art_link = artwork_link(rec_art_id, rec_title) if rec_title else "대표작"
            body.append("> [!INFO] 📊 **시장 거래 지표 (Market Analytics)**")
            body.append(f"> - 🏆 **역대 최고 낙찰가**: **{format_usd(rec_usd)}** — {rec_art_link} ({rec_house or '경매사'}, {rec_date or '기록'})")
            if turnover > 0:
                body.append(f"> - 📈 **누적 경매 거래액**: **{format_usd(turnover)}** | 🎯 **낙찰률**: **{sold_rate:.1f}%** ({sold_cnt:,}/{a_cnt:,}건)")
            body.append("")
        elif a_cnt > 0:
            body.append(f"> 📜 **경매 기록**: 총 **{a_cnt:,}건** (Getty 판매 아카이브 1675~1944 + Bonhams 2003~ 등. 데이터 범위 밖 시기는 공백이며 시장 지표로 해석하지 말 것)\n")

        if bio:
            body.append(f"### ℹ️ 작가 개요\n{bio.strip()}\n")

        exhs = artist_to_exhibitions.get(a_id, [])
        if exhs:
            body.append(f"## 🗓️ 전시 이력 (최근 {len(exhs)}건)")
            body.append("| 전시명 | 기간 | 장소 |")
            body.append("|---|---|---|")
            for title, sd, ed, venue, url in exhs:
                period = f"{sd or ''} ~ {ed or ''}".strip(" ~") or "-"
                body.append(f"| {truncate_cell(title, 50)} | {period} | {truncate_cell(venue or '-', 30)} |")
            body.append("")
        awards = artist_to_awards.get(a_id, [])
        if awards:
            body.append(f"## 🏅 수상 ({len(awards)}건)")
            for d, detail in awards:
                body.append(f"- {d.year if d else '연도 미상'}: {escape_cell(detail)}")
            body.append("")

        galleries = artist_to_galleries.get(a_id, [])
        if galleries:
            body.append("## 🏢 전속 및 취급 갤러리")
            for g_id, g_name in galleries:
                body.append(f"- {gallery_link(g_id, g_name)}")
            body.append("")

        m_stats = artist_to_museum_stats.get(a_id, {})
        if m_stats:
            body.append("## 🏛️ 주요 소장 미술관")
            sorted_m_stats = sorted(m_stats.items(), key=lambda x: x[1], reverse=True)[:15]
            for (m_id, m_name), count in sorted_m_stats:
                body.append(f"- {museum_link(m_id, m_name)}: **{count:,}점**")
            body.append("")

        works = artist_to_works.get(a_id, [])
        if works:
            body.append(f"## 🎨 대표 소장 작품 (주요 {len(works)}선)")
            body.append("| 작품명 | 제작연도 | 매체 | 소장처 |")
            body.append("|---|---|---|---|")
            for aw_id, title, yr, med, m_id, m_name in works:
                t_cell = artwork_link(aw_id, title, max_len=40)
                y_cell = escape_cell(yr or "-")
                med_cell = truncate_cell(med or "-", 25)
                m_cell = museum_link(m_id, m_name)
                body.append(f"| {t_cell} | {y_cell} | {med_cell} | {m_cell} |")
            body.append("")

        auctions = artist_to_auctions.get(a_id, [])
        if auctions:
            body.append(f"## 🔨 주요 경매 낙찰 이력 (상위 {len(auctions)}건)")
            body.append("| 작품명 | 경매사 | 경매일자 | 낙찰가 (USD / 원통화) | 상태 |")
            body.append("|---|---|---|---|---|")
            for ah_id, ah_name, a_date, hammer, curr, sold, aw_id, aw_title, p_usd in auctions:
                title_cell = artwork_link(aw_id, aw_title, max_len=40)
                h_cell = house_link(ah_id, ah_name)
                d_cell = escape_cell(a_date or "-")
                price_str = format_price_with_curr(hammer, curr, p_usd)

                if hammer is not None and hammer > 0:
                    s_cell = "낙찰" if (sold is True or sold is None) else "유찰"
                else:
                    s_cell = "출품 (가격 미상)"
                body.append(f"| {title_cell} | {h_cell} | {d_cell} | {price_str} | {s_cell} |")
            body.append("")

        write_md(VAULT_DIR / "artists" / f"{slug}.md", fm + "\n".join(body))

    print(f"  -> 작가 마크다운 {len(selected_artists)}개 생성 완료")

    # -------------------------------------------------------------
    # 4. Export Museums
    # -------------------------------------------------------------
    print("\n[4/7] 미술관(Museums) 마크다운 생성 중...")

    cur.execute("""
        SELECT mh.museum_id, a.artist_id, ar.name, count(a.id) as cnt
        FROM museum_holdings mh
        JOIN artworks a ON a.id = mh.artwork_id
        JOIN artists ar ON ar.id = a.artist_id
        WHERE mh.museum_id = ANY(%s::uuid[])
        GROUP BY mh.museum_id, a.artist_id, ar.name
        ORDER BY cnt DESC
    """, (selected_museum_ids,))
    museum_top_artists = defaultdict(list)
    for m_id, a_id, a_name, cnt in cur.fetchall():
        m_id_str = str(m_id)
        if len(museum_top_artists[m_id_str]) < 30:
            museum_top_artists[m_id_str].append((str(a_id), a_name, cnt))

    cur.execute("""
        SELECT mh.museum_id, a.id, a.title, a.year_created, a.medium, a.artist_id, ar.name
        FROM museum_holdings mh
        JOIN artworks a ON a.id = mh.artwork_id
        LEFT JOIN artists ar ON ar.id = a.artist_id
        WHERE mh.museum_id = ANY(%s::uuid[])
          AND a.title IS NOT NULL
          AND length(trim(a.title)) >= 3
          AND a.title NOT ILIKE '%%(제목 없음)%%'
          AND a.title NOT ILIKE '%%untitled%%'
        ORDER BY a.year_created NULLS LAST
    """, (selected_museum_ids,))
    museum_works = defaultdict(list)
    for m_id, aw_id, title, yr, med, a_id, a_name in cur.fetchall():
        m_id_str = str(m_id)
        if len(museum_works[m_id_str]) < MAX_MUSEUM_HIGHLIGHTS:
            museum_works[m_id_str].append((str(aw_id), title, yr, med, str(a_id) if a_id else None, a_name))

    for r in museum_rows:
        m_id = str(r[0])
        name = r[1]
        name_en = r[2]
        country = r[3]
        city = r[4]
        cat = r[5]
        website = r[6]
        h_cnt = r[7]
        slug = museum_slugs[m_id]

        aliases = [name]
        if name_en:
            aliases.append(name_en)

        fm = build_frontmatter(
            aliases=aliases,
            type="museum",
            name=name,
            name_en=name_en,
            country=country,
            city=city,
            category=cat,
            holdings_count=h_cnt,
            website=website,
        )

        body = [f"# {name}\n"]

        badges = []
        loc = ", ".join([p for p in [city, country] if p])
        if loc:
            badges.append(f"**위치**: {loc}")
        if h_cnt > 0:
            badges.append(f"**소장품 수**: {h_cnt:,}점")
        if cat:
            badges.append(f"**유형**: {cat}")
        if website:
            badges.append(f"**공식 웹사이트**: [{website}]({website})")
        if badges:
            body.append("> " + " | ".join(badges) + "\n")

        top_artists = museum_top_artists.get(m_id, [])
        if top_artists:
            body.append("## 🎨 대표 소장 작가 (TOP 30)")
            body.append("| 작가명 | 소장 작품 수 |")
            body.append("|---|---|")
            for a_id, a_name, cnt in top_artists:
                body.append(f"| {artist_link(a_id, a_name)} | **{cnt:,}점** |")
            body.append("")

        works = museum_works.get(m_id, [])
        if works:
            body.append(f"## 🏛️ 컬렉션 대표 명작 (주요 {len(works)}선)")
            body.append("| 작품명 | 작가 | 제작연도 | 매체 |")
            body.append("|---|---|---|---|")
            for aw_id, title, yr, med, a_id, a_name in works:
                t_cell = artwork_link(aw_id, title, max_len=40)
                a_cell = artist_link(a_id, a_name)
                y_cell = escape_cell(yr or "-")
                med_cell = truncate_cell(med or "-", 25)
                body.append(f"| {t_cell} | {a_cell} | {y_cell} | {med_cell} |")
            body.append("")

        write_md(VAULT_DIR / "museums" / f"{slug}.md", fm + "\n".join(body))

    print(f"  -> 미술관 마크다운 {len(museum_rows)}개 생성 완료")

    # -------------------------------------------------------------
    # 5. Export Galleries
    # -------------------------------------------------------------
    print("\n[5/7] 갤러리(Galleries) 마크다운 생성 중...")

    cur.execute("""
        SELECT gr.gallery_id, a.id, a.name, a.nationality, a.birth_year, a.death_year
        FROM gallery_representations gr
        JOIN artists a ON a.id = gr.artist_id
        WHERE gr.gallery_id = ANY(%s::uuid[])
        ORDER BY a.name
    """, (selected_gallery_ids,))
    gallery_artists = defaultdict(list)
    for g_id, a_id, a_name, nat, b_yr, d_yr in cur.fetchall():
        g_id_str = str(g_id)
        if len(gallery_artists[g_id_str]) < MAX_GALLERY_ARTISTS:
            gallery_artists[g_id_str].append((str(a_id), a_name, nat, b_yr, d_yr))

    for r in gallery_rows:
        g_id = str(r[0])
        name = r[1]
        city = r[2]
        country = r[3]
        website = r[4]
        rep_cnt = r[5]
        slug = gallery_slugs[g_id]

        aliases = [name]

        fm = build_frontmatter(
            aliases=aliases,
            type="gallery",
            name=name,
            city=city,
            country=country,
            artists_count=rep_cnt,
            website=website,
        )

        body = [f"# {name}\n"]

        badges = []
        loc = ", ".join([p for p in [city, country] if p])
        if loc:
            badges.append(f"**위치**: {loc}")
        if rep_cnt > 0:
            badges.append(f"**전속/취급 작가**: {rep_cnt}명")
        if website:
            badges.append(f"**공식 웹사이트**: [{website}]({website})")
        if badges:
            body.append("> " + " | ".join(badges) + "\n")

        artists = gallery_artists.get(g_id, [])
        if artists:
            body.append(f"## 🎨 전속 및 취급 작가 명단 (총 {len(artists)}명)")
            body.append("| 작가명 | 국적 | 활동시기 |")
            body.append("|---|---|---|")
            for a_id, a_name, nat, b_yr, d_yr in artists:
                a_cell = artist_link(a_id, a_name)
                nat_cell = escape_cell(nat or "-")
                period = f"{b_yr or ''} ~ {d_yr or ''}".strip(" ~") or "-"
                body.append(f"| {a_cell} | {nat_cell} | {period} |")
            body.append("")

        write_md(VAULT_DIR / "galleries" / f"{slug}.md", fm + "\n".join(body))

    print(f"  -> 갤러리 마크다운 {len(gallery_rows)}개 생성 완료")

    # -------------------------------------------------------------
    # 6. Export Auction Houses
    # -------------------------------------------------------------
    print("\n[6/7] 경매사(Auction Houses) 마크다운 생성 중...")

    cur.execute("""
        SELECT au.auction_house_id, al.id, a.id, a.title, ar.id, ar.name, au.auction_date,
               al.hammer_price, al.currency, al.sold, al.price_usd
        FROM auction_lots al
        JOIN auctions au ON au.id = al.auction_id
        JOIN artworks a ON a.id = al.artwork_id
        LEFT JOIN artists ar ON ar.id = a.artist_id
        WHERE au.auction_house_id = ANY(%s::uuid[])
        ORDER BY al.price_usd DESC NULLS LAST
    """, (selected_house_ids,))
    house_lots = defaultdict(list)
    for h_id, lot_id, aw_id, aw_title, a_id, a_name, a_date, hammer, curr, sold, p_usd in cur.fetchall():
        h_id_str = str(h_id)
        if len(house_lots[h_id_str]) < MAX_AUCTION_LOTS:
            house_lots[h_id_str].append((str(aw_id), aw_title, str(a_id) if a_id else None, a_name, a_date, hammer, curr, sold, p_usd))

    for r in house_rows:
        h_id = str(r[0])
        name = r[1]
        country = r[2]
        au_cnt = r[3]
        lot_cnt = r[4]
        vol_usd = float(r[5] or 0)
        slug = house_slugs[h_id]

        aliases = [name]

        fm = build_frontmatter(
            aliases=aliases,
            type="auction_house",
            name=name,
            country=country,
            auctions_count=au_cnt,
            lots_count=lot_cnt,
            total_turnover_usd=vol_usd if vol_usd > 0 else None,
        )

        body = [f"# {name}\n"]

        badges = []
        if country:
            badges.append(f"**국가**: {country}")
        if au_cnt > 0:
            badges.append(f"**개최 경매**: {au_cnt:,}회")
        if lot_cnt > 0:
            badges.append(f"**출품 Lot**: {lot_cnt:,}건")
        if vol_usd >= 10000:
            badges.append(f"**누적 거래액**: {format_usd(vol_usd)}")
        if badges:
            body.append("> " + " | ".join(badges) + "\n")

        lots = house_lots.get(h_id, [])
        if lots:
            body.append(f"## 🏆 주요 출품 및 낙찰 기록 (상위 {len(lots)}건)")
            body.append("| 작품명 | 작가 | 경매일자 | 낙찰가 (USD / 원통화) | 상태 |")
            body.append("|---|---|---|---|---|")
            for aw_id, aw_title, a_id, a_name, a_date, hammer, curr, sold, p_usd in lots:
                t_cell = artwork_link(aw_id, aw_title, max_len=40)
                a_cell = artist_link(a_id, a_name)
                d_cell = escape_cell(a_date or "-")
                price_str = format_price_with_curr(hammer, curr, p_usd)

                if hammer is not None and hammer > 0:
                    s_cell = "낙찰" if (sold is True or sold is None) else "유찰"
                else:
                    s_cell = "출품 (가격 미상)"
                body.append(f"| {t_cell} | {a_cell} | {d_cell} | {price_str} | {s_cell} |")
            body.append("")

        write_md(VAULT_DIR / "auction_houses" / f"{slug}.md", fm + "\n".join(body))

    print(f"  -> 경매사 마크다운 {len(house_rows)}개 생성 완료")

    # -------------------------------------------------------------
    # 7. Export Collectors & Dashboard
    # -------------------------------------------------------------
    print("\n[7/7] 컬렉터(Collectors) 및 종합 대시보드 마크다운 생성 중...")

    cur.execute("""
        SELECT pr.owner_collector_id, a.id, a.title, ar.id, ar.name, pr.acquired_date, pr.disposed_date,
               pr.acquired_method, mh.museum_id, m.name
        FROM provenance_records pr
        JOIN artworks a ON a.id = pr.artwork_id
        LEFT JOIN artists ar ON ar.id = a.artist_id
        LEFT JOIN museum_holdings mh ON mh.artwork_id = a.id
        LEFT JOIN museums m ON m.id = mh.museum_id
        WHERE pr.owner_collector_id = ANY(%s::uuid[])
        ORDER BY pr.acquired_date NULLS LAST
    """, (selected_collector_ids,))
    collector_prov = defaultdict(list)
    for c_id, aw_id, aw_title, a_id, a_name, p_s, p_e, meth, m_id, m_name in cur.fetchall():
        c_id_str = str(c_id)
        if len(collector_prov[c_id_str]) < MAX_COLLECTOR_PROV:
            collector_prov[c_id_str].append((str(aw_id), aw_title, str(a_id) if a_id else None, a_name, p_s, p_e, meth, str(m_id) if m_id else None, m_name))

    for r in collector_rows:
        c_id = str(r[0])
        name = r[1]
        bio = r[2]
        is_inst = r[3]
        prov_cnt = r[4]
        slug = collector_slugs[c_id]

        aliases = [name]

        fm = build_frontmatter(
            aliases=aliases,
            type="collector",
            name=name,
            is_institution=bool(is_inst),
            provenance_count=prov_cnt,
        )

        body = [f"# {name}\n"]

        badges = [
            f"**구분**: {'기관 컬렉터' if is_inst else '개인 컬렉터'}",
            f"**확인된 소장 이력**: {prov_cnt:,}건",
        ]
        body.append("> " + " | ".join(badges) + "\n")

        if bio:
            body.append(f"### ℹ️ 컬렉터 소개\n{bio.strip()}\n")

        provs = collector_prov.get(c_id, [])
        if provs:
            body.append(f"## 📜 주요 소장 및 이전 작품 이력 (상위 {len(provs)}선)")
            body.append("| 작품명 | 작가 | 소장시기 | 취득/이전방식 | 현재 소장처 |")
            body.append("|---|---|---|---|---|")
            for aw_id, aw_title, a_id, a_name, p_s, p_e, meth, m_id, m_name in provs:
                t_cell = artwork_link(aw_id, aw_title, max_len=40)
                a_cell = artist_link(a_id, a_name)
                period = f"{p_s or ''} ~ {p_e or ''}".strip(" ~") or "-"
                meth_cell = truncate_cell(meth or "-", 25)
                m_cell = museum_link(m_id, m_name)
                body.append(f"| {t_cell} | {a_cell} | {period} | {meth_cell} | {m_cell} |")
            body.append("")

        write_md(VAULT_DIR / "collectors" / f"{slug}.md", fm + "\n".join(body))

    print(f"  -> 컬렉터 마크다운 {len(collector_rows)}개 생성 완료")

    # -------------------------------------------------------------
    # Build Comprehensive Dashboard
    # -------------------------------------------------------------
    print("\n[최종] '00 대시보드.md' 작성 중...")

    # Fetch Top 20 All-time Auction Records (modern verified high records)
    cur.execute("""
        SELECT a.id, a.title, ar.id, ar.name, al.price_usd, al.hammer_price, al.currency,
               ah.id, ah.name, au.auction_date
        FROM auction_lots al
        JOIN artworks a ON a.id = al.artwork_id
        JOIN auctions au ON au.id = al.auction_id
        JOIN auction_houses ah ON ah.id = au.auction_house_id
        LEFT JOIN artists ar ON ar.id = a.artist_id
        WHERE al.price_usd IS NOT NULL AND al.price_usd > 1000000
          AND (al.sold = TRUE OR al.sold IS NULL)
          AND a.title IS NOT NULL
          AND a.title !~ '^Q[0-9]{6,}$'
        ORDER BY al.price_usd DESC
        LIMIT 20;
    """)
    top_20_auctions = cur.fetchall()

    dash_fm = build_frontmatter(
        type="dashboard",
        title="Artrend Curated Art Graph Dashboard (V4 Visual & Bio Enhanced)",
        curated_artists_count=len(selected_artists),
        curated_artworks_count=len(selected_artwork_rows),
        curated_museums_count=len(museum_rows),
        curated_galleries_count=len(gallery_rows),
        curated_auction_houses_count=len(house_rows),
        curated_collectors_count=len(collector_rows),
        updated_at="2026-09-16",
    )

    dash_body = [
        "# 🎨 Artrend 큐레이티드 아트 그래프 (Curated Vault V4)\n",
        "> 소장·경매·갤러리·전시 관계 데이터 중 **여러 축에 걸쳐 실제 연결 기록이 있는** 작가·작품·미술관·갤러리·경매사·컬렉터를 추린 볼트다. 출처가 없는 정보는 넣지 않는다.\n",
        "> [!NOTE] **데이터 범위와 한계 (2026-09-16 기준)**",
        "> 1. **작가 선별 기준**: 소장(미술관 Open Access)·경매(Getty 판매 아카이브 1675~1944, Bonhams 2003~ 등)·갤러리 로스터·전시(2016~, 국내 기관·Wikidata·갤러리 페이지) 중 2개 축 이상에 기록이 있거나 단일 축 기록이 충분한 작가. 정본 ID(Getty ULAN / Wikidata QID)가 있으면 표기.",
        "> 2. **약력**: 원본 소스(미술관·Wikidata)의 약력만 싣는다. 별도 생성 약력은 `artist_bio_generated`에 격리돼 있고 여기 포함하지 않는다.",
        "> 3. **가격**: USD 환산은 1970년 이후 ISO 통화 로트에만 있다. 18~19세기 livres/guilders 등 역사 통화는 환산하지 않으며, 1850~1999년 경매는 소스 공백이라 '시장 지표'로 읽으면 안 된다.\n",
        "---",
        "## 📊 큐레이션 지식 그래프 데이터 현황",
        "| 분류 | 큐레이션 수량 | 설명 | 저장 폴더 |",
        "|:---|:---:|:---|:---|",
        f"| 🎨 **작가 (Artists)** | **{len(selected_artists):,}명** | 2개 축 이상 관계 기록 보유 작가(스코어 상위) | `artists/` |",
        f"| 🖼️ **대표 명작 (Artworks)** | **{len(selected_artwork_rows):,}점** | USD 환산 가능한 고가 낙찰작 + 선별 미술관·작가의 소장작 | `artworks/` |",
        f"| 🏛️ **미술관 (Museums)** | **{len(museum_rows):,}곳** | 소장 기록 수 상위 미술관 | `museums/` |",
        f"| 🏢 **갤러리 (Galleries)** | **{len(gallery_rows):,}곳** | 로스터(작가 명부) 수집 갤러리 | `galleries/` |",
        f"| 🔨 **경매사 (Auction Houses)** | **{len(house_rows):,}곳** | 로트 수 상위 경매사(국내 경매사는 미수집) | `auction_houses/` |",
        f"| 📜 **컬렉터 (Collectors)** | **{len(collector_rows):,}명** | 프로버넌스 기록 수 상위 컬렉터 | `collectors/` |",
        f"| **합계** | **{total_curated_entities:,}개** | **관계 기록이 있는 항목만** | `vault_curated/` |",
        "",
        "---",
        "## 🏆 USD 환산 낙찰가 상위 20 (1970년 이후 ISO 통화 로트만)",
        "| 순위 | 작품명 | 작가 | 낙찰가 (USD) | 원통화 낙찰가 | 경매사 | 낙찰일자 |",
        "|:---:|:---|:---|:---:|:---:|:---|:---:|",
    ]

    for idx, (aw_id, title, a_id, a_name, p_usd, hammer, curr, ah_id, ah_name, s_date) in enumerate(top_20_auctions, 1):
        t_cell = artwork_link(str(aw_id), title, max_len=45)
        a_cell = artist_link(str(a_id) if a_id else None, a_name)
        p_cell = format_usd(p_usd)
        h_orig = f"{int(round(hammer)):,} {curr or 'USD'}" if hammer else "-"
        house_cell = house_link(str(ah_id) if ah_id else None, ah_name)
        d_cell = str(s_date) if s_date else "-"
        dash_body.append(f"| {idx} | {t_cell} | {a_cell} | **{p_cell}** | {h_orig} | {house_cell} | {d_cell} |")

    dash_body.extend([
        "",
        "---",
        "## 🌟 관계 스코어 상위 작가 TOP 20",
        "| 순위 | 작가명 | 국적 | 활동시기 | 소장품 | 경매기록 | 역대 최고가 |",
        "|:---:|:---|:---|:---:|:---:|:---:|:---:|",
    ])

    for idx, (r, h_cnt, r_cnt, a_cnt, score, m_info) in enumerate(selected_artists[:20], 1):
        a_id = str(r[0])
        name = r[1]
        nat = r[5] or "-"
        b_yr = r[3]
        d_yr = r[4]
        period = f"{b_yr or ''} ~ {d_yr or ''}".strip(" ~") or "-"
        rec_usd = m_info.get("record_usd", 0)
        rec_str = format_usd(rec_usd) if rec_usd >= 10000 else "-"
        a_cell = f"[[{artist_slugs[a_id]}\\|{name}]]"
        dash_body.append(f"| {idx} | {a_cell} | {nat} | {period} | {h_cnt:,}점 | {a_cnt:,}건 | {rec_str} |")

    dash_body.extend([
        "",
        "---",
        "## 🏛️ 소장 기록 상위 미술관 15",
        "| 순위 | 미술관명 | 국가 / 도시 | 소장 작품 수 |",
        "|:---:|:---|:---|:---:|",
    ])

    for idx, r in enumerate(museum_rows[:15], 1):
        m_id = str(r[0])
        name = r[1]
        loc = ", ".join([p for p in [r[4], r[3]] if p]) or "-"
        h_cnt = r[7]
        m_cell = f"[[{museum_slugs[m_id]}\\|{name}]]"
        dash_body.append(f"| {idx} | {m_cell} | {loc} | **{h_cnt:,}점** |")

    dash_body.extend([
        "",
        "---",
        "## 💡 옵시디언 활용 팁",
        "1. **그래프 뷰(Graph View)**: `Ctrl + G`를 누르면 작가-명작-미술관-경매사-컬렉터가 촘촘히 엮인 거대한 은하수 지식 그래프를 감상할 수 있습니다.",
        "2. **자동 링크 (Aliases)**: 한글명/영문명 별칭이 완벽 등록되어 있어 새 노트를 작성할 때 `[[이우환]]` 또는 `[[MMCA]]`만 입력해도 자동 연결됩니다.",
        "3. **전체 266만 건 정밀 탐색**: 마크다운에 다 담기지 않은 266만 건의 세부 데이터는 `python pipeline/artgraph_chat.py --interactive`를 통해 언제든 자연어로 질문하세요.",
    ])

    write_md(VAULT_DIR / "00 대시보드.md", dash_fm + "\n".join(dash_body))
    print("  -> 대시보드 작성 완료!")

    elapsed = time.time() - start_time
    print(f"\n==================================================")
    print(f"  Curated Vault V3 빌드 완료! (총 {total_curated_entities:,}개 파일, 소요시간: {elapsed:.2f}초)")
    print(f"==================================================")
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
