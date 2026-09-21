"""갤러리 5곳(Gladstone/Lehmann Maupin/Taka Ishii/Pyo/Simon) 전시 페이지 raw -> exhibitions/
exhibition_artists 적재. 2026-09-17 SPA갤러리_엔드포인트_20260917.md 조사 + 메인 승인 후속.

사이트별 데이터 품질이 크게 달라 소스별로 파서를 분리한다:
- gladstone: Gatsby page-data.json — title/artists(정식 이름 리스트)/startDate/endDate 전부 구조화.
- lehmannmaupin: 목록 페이지 JSON-LD(ItemList) — 현재 진행 전시 소수(4건)만, 날짜 없음. 작가는
  URL 슬러그 접두어가 로스터 작가 이름과 일치할 때만 best-effort로 추정.
  주의: JSON-LD 파싱은 정규식 대신 "CollectionPage" 위치를 기준으로 앞뒤 <script> 태그를 찾아
  파이썬 json.loads로 처리한다 — 중첩 `.*?` 정규식은 이 파일 크기(약 15만자)에서 catastrophic
  backtracking으로 멈춰버림(직접 겪음, 2026-09-17).
- takaishii: 워드프레스 SSR 텍스트 — "{작가명} “{제목}” Dates: {기간} Location: {장소}" 또는
  제목 없이 "{작가명} Dates: ... Location: ..." 두 패턴 혼재. 정규식으로 순차 파싱.
- pyo, simon: Wix 개별 페이지 title/meta만 저장돼 있음. **실측 결과 두 사이트의 실제 구조가
  당초 예상보다 빈약함** — Pyo는 title이 "{작가명} | PYO GALLERY"(전시명·날짜 없음)뿐이고
  meta description은 전수 비어 있음(214건 중 0건). Simon만 title에 "{전시명},{작가1, 작가2...}"
  + description에 날짜 범위가 실제로 채워져 있음. Pyo는 작가명만으로 전시 레코드를 만들고
  (제목=작가명, 날짜 없음), Simon은 제목/작가/날짜 전부 채운다.

작가 연결은 전부 **기존 artists 행과 이름 정확일치(대소문자 무시)만** — 신규 생성·수정 없음.
갤러리 연결은 galleries.name의 괄호 병기("한글이름 (English Name)") 영문 부분과 정확일치.
매칭 실패 시 exhibition_artists 링크만 생략(기존 R2 관례, exhibitions 레코드 자체는 유지).

사용법:
    python pipeline/gallery_exhibitions_pages_load.py            # 리포트만
    python pipeline/gallery_exhibitions_pages_load.py --apply    # 실제 반영
    python pipeline/gallery_exhibitions_pages_load.py --site gladstone   # 사이트 하나만
"""
from __future__ import annotations

import argparse
import glob
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import get_connection  # noqa: E402

RAW_ROOT = Path(__file__).resolve().parent.parent / "crawlers" / "raw"
LICENSE_NOTE = "갤러리 공식 전시 페이지, robots.txt 확인(2026-09-17)"

MONTHS = {m: i + 1 for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"])}
MONTHS.update({m[:3]: v for m, v in list(MONTHS.items())})


def _parse_month_range(text: str) -> tuple[str | None, str | None]:
    """'September 3 - October 15, 2026' / 'May 16 – Jun 20, 2026' 등을 (start,end)로."""
    if not text:
        return None, None
    text = text.replace("–", "-").replace("—", "-")
    m = re.search(
        r"([A-Za-z]+)\.?\s+(\d{1,2})(?:,\s*(\d{4}))?\s*-\s*(?:([A-Za-z]+)\.?\s+)?(\d{1,2}),?\s*(\d{4})",
        text,
    )
    if not m:
        return None, None
    mon1, d1, y1, mon2, d2, y2 = m.groups()
    mon2 = mon2 or mon1
    y1 = y1 or y2
    mo1 = MONTHS.get(mon1[:3].title())
    mo2 = MONTHS.get(mon2[:3].title())
    if not mo1 or not mo2 or not y1 or not y2:
        return None, None
    start = f"{y1}-{mo1:02d}-{int(d1):02d}"
    end = f"{y2}-{mo2:02d}-{int(d2):02d}"
    return start, end


def load_lookup(cur):
    cur.execute("select id::text, lower(name) from artists where entity_kind = 'person'")
    artists_by_name = {}
    for aid, name in cur.fetchall():
        artists_by_name.setdefault(name, aid)
    cur.execute("select id::text, name_en, lower(name) from artists where entity_kind='person' and name_en is not null")
    for aid, name_en, _ in cur.fetchall():
        artists_by_name.setdefault(name_en.lower(), aid)

    cur.execute("select id::text, name from galleries")
    galleries_by_en = {}
    galleries_by_name = {}
    paren_re = re.compile(r"\(([^)]+)\)\s*$")
    for gid, name in cur.fetchall():
        galleries_by_name[name.lower()] = gid
        m = paren_re.search(name)
        if m:
            galleries_by_en[m.group(1).strip().lower()] = gid
    return artists_by_name, galleries_by_en, galleries_by_name


def match_artist(name: str, artists_by_name: dict) -> str | None:
    return artists_by_name.get(name.strip().lower())


def match_gallery(label: str, galleries_by_en: dict, galleries_by_name: dict) -> str | None:
    label = label.strip().lower()
    return galleries_by_en.get(label) or galleries_by_name.get(label)


# ---------- 사이트별 파서: 각각 exhibitions 후보 list[dict] 반환 ----------
# dict keys: title, artist_names(list[str]), start_date, end_date, url, gallery_label

def parse_gladstone() -> list[dict]:
    fp = RAW_ROOT / "gladstone_exhibitions" / "page-data.json"
    if not fp.exists():
        return []
    data = json.loads(fp.read_text(encoding="utf-8"))
    nodes = data["result"]["data"]["allContentfulExhibition"]["nodes"]
    out = []
    for n in nodes:
        title = (n.get("title") or "").strip()
        if not title or n.get("slug") == "placeholder-does-not-show-on-site-do-not-delete":
            continue
        out.append({
            "title": title[:500],
            "artist_names": [a["name"] for a in (n.get("artists") or []) if a.get("name")],
            "start_date": n.get("startDate"),
            "end_date": n.get("endDate"),
            "url": f"https://www.gladstonegallery.com/exhibitions/{n.get('slug', '')}",
            "gallery_label": "Gladstone Gallery",
        })
    return out


def parse_lehmannmaupin(artists_by_name: dict) -> list[dict]:
    fp = RAW_ROOT / "lehmannmaupin_exhibitions" / "exhibitions-list.html"
    if not fp.exists():
        return []
    html_text = fp.read_text(encoding="utf-8")
    idx = html_text.find("CollectionPage")
    if idx < 0:
        return []
    start = html_text.rfind("<script", 0, idx)
    end = html_text.find("</script>", idx)
    blob = html_text[html_text.find(">", start) + 1:end]
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        return []
    items = data.get("@graph", [{}])[0].get("mainEntity", {}).get("itemListElement", [])
    out = []
    for it in items:
        title = it.get("name") or ""
        url = it.get("url") or ""
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        # 슬러그 접두어가 로스터 작가 이름과 일치하면 추정(하이픈->공백 정규화, 최선 매칭)
        guess_names = []
        norm_slug = slug.replace("-", " ")
        for name_lower in artists_by_name:
            if len(name_lower) < 6:
                continue
            if norm_slug == name_lower or norm_slug.startswith(name_lower + " "):
                guess_names.append(name_lower)
        out.append({
            "title": title[:500] if title and title != "Untitled exhibition" else slug.replace("-", " ")[:500],
            "artist_names": guess_names,
            "start_date": None,
            "end_date": None,
            "url": url,
            "gallery_label": "Lehmann Maupin",
        })
    return out


TAKAISHII_ENTRY_RE = re.compile(
    r'(?P<pre>[A-Z][^"“”]{0,80}?)\s*(?:[“"](?P<title>[^"”]{1,200})[”"])?\s*Dates:\s*(?P<dates>[^L]{5,60}?)\s*Location:\s*(?P<location>[^A-Z]{0,40}(?:Taka Ishii Gallery[^O0-9]{0,30})?)',
)


def parse_takaishii() -> list[dict]:
    out = []
    for fp in sorted((RAW_ROOT / "takaishii_exhibitions").glob("page-*.html")):
        html_text = fp.read_text(encoding="utf-8")
        text = re.sub(r"<[^>]+>", " ", html_text)
        text = re.sub(r"&#8220;|&#8221;", '"', text)
        text = re.sub(r"&amp;", "&", text)
        text = re.sub(r"\s+", " ", text)
        for m in TAKAISHII_ENTRY_RE.finditer(text):
            pre = m.group("pre").strip(" *")
            title = m.group("title")
            dates = m.group("dates").strip()
            location = m.group("location").strip()
            if not pre or len(pre) > 60 or len(pre.split()) > 6:
                continue
            if any(bad in pre for bad in ("apologize", "reception", "inconvenience", "caused", ":")):
                continue
            start, end = _parse_month_range(dates)
            out.append({
                "title": (title or pre)[:500],
                "artist_names": [pre] if title else [],
                "start_date": start,
                "end_date": end,
                "url": "https://www.takaishiigallery.com/en/exhibitions/",
                "gallery_label": "Taka Ishii Gallery",
                "venue_name": location or None,
            })
    return out


def parse_pyo() -> list[dict]:
    out = []
    for fp in (RAW_ROOT / "pyo_exhibitions").glob("*.json"):
        d = json.loads(fp.read_text(encoding="utf-8"))
        title = d.get("title")
        if not title:
            continue
        title = re.sub(r"\s*\|\s*PYO GALLERY\s*$", "", title, flags=re.I).strip()
        if not title:
            continue
        out.append({
            "title": title[:500],
            "artist_names": [title],  # Pyo는 제목=작가명인 경우가 대부분(구조상 구분 불가)
            "start_date": None,
            "end_date": None,
            "url": d.get("url"),
            "gallery_label": "Pyo Gallery",
        })
    return out


def parse_simon() -> list[dict]:
    out = []
    for fp in (RAW_ROOT / "simon_exhibitions").glob("*.json"):
        d = json.loads(fp.read_text(encoding="utf-8"))
        title_raw = d.get("title")
        if not title_raw:
            continue
        parts = title_raw.split(",")
        title = parts[0].strip()
        artist_names = [p.strip() for p in parts[1:] if p.strip()]
        start, end = _parse_month_range(d.get("description") or "")
        out.append({
            "title": title[:500] or title_raw[:500],
            "artist_names": artist_names,
            "start_date": start,
            "end_date": end,
            "url": d.get("url"),
            "gallery_label": "Gallery Simon",
        })
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--site", choices=["all", "gladstone", "lehmannmaupin", "takaishii", "pyo", "simon"], default="all")
    args = ap.parse_args()

    conn = get_connection()
    cur = conn.cursor()
    artists_by_name, galleries_by_en, galleries_by_name = load_lookup(cur)

    candidates: list[dict] = []
    sites = ["gladstone", "lehmannmaupin", "takaishii", "pyo", "simon"] if args.site == "all" else [args.site]
    per_site_counts = Counter()
    if "gladstone" in sites:
        rows = parse_gladstone()
        candidates += rows
        per_site_counts["gladstone"] = len(rows)
    if "lehmannmaupin" in sites:
        rows = parse_lehmannmaupin(artists_by_name)
        candidates += rows
        per_site_counts["lehmannmaupin"] = len(rows)
    if "takaishii" in sites:
        rows = parse_takaishii()
        candidates += rows
        per_site_counts["takaishii"] = len(rows)
    if "pyo" in sites:
        rows = parse_pyo()
        candidates += rows
        per_site_counts["pyo"] = len(rows)
    if "simon" in sites:
        rows = parse_simon()
        candidates += rows
        per_site_counts["simon"] = len(rows)

    matched_artist_total = 0
    unmatched_artist_names = Counter()
    for c in candidates:
        gid = match_gallery(c["gallery_label"], galleries_by_en, galleries_by_name)
        c["gallery_id"] = gid
        aids = []
        for name in c["artist_names"]:
            aid = match_artist(name, artists_by_name)
            if aid:
                aids.append(aid)
            else:
                unmatched_artist_names[name] += 1
        c["artist_ids"] = list(dict.fromkeys(aids))
        matched_artist_total += len(c["artist_ids"])

    print(f"[gallery_exhibitions_pages_load] 사이트별 후보: {dict(per_site_counts)}")
    print(f"[gallery_exhibitions_pages_load] 전체 후보 {len(candidates)}건, 작가 매칭 {matched_artist_total}건, 미매칭 이름(상위 10): {unmatched_artist_names.most_common(10)}")

    if not args.apply:
        print("--apply 없음: 리포트만")
        return

    cur.execute(
        """insert into sources (url, site_name, fetched_at, raw_path, license_note)
           values (%s, %s, now(), %s, %s)
           on conflict (raw_path) do update set fetched_at = now() returning id""",
        ("https://www.gladstonegallery.com/exhibitions (+4곳)", "gallery_exhibitions_pages",
         "crawlers/raw/{gladstone,lehmannmaupin,takaishii,pyo,simon}_exhibitions/", LICENSE_NOTE),
    )
    source_id = cur.fetchone()[0]

    n = Counter()
    for c in candidates:
        if not c.get("title"):
            continue
        cur.execute(
            """insert into exhibitions (title, venue_kind, gallery_id, venue_name, start_date, end_date, url, source_id)
               values (%s,'gallery',%s,%s,%s,%s,%s,%s) on conflict do nothing returning id""",
            (c["title"], c.get("gallery_id"), c.get("venue_name"), c.get("start_date"), c.get("end_date"), c.get("url"), source_id),
        )
        row = cur.fetchone()
        if row:
            eid = row[0]
            n["exhibition"] += 1
        else:
            cur.execute(
                "select id from exhibitions where coalesce(url,'')=coalesce(%s,'') and title=%s limit 1",
                (c.get("url"), c["title"]),
            )
            r2 = cur.fetchone()
            if not r2:
                continue
            eid = r2[0]
        for aid in c["artist_ids"]:
            cur.execute("insert into exhibition_artists (exhibition_id, artist_id) values (%s,%s) on conflict do nothing", (eid, aid))
            n["exhibition_artist"] += cur.rowcount
    conn.commit()
    print("적용 완료:", dict(n))


if __name__ == "__main__":
    main()
