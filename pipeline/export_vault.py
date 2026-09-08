"""DB -> vault/ 마크다운 위키 내보내기 (옵시디언 볼트).

사용법:
    python export_vault.py --what museums,galleries,artists,artworks
    python export_vault.py --what artists --limit 100   # 테스트용

DATABASE_URL 환경변수가 필요하다 (pipeline/.env 참고).
artworks는 40만 건 규모라 서버사이드 커서로 스트리밍하며 파일 I/O가
병목이 되므로 --limit 없이 돌리면 오래 걸린다 — 백그라운드 실행 권장.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

import psycopg2

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(line_buffering=True)

VAULT_ROOT = Path(__file__).resolve().parent.parent / "vault"
MAX_LINKED_ARTWORKS = 200  # 작가 문서 하나에 나열할 작품 링크 상한 (다작 작가 대비)


def slugify(name: str, uid: str) -> str:
    name = (name or "무제").strip()
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    name = re.sub(r"\s+", " ", name).strip()
    name = name[:80]
    return f"{name} ({uid[:8]})"


def frontmatter(**fields) -> str:
    lines = ["---"]
    for key, value in fields.items():
        if value is None or value == "":
            continue
        value = str(value).replace('"', "'").replace("\n", " ")
        lines.append(f'{key}: "{value}"')
    lines.append("---\n")
    return "\n".join(lines)


def write_md(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def export_museums(cur) -> dict[str, str]:
    cur.execute("select id, name, name_en, country, city, type, website from museums")
    rows = cur.fetchall()
    id_to_slug: dict[str, str] = {}
    for id_, name, name_en, country, city, type_, website in rows:
        slug = slugify(name, id_)
        id_to_slug[id_] = slug
        fm = frontmatter(type="museum", name=name, name_en=name_en, country=country, city=city, category=type_, website=website)
        body = f"# {name}\n\n"
        if name_en:
            body += f"영문명: {name_en}\n\n"
        if city or country:
            body += f"위치: {city or ''} {country or ''}\n\n"
        write_md(VAULT_ROOT / "museums" / f"{slug}.md", fm + body)
    print(f"[vault:museums] {len(rows)}건 내보냄")
    return id_to_slug


def export_galleries(cur) -> dict[str, str]:
    cur.execute("select id, name, city, country, website from galleries")
    rows = cur.fetchall()
    id_to_slug: dict[str, str] = {}
    for id_, name, city, country, website in rows:
        slug = slugify(name, id_)
        id_to_slug[id_] = slug
        fm = frontmatter(type="gallery", name=name, country=country, city=city, website=website)
        body = f"# {name}\n\n"
        if city or country:
            body += f"위치: {city or ''} {country or ''}\n\n"
        write_md(VAULT_ROOT / "galleries" / f"{slug}.md", fm + body)
    print(f"[vault:galleries] {len(rows)}건 내보냄")
    return id_to_slug


def _escape_cell(value) -> str:
    """마크다운 테이블 셀 안에서 파이프/줄바꿈이 구조를 깨는 것 방지."""
    if value is None:
        return ""
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def load_artist_artworks(conn, museum_name: dict[str, str]) -> tuple[dict[str, list[tuple]], dict[str, int]]:
    """artist_id -> [(title, year_created, medium, museum_name), ...] (최대 MAX_LINKED_ARTWORKS개)
    + artist_id -> 전체 작품 수(캡 걸리기 전 실제 총계)."""
    cur = conn.cursor("artist_artworks_export_cursor")
    cur.execute(
        """
        select a.artist_id, a.title, a.year_created, a.medium, mh.museum_id
        from artworks a
        left join lateral (
            select museum_id from museum_holdings mh where mh.artwork_id = a.id limit 1
        ) mh on true
        where a.artist_id is not null
        order by a.artist_id
        """
    )
    by_artist: dict[str, list[tuple]] = {}
    counts: dict[str, int] = {}
    while True:
        batch = cur.fetchmany(5000)
        if not batch:
            break
        for artist_id, title, year_created, medium, museum_id in batch:
            counts[artist_id] = counts.get(artist_id, 0) + 1
            bucket = by_artist.setdefault(artist_id, [])
            if len(bucket) < MAX_LINKED_ARTWORKS:
                m_name = museum_name.get(museum_id) if museum_id else None
                bucket.append((title, year_created, medium, m_name))
    cur.close()
    return by_artist, counts


MAX_LINKED_AUCTIONS = 200  # 작가 문서 하나에 나열할 경매기록 상한


def load_artist_auctions(conn) -> tuple[dict[str, list[tuple]], dict[str, int]]:
    """artist_id -> [(auction_house, auction_date, hammer_price, currency, sold), ...]
    (최대 MAX_LINKED_AUCTIONS개) + artist_id -> 전체 경매기록 수.

    artworks.artist_id를 통해서만 연결(작품 단위 매칭은 포기, 자율운영기준.md
    3절 근거) — 미술관 소장작과 마찬가지로 작가 레벨 FK 연결만 신뢰."""
    cur = conn.cursor("artist_auctions_export_cursor")
    cur.execute(
        """
        select aw.artist_id, ah.name, au.auction_date, al.hammer_price, al.currency, al.sold
        from auction_lots al
        join artworks aw on aw.id = al.artwork_id
        join auctions au on au.id = al.auction_id
        join auction_houses ah on ah.id = au.auction_house_id
        where aw.artist_id is not null
        order by aw.artist_id
        """
    )
    by_artist: dict[str, list[tuple]] = {}
    counts: dict[str, int] = {}
    while True:
        batch = cur.fetchmany(5000)
        if not batch:
            break
        for artist_id, house, auction_date, hammer_price, currency, sold in batch:
            counts[artist_id] = counts.get(artist_id, 0) + 1
            bucket = by_artist.setdefault(artist_id, [])
            if len(bucket) < MAX_LINKED_AUCTIONS:
                bucket.append((house, auction_date, hammer_price, currency, sold))
    cur.close()
    return by_artist, counts


def export_artists(conn, cur, gallery_slug: dict[str, str], limit: int | None) -> dict[str, str]:
    q = "select id, name, name_en, birth_year, death_year, nationality, bio from artists order by name"
    if limit:
        q += f" limit {limit}"
    cur.execute(q)
    rows = cur.fetchall()

    rep_cur = conn.cursor()
    rep_cur.execute("select artist_id, gallery_id from gallery_representations")
    reps_by_artist: dict[str, list[str]] = {}
    for artist_id, gallery_id in rep_cur.fetchall():
        reps_by_artist.setdefault(artist_id, []).append(gallery_id)
    rep_cur.close()

    museum_cur = conn.cursor()
    museum_cur.execute("select id, name from museums")
    museum_name = {row[0]: row[1] for row in museum_cur.fetchall()}
    museum_cur.close()

    artworks_by_artist, artwork_counts = load_artist_artworks(conn, museum_name)
    print(f"[vault:artists] 작가별 작품 사전 로드 완료 ({len(artworks_by_artist)}명)")

    auctions_by_artist, auction_counts = load_artist_auctions(conn)
    print(f"[vault:artists] 작가별 경매기록 사전 로드 완료 ({len(auctions_by_artist)}명)")

    id_to_slug: dict[str, str] = {}
    for id_, name, name_en, birth_year, death_year, nationality, bio in rows:
        slug = slugify(name, id_)
        id_to_slug[id_] = slug

        galleries = [gallery_slug[g] for g in reps_by_artist.get(id_, []) if g in gallery_slug]

        fm = frontmatter(
            type="artist", name=name, name_en=name_en,
            birth_year=birth_year, death_year=death_year, nationality=nationality,
        )
        life = f"{birth_year or '?'}–{death_year or '?'}" if (birth_year or death_year) else ""
        body = f"# {name}\n\n"
        if name_en:
            body += f"영문명: {name_en}\n\n"
        if life:
            body += f"생몰: {life}\n\n"
        if nationality:
            body += f"국적: {nationality}\n\n"
        if bio:
            body += f"{bio}\n\n"
        if galleries:
            body += "## 전속/취급 갤러리\n\n"
            for g in galleries:
                body += f"- [[{g}]]\n"
            body += "\n"

        artworks = artworks_by_artist.get(id_, [])
        total = artwork_counts.get(id_, 0)
        body += f"## 소장 작품 ({total}건)\n\n"
        if artworks:
            body += "| 제목 | 연도 | 매체 | 소장처 |\n|---|---|---|---|\n"
            for title, year_created, medium, m_name in artworks:
                body += (
                    f"| {_escape_cell(title)} | {_escape_cell(year_created)} | "
                    f"{_escape_cell(medium)} | {_escape_cell(m_name)} |\n"
                )
            if total > len(artworks):
                body += f"\n*(외 {total - len(artworks)}건 더 — 상위 {MAX_LINKED_ARTWORKS}건만 표시)*\n"
        else:
            body += "(소장 기록 없음)\n"

        auctions = auctions_by_artist.get(id_, [])
        auction_total = auction_counts.get(id_, 0)
        if auctions:
            body += f"\n## 경매 기록 ({auction_total}건)\n\n"
            body += "| 경매사 | 날짜 | 낙찰가 | 통화 | 낙찰여부 |\n|---|---|---|---|---|\n"
            for house, auction_date, hammer_price, currency, sold in auctions:
                body += (
                    f"| {_escape_cell(house)} | {_escape_cell(auction_date)} | "
                    f"{_escape_cell(hammer_price)} | {_escape_cell(currency)} | "
                    f"{'낙찰' if sold else ('유찰' if sold is False else '?')} |\n"
                )
            if auction_total > len(auctions):
                body += f"\n*(외 {auction_total - len(auctions)}건 더 — 상위 {MAX_LINKED_AUCTIONS}건만 표시)*\n"

        write_md(VAULT_ROOT / "artists" / f"{slug}.md", fm + body)

    print(f"[vault:artists] {len(rows)}건 내보냄")
    return id_to_slug


def load_holdings(conn) -> dict[str, tuple[str, str | None]]:
    """artwork_id -> (museum_id, accession_number) — 작품당 최초 소장 레코드 1건."""
    cur = conn.cursor("holdings_export_cursor")
    cur.execute("select artwork_id, museum_id, accession_number from museum_holdings order by artwork_id")
    holdings: dict[str, tuple[str, str | None]] = {}
    while True:
        batch = cur.fetchmany(5000)
        if not batch:
            break
        for artwork_id, museum_id, accession_number in batch:
            holdings.setdefault(artwork_id, (museum_id, accession_number))
    cur.close()
    return holdings


def export_artworks(conn, artist_slug: dict[str, str], museum_slug: dict[str, str], limit: int | None) -> int:
    holdings = load_holdings(conn)
    print(f"[vault:artworks] museum_holdings {len(holdings)}건 사전 로드")

    cur = conn.cursor("artwork_export_cursor")
    q = """
        select a.id, a.artist_id, a.title, a.title_en, a.year_created, a.medium,
               a.dimensions, a.description
        from artworks a
    """
    if limit:
        q += f" limit {limit}"
    cur.execute(q)

    count = 0
    while True:
        batch = cur.fetchmany(2000)
        if not batch:
            break
        for id_, artist_id, title, title_en, year_created, medium, dimensions, description in batch:
            slug = slugify(title, id_)
            a_slug = artist_slug.get(artist_id)

            holding = holdings.get(id_)
            m_slug = museum_slug.get(holding[0]) if holding else None

            fm = frontmatter(
                type="artwork", title=title, title_en=title_en,
                year_created=year_created, medium=medium, dimensions=dimensions,
            )
            body = f"# {title}\n\n"
            if title_en:
                body += f"영문명: {title_en}\n\n"
            if a_slug:
                body += f"작가: [[{a_slug}]]\n\n"
            if year_created:
                body += f"제작연도: {year_created}\n\n"
            if medium:
                body += f"재료/기법: {medium}\n\n"
            if dimensions:
                body += f"크기: {dimensions}\n\n"
            if m_slug:
                body += f"소장처: [[{m_slug}]]" + (f" (accession {holding[1]})" if holding[1] else "") + "\n\n"
            if description:
                body += f"{description}\n\n"

            write_md(VAULT_ROOT / "artworks" / f"{slug}.md", body if not fm else fm + body)
            count += 1
            if count % 5000 == 0:
                print(f"[vault:artworks] {count}건 진행 중...")

    cur.close()
    print(f"[vault:artworks] {count}건 내보냄")
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="DB -> vault/ 마크다운 내보내기")
    parser.add_argument("--what", default="museums,galleries,artists,artworks")
    parser.add_argument("--limit", type=int, default=None, help="테스트용 — artists/artworks 각각에 적용")
    args = parser.parse_args()

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL 환경변수가 설정되지 않았습니다.")
    conn = psycopg2.connect(dsn)
    cur = conn.cursor()

    targets = set(args.what.split(","))

    museum_slug: dict[str, str] = {}
    gallery_slug: dict[str, str] = {}
    artist_slug: dict[str, str] = {}

    if "museums" in targets:
        museum_slug = export_museums(cur)
    if "galleries" in targets:
        gallery_slug = export_galleries(cur)
    if "artists" in targets:
        artist_slug = export_artists(conn, cur, gallery_slug, args.limit)
    if "artworks" in targets:
        if not artist_slug:
            cur.execute("select id, name from artists")
            artist_slug = {row[0]: slugify(row[1], row[0]) for row in cur.fetchall()}
        if not museum_slug:
            cur.execute("select id, name from museums")
            museum_slug = {row[0]: slugify(row[1], row[0]) for row in cur.fetchall()}
        export_artworks(conn, artist_slug, museum_slug, args.limit)

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
