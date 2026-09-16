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
    name = "".join(c for c in name if c.isprintable())  # bonhams 등 원본 텍스트에 섞인 제어문자(예: \x13) 제거 — Windows 경로에서 OSError 유발
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


ARTISTS_CHECKPOINT_PATH = Path(__file__).resolve().parent.parent / "docs" / "_artists_export_checkpoint.txt"


def export_artists(conn, cur, gallery_slug: dict[str, str], limit: int | None, resume: bool = False) -> dict[str, str]:
    """resume=True면 ARTISTS_CHECKPOINT_PATH에 저장된 마지막 처리 이름 이후부터 이어서
    처리한다(외부 요인으로 반복 kill되는 상황 대비, 2026-09-08). 파일 쓰기 자체가
    이미 덮어쓰기라 idempotent하므로, name 동률로 한두 건 건너뛰거나 겹쳐 써도 무해함
    — 정확한 재개 지점 계산 없이 "체크포인트 이전은 스킵"만 한다.
    주의: resume 시 id_to_slug에는 이번 실행에서 실제로 처리한 구간만 담긴다 —
    --what artists,artworks를 같은 프로세스에서 함께 돌릴 때는 resume을 쓰지 말 것."""
    resume_from_name: str | None = None
    if resume and ARTISTS_CHECKPOINT_PATH.exists():
        resume_from_name = ARTISTS_CHECKPOINT_PATH.read_text(encoding="utf-8").strip() or None
        if resume_from_name:
            print(f"[vault:artists] 체크포인트에서 재개: {resume_from_name!r} 이후부터")

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

    # named cursor + fetchmany 스트리밍 — 199K건을 fetchall()로 한 번에 들고
    # 있으면 artworks_by_artist/auctions_by_artist preload와 겹쳐 이 구간이
    # 메모리 피크가 된다(2026-09-08, 재수출이 이 지점 직후에서 반복 kill됨).
    # 배치 단위로 읽어 즉시 쓰고 버리는 식으로 rows 전체를 들고 있지 않는다.
    artists_cur = conn.cursor("export_artists_cursor")
    q = "select id, name, name_en, birth_year, death_year, nationality, bio from artists"
    params: tuple = ()
    if resume_from_name:
        q += " where name > %s"
        params = (resume_from_name,)
    q += " order by name"
    if limit:
        q += f" limit {limit}"
    artists_cur.execute(q, params)

    id_to_slug: dict[str, str] = {}
    written = 0
    last_name = resume_from_name
    while True:
        batch = artists_cur.fetchmany(5000)
        if not batch:
            break
        for id_, name, name_en, birth_year, death_year, nationality, bio in batch:
            id_to_slug[id_] = _export_one_artist(
                id_, name, name_en, birth_year, death_year, nationality, bio,
                reps_by_artist, gallery_slug, artworks_by_artist, artwork_counts,
                auctions_by_artist, auction_counts,
            )
            written += 1
            last_name = name
        print(f"[vault:artists] {written}건 진행 중...", flush=True)
        if resume and last_name is not None:
            ARTISTS_CHECKPOINT_PATH.write_text(last_name, encoding="utf-8")
    artists_cur.close()

    if resume and ARTISTS_CHECKPOINT_PATH.exists():
        ARTISTS_CHECKPOINT_PATH.unlink()
        print("[vault:artists] 완주 확인 — 체크포인트 삭제")

    print(f"[vault:artists] {written}건 내보냄")
    return id_to_slug


def _export_one_artist(
    id_, name, name_en, birth_year, death_year, nationality, bio,
    reps_by_artist, gallery_slug, artworks_by_artist, artwork_counts,
    auctions_by_artist, auction_counts,
) -> str:
        slug = slugify(name, id_)

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
        return slug


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


def export_artworks(
    conn, artist_slug: dict[str, str], museum_slug: dict[str, str], limit: int | None,
    source: str | None = None,
) -> int:
    holdings = load_holdings(conn)
    print(f"[vault:artworks] museum_holdings {len(holdings)}건 사전 로드")

    cur = conn.cursor("artwork_export_cursor")
    params: tuple = ()
    q = """
        select a.id, a.artist_id, a.title, a.title_en, a.year_created, a.medium,
               a.dimensions, a.description
        from artworks a
    """
    if source:
        q += " join sources s on s.id = a.source_id where s.site_name = %s"
        params = (source,)
    if limit:
        q += f" limit {limit}"
    cur.execute(q, params)

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


MAX_LINKED_LOTS = 300  # 경매사 문서 하나에 나열할 낙찰기록 상한


def export_auction_houses(conn, artist_slug: dict[str, str]) -> dict[str, str]:
    """auction_houses -> vault/auctions/*.md, 경매사별 낙찰기록(작품/작가 링크 포함)을 묶어서 문서화.
    개별 auction_lot 단위가 아니라 경매사 단위로 묶는다 — 10,461개 auctions/527,415개
    auction_lots를 각각 파일로 쪼개면 지나치게 잘게 나뉘고, artist 문서에도 이미
    작가별 경매요약이 있어(load_artist_auctions) 경매사 관점 문서가 빠진 부분을 채운다."""
    cur = conn.cursor()
    cur.execute("select id, name, country from auction_houses")
    houses = cur.fetchall()

    lots_cur = conn.cursor("auction_house_lots_export_cursor")
    lots_cur.execute(
        """
        select ah.id, au.name, au.auction_date, aw.id, aw.title, aw.artist_id,
               al.hammer_price, al.currency, al.sold
        from auction_lots al
        join auctions au on au.id = al.auction_id
        join auction_houses ah on ah.id = au.auction_house_id
        left join artworks aw on aw.id = al.artwork_id
        order by ah.id, au.auction_date desc nulls last
        """
    )
    lots_by_house: dict[str, list[tuple]] = {}
    lot_counts: dict[str, int] = {}
    while True:
        batch = lots_cur.fetchmany(5000)
        if not batch:
            break
        for house_id, auction_name, auction_date, aw_id, aw_title, artist_id, hammer_price, currency, sold in batch:
            lot_counts[house_id] = lot_counts.get(house_id, 0) + 1
            bucket = lots_by_house.setdefault(house_id, [])
            if len(bucket) < MAX_LINKED_LOTS:
                bucket.append((auction_name, auction_date, aw_id, aw_title, artist_id, hammer_price, currency, sold))
    lots_cur.close()

    id_to_slug: dict[str, str] = {}
    for id_, name, country in houses:
        slug = slugify(name, id_)
        id_to_slug[id_] = slug
        fm = frontmatter(type="auction_house", name=name, country=country)
        body = f"# {name}\n\n"
        if country:
            body += f"국가: {country}\n\n"

        lots = lots_by_house.get(id_, [])
        total = lot_counts.get(id_, 0)
        body += f"## 낙찰 기록 ({total}건)\n\n"
        if lots:
            body += "| 경매명 | 날짜 | 작품 | 작가 | 낙찰가 | 통화 | 낙찰여부 |\n|---|---|---|---|---|---|---|\n"
            for auction_name, auction_date, aw_id, aw_title, artist_id, hammer_price, currency, sold in lots:
                aw_slug = slugify(aw_title, aw_id) if (aw_id and aw_title) else None
                a_slug = artist_slug.get(artist_id) if artist_id else None
                aw_cell = f"[[{aw_slug}]]" if aw_slug else _escape_cell(aw_title)
                a_cell = f"[[{a_slug}]]" if a_slug else ""
                body += (
                    f"| {_escape_cell(auction_name)} | {_escape_cell(auction_date)} | {aw_cell} | {a_cell} | "
                    f"{_escape_cell(hammer_price)} | {_escape_cell(currency)} | "
                    f"{'낙찰' if sold else ('유찰' if sold is False else '?')} |\n"
                )
            if total > len(lots):
                body += f"\n*(외 {total - len(lots)}건 더 — 상위 {MAX_LINKED_LOTS}건만 표시)*\n"
        else:
            body += "(낙찰 기록 없음)\n"

        write_md(VAULT_ROOT / "auctions" / f"{slug}.md", fm + body)

    print(f"[vault:auctions] {len(houses)}건 내보냄")
    return id_to_slug


MAX_LINKED_PROVENANCE = 300  # 컬렉터 문서 하나에 나열할 프로버넌스 레코드 상한


def export_collectors(conn, artist_slug: dict[str, str]) -> int:
    """collectors -> vault/collectors/*.md, 소장/거쳐간 작품 이력(provenance_records)을 묶어 문서화."""
    cur = conn.cursor()
    cur.execute("select id, name, is_institution, bio from collectors")
    rows = cur.fetchall()

    prov_cur = conn.cursor("collector_provenance_export_cursor")
    prov_cur.execute(
        """
        select p.owner_collector_id, aw.id, aw.title, aw.artist_id, p.acquired_date, p.acquired_method, p.disposed_date
        from provenance_records p
        join artworks aw on aw.id = p.artwork_id
        where p.owner_type = 'collector' and p.owner_collector_id is not null
        order by p.owner_collector_id
        """
    )
    by_collector: dict[str, list[tuple]] = {}
    counts: dict[str, int] = {}
    while True:
        batch = prov_cur.fetchmany(5000)
        if not batch:
            break
        for collector_id, aw_id, aw_title, artist_id, acquired_date, acquired_method, disposed_date in batch:
            counts[collector_id] = counts.get(collector_id, 0) + 1
            bucket = by_collector.setdefault(collector_id, [])
            if len(bucket) < MAX_LINKED_PROVENANCE:
                bucket.append((aw_id, aw_title, artist_id, acquired_date, acquired_method, disposed_date))
    prov_cur.close()

    count = 0
    for id_, name, is_institution, bio in rows:
        slug = slugify(name, id_)
        fm = frontmatter(type="collector", name=name, is_institution=is_institution)
        body = f"# {name}\n\n"
        if is_institution:
            body += "기관 컬렉터\n\n"
        if bio:
            body += f"{bio}\n\n"

        records = by_collector.get(id_, [])
        total = counts.get(id_, 0)
        body += f"## 소장/거쳐간 작품 ({total}건)\n\n"
        if records:
            body += "| 작품 | 작가 | 취득일 | 취득방법 | 처분일 |\n|---|---|---|---|---|\n"
            for aw_id, aw_title, artist_id, acquired_date, acquired_method, disposed_date in records:
                aw_slug = slugify(aw_title, aw_id) if (aw_id and aw_title) else None
                a_slug = artist_slug.get(artist_id) if artist_id else None
                aw_cell = f"[[{aw_slug}]]" if aw_slug else _escape_cell(aw_title)
                a_cell = f"[[{a_slug}]]" if a_slug else ""
                body += (
                    f"| {aw_cell} | {a_cell} | {_escape_cell(acquired_date)} | "
                    f"{_escape_cell(acquired_method)} | {_escape_cell(disposed_date)} |\n"
                )
            if total > len(records):
                body += f"\n*(외 {total - len(records)}건 더 — 상위 {MAX_LINKED_PROVENANCE}건만 표시)*\n"
        else:
            body += "(기록 없음)\n"

        write_md(VAULT_ROOT / "collectors" / f"{slug}.md", fm + body)
        count += 1

    print(f"[vault:collectors] {count}건 내보냄")
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="DB -> vault/ 마크다운 내보내기")
    parser.add_argument("--what", default="museums,galleries,artists,artworks,auctions,collectors")
    parser.add_argument("--limit", type=int, default=None, help="테스트용 — artists/artworks 각각에 적용")
    parser.add_argument("--source", default=None, help="artworks만 특정 site_name으로 증분 재수출 (예: bonhams)")
    parser.add_argument(
        "--resume", action="store_true",
        help="artists 재수출을 docs/_artists_export_checkpoint.txt 체크포인트부터 이어서 진행",
    )
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
        artist_slug = export_artists(conn, cur, gallery_slug, args.limit, resume=args.resume)
    if "artworks" in targets:
        if not artist_slug:
            cur.execute("select id, name from artists")
            artist_slug = {row[0]: slugify(row[1], row[0]) for row in cur.fetchall()}
        if not museum_slug:
            cur.execute("select id, name from museums")
            museum_slug = {row[0]: slugify(row[1], row[0]) for row in cur.fetchall()}
        export_artworks(conn, artist_slug, museum_slug, args.limit, source=args.source)

    if "auctions" in targets or "collectors" in targets:
        if not artist_slug:
            cur.execute("select id, name from artists")
            artist_slug = {row[0]: slugify(row[1], row[0]) for row in cur.fetchall()}
        if "auctions" in targets:
            export_auction_houses(conn, artist_slug)
        if "collectors" in targets:
            export_collectors(conn, artist_slug)

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
