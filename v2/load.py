"""원본(raw) -> 파서 -> artgraph_v2 DB. 기본은 리포트만, --apply로 반영 (idempotent).

    python v2/load.py                     # 파싱 결과 리포트 (DB 쓰기 없음)
    python v2/load.py --apply             # 반영
    python v2/load.py --only venice_2024  # 회차 지정

파서 출력 계약 (parsers/*.py, 원본 텍스트 -> list[dict]):
  비엔날레: {"name", "name_ko"?, "name_en"?, "country"?, "birth_year"?, "section"?}
  페어:     {"gallery", "gallery_ko"?, "gallery_en"?, "gallery_city"?, "booth"?, "section"?,
             "artists": [{"name", "name_ko"?, "name_en"?}]}
작가·갤러리 동일성은 alias_key(정규화 표기) 정확일치만 — 이름·한글명·영문명 중 하나라도 기존 별칭과
같으면 같은 엔티티, 아니면 새로 만든다. 서로 다른 두 엔티티에 걸치면 첫 매칭을 쓰고 리포트에 남긴다.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATA_ROOT, RAW_ROOT, V2_ROOT, alias_key, get_conn, read_meta  # noqa: E402
from registry import EDITIONS, SERIES, resolve  # noqa: E402

LOG_DIR = DATA_ROOT / "logs"
PAGE_RE = re.compile(r"^(?P<eid>.+)__p(?P<i>\d{2})(?:d(?P<j>\d{3}))?\.(?P<ext>.+)$")
COLLECTIVE_RE = re.compile(
    r"\b(collective|collectif|colectivo|coletivo|kollektiv|group|groupe|grupo|cooperative|"
    r"association|assembly|foundation|network|initiative|ensemble|institute|society|platform|"
    r"council|union|club)\b|\s(and|&|\+)\s",
    re.I,
)


def edition_pages(eid: str):
    """회차의 원본 페이지를 (source 인덱스, detail 여부, 경로) 순으로."""
    site_dir = RAW_ROOT / EDITIONS[eid]["series"]
    out = []
    for p in sorted(site_dir.glob(f"{eid}__p*")):
        if p.name.endswith(".meta.json"):
            continue
        m = PAGE_RE.match(p.name)
        if m and m["eid"] == eid:
            out.append((int(m["i"]), m["j"] is not None, p))
    return out


def page_text(path: Path) -> str:
    if path.suffix == ".pdf":
        import pymupdf  # 파서들이 PyMuPDF 텍스트 기준으로 작성됨 — pypdf와 줄바꿈이 달라 섞어 쓰지 말 것
        with pymupdf.open(str(path)) as doc:
            return "\n".join(pg.get_text() for pg in doc)
    return path.read_text(encoding="utf-8")


def prebuilt_edition(eid: str):
    """페어처럼 여러 원본(목록 HTML·카탈로그 PDF·웨이백 스냅샷)을 엮어 회차 JSON을 조립하는 소스용.

    조립은 research/<fair>/build*.py가 캐시된 원본만으로(네트워크 없이) 하고, 회차 JSON의
    `files` {url: research/<fair>/ 기준 상대경로}로 원본 파일마다 sources 행을 만든다. 부스의
    `sources`(실제 받은 URL들) 첫 항목을 그 부스 참가 기록의 근거로 쓴다.
    """
    ed = EDITIONS[eid]
    built = DATA_ROOT / ed["prebuilt"]
    if not built.exists():
        return [], []
    d = json.loads(built.read_text(encoding="utf-8"))
    base = built.parent.parent if built.parent.name == "built" else built.parent
    metas, by_url = [], {}
    for url, rel in (d.get("files") or {}).items():
        path = base / rel
        if not path.exists():
            continue
        m = {
            "url": url,
            "fetched_at": datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(),
            "raw_path": str(path.relative_to(DATA_ROOT)).replace("\\", "/"),
            "source_tier": "archive" if "web.archive.org" in url else ("official_pdf" if rel.lower().endswith(".pdf") else "official"),
            "license_note": ed.get("license", ""),
        }
        metas.append(m)
        by_url[url] = m["raw_path"]
    if not metas:
        raise RuntimeError(f"{eid}: 회차 JSON에 files 매핑이 없거나 원본 파일이 없음 — 근거 없는 적재 금지")
    records = []
    for b in d.get("booths") or []:
        urls = [u["url"] if isinstance(u, dict) else u for u in (b.get("sources") or [])]
        page = next((by_url[u] for u in urls if u in by_url), metas[0]["raw_path"])
        records.append({**b, "_page": page})
    if ed.get("prebuilt_adapter"):  # 시리즈별 표기 정리(특별전 분리, 한/영 혼합 이름 분리 등)
        records = resolve(ed["prebuilt_adapter"])(records, eid)
    return records, metas


def parse_edition(eid: str):
    """-> (records, metas). records: 파서 출력에 '_page'(raw 경로) 추가."""
    ed = EDITIONS[eid]
    if ed.get("prebuilt"):
        return prebuilt_edition(eid)
    if ed.get("edition_parser"):
        pages = edition_pages(eid)
        metas = [read_meta(p) for _, _, p in pages]
        texts = [page_text(p) for _, is_detail, p in pages if not is_detail]
        records = resolve(ed["edition_parser"])(texts, **ed.get("edition_parser_kwargs", {})) if texts else []
        for rec in records:
            rec.setdefault("_page", metas[0]["raw_path"])
        return records, metas
    per_page, metas = [], []
    for i, is_detail, path in edition_pages(eid):
        src = ed["sources"][i]
        fn_name = src.get("detail_parser") if is_detail else src.get("parser")
        meta = read_meta(path)
        metas.append(meta)
        if not fn_name:
            continue  # 목록 페이지가 상세 URL 발견용일 뿐인 경우
        recs = resolve(fn_name)(page_text(path))
        for rec in recs:
            rec.setdefault("_page", meta["raw_path"])
        per_page.append(recs)
    if ed.get("combine"):
        # 한/영 페이지를 한 작가로 합치는 등 페이지 간 결합 — 결합된 레코드는 첫 페이지를 근거로 남긴다
        first = metas[0]["raw_path"] if metas else None
        records = resolve(ed["combine"])(per_page)
        for rec in records:
            rec.setdefault("_page", first)
    else:
        records = [r for recs in per_page for r in recs]
    return records, metas


class Resolver:
    """alias_key -> id 캐시를 들고 작가/갤러리를 찾거나 만든다.

    한 레코드의 표기들(예: 영문명·한글명)이 서로 다른 기존 엔티티 둘에 걸리면, 그 둘은 한쪽 명단엔
    한글만·다른 명단엔 영문만 있어 따로 생긴 같은 대상이다 — 공식 이중언어 명단 한 줄이 다리를
    놓은 경우이므로 병합한다(유사도 추정이 아니라 같은 레코드의 정확일치 근거). 병합은 리포트에 남긴다.
    """

    def __init__(self, cur, table: str, alias_table: str, fk: str, fill_cols: tuple[str, ...]):
        self.cur, self.table, self.alias_table, self.fk = cur, table, alias_table, fk
        self.fill_cols = fill_cols
        cur.execute(f"select alias_key, {fk} from {alias_table}")
        self.cache = {k: str(v) for k, v in cur.fetchall()}
        self.created = 0
        self.last_created = False
        self.conflicts: list[str] = []
        self.merges: list[str] = []

    def lookup(self, names: list[str | None]) -> list[str]:
        hits = []
        for n in names:
            k = alias_key(n)
            if k and k in self.cache and self.cache[k] not in hits:
                hits.append(self.cache[k])
        if len(hits) > 1:
            self.conflicts.append(" / ".join(n for n in names if n))
        return hits

    def get_or_create(self, cols: dict, names: list[str | None], apply: bool) -> str | None:
        hits = self.lookup(names)
        self.last_created = False
        if not apply:
            return hits[0] if hits else None
        if hits:
            keep = hits[0]
            for drop in hits[1:]:
                self._merge(keep, drop, names)
            self._fill(keep, cols)
            self._register(keep, names)
            return keep
        keys = ", ".join(cols)
        self.cur.execute(
            f"insert into {self.table} ({keys}) values ({', '.join(['%s'] * len(cols))}) returning id",
            list(cols.values()),
        )
        new_id = str(self.cur.fetchone()[0])
        self.created += 1
        self.last_created = True
        self._register(new_id, names)
        return new_id

    def _fill(self, eid: str, cols: dict):
        sets = [f"{c} = coalesce({c}, %s)" for c in self.fill_cols if cols.get(c) is not None]
        if sets:
            self.cur.execute(f"update {self.table} set {', '.join(sets)} where id = %s",
                             [cols[c] for c in self.fill_cols if cols.get(c) is not None] + [eid])

    def _merge(self, keep: str, drop: str, names):
        cur = self.cur
        if self.table == "artists":
            cur.execute(
                """delete from participations p where artist_id = %s and exists (
                     select 1 from participations q where q.artist_id = %s and q.edition_id = p.edition_id
                       and q.section = p.section
                       and coalesce(q.booth_id, '00000000-0000-0000-0000-000000000000'::uuid)
                         = coalesce(p.booth_id, '00000000-0000-0000-0000-000000000000'::uuid))""", (drop, keep))
            cur.execute("update participations set artist_id = %s where artist_id = %s", (keep, drop))
        else:
            cur.execute(
                """delete from fair_booths b where gallery_id = %s and exists (
                     select 1 from fair_booths c where c.gallery_id = %s and c.edition_id = b.edition_id
                       and c.section = b.section)""", (drop, keep))
            cur.execute("update fair_booths set gallery_id = %s where gallery_id = %s", (keep, drop))
        cur.execute(f"update {self.alias_table} set {self.fk} = %s where {self.fk} = %s", (keep, drop))
        fills = ", ".join(f"{c} = coalesce(k.{c}, d.{c})" for c in self.fill_cols)
        cur.execute(f"update {self.table} k set {fills} from {self.table} d where k.id = %s and d.id = %s", (keep, drop))
        cur.execute(f"delete from {self.table} where id = %s", (drop,))
        for k, v in self.cache.items():
            if v == drop:
                self.cache[k] = keep
        self.merges.append(f"{drop} -> {keep}: " + " / ".join(n for n in names if n))

    def _register(self, eid: str, names):
        for n in names:
            k = alias_key(n)
            if k and k not in self.cache:
                self.cur.execute(
                    f"insert into {self.alias_table} (alias_key, {self.fk}) values (%s,%s) on conflict do nothing",
                    (k, eid),
                )
                self.cache[k] = eid


def upsert_registry(cur):
    for sid, s in SERIES.items():
        cur.execute(
            """insert into series (id, kind, name, name_ko, city, country) values (%s,%s,%s,%s,%s,%s)
               on conflict (id) do update set kind=excluded.kind, name=excluded.name, name_ko=excluded.name_ko,
                 city=excluded.city, country=excluded.country""",
            (sid, s["kind"], s["name"], s.get("name_ko"), s.get("city"), s.get("country")),
        )
    for eid, e in EDITIONS.items():
        cur.execute(
            """insert into editions (id, series_id, year, label, title, start_date, end_date, city,
                 announced_count, coverage, coverage_note)
               values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               on conflict (id) do update set year=excluded.year, label=excluded.label, title=excluded.title,
                 start_date=excluded.start_date, end_date=excluded.end_date, city=excluded.city,
                 announced_count=excluded.announced_count, coverage=excluded.coverage,
                 coverage_note=excluded.coverage_note""",
            (eid, e["series"], e["year"], e["label"], e.get("title"), e.get("start_date"), e.get("end_date"),
             e.get("city") or SERIES[e["series"]].get("city"), e.get("announced"), e.get("coverage"),
             e.get("coverage_note")),
        )


def artist_cols(a: dict) -> tuple[dict, list]:
    """대표 표기 = 영문명(있으면) > 원 표기. 한글명은 name_ko에 따로 — 한국 명단의 외국 작가는
    한글 음차('매튜 바니')로만 오는 경우가 있어 영문명이 있으면 그걸 대표로 둬야 다른 회차와 맞는다."""
    name_en = a.get("name_en") or None
    name = name_en or a["name"]
    cols = {
        "name": name,
        "name_ko": a.get("name_ko"),
        "name_en": name_en,
        "kind": "collective" if a.get("collective") or COLLECTIVE_RE.search(name) else "person",
        "birth_year": a.get("birth_year") if isinstance(a.get("birth_year"), int) else None,
    }
    return cols, [a["name"], a.get("name_ko"), a.get("name_en"), *(a.get("aliases") or [])]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--only", nargs="*")
    args = ap.parse_args()
    ids = [e for e in EDITIONS if not args.only or e in args.only]

    conn = get_conn()
    cur = conn.cursor()
    if args.apply:
        upsert_registry(cur)
        conn.commit()
    artists = Resolver(cur, "artists", "artist_aliases", "artist_id",
                       fill_cols=("name_ko", "name_en", "birth_year"))
    galleries = Resolver(cur, "galleries", "gallery_aliases", "gallery_id",
                         fill_cols=("name_ko", "name_en", "city"))
    report = {"generated_at": datetime.now().isoformat(timespec="seconds"), "apply": args.apply, "editions": {}}

    for eid in ids:
        ed = EDITIONS[eid]
        kind = SERIES[ed["series"]]["kind"]
        records, metas = parse_edition(eid)
        if not metas:
            report["editions"][eid] = {"status": "no_raw"}
            print(f"{eid:26s} (원본 없음)")
            continue
        src_ids = {}
        if args.apply:
            for m in metas:
                cur.execute(
                    """insert into sources (url, fetched_at, raw_path, source_tier, license_note)
                       values (%s,%s,%s,%s,%s)
                       on conflict (raw_path) do update set fetched_at=excluded.fetched_at returning id""",
                    (m["url"], m["fetched_at"], m["raw_path"], m["source_tier"], m["license_note"]),
                )
                src_ids[m["raw_path"]] = str(cur.fetchone()[0])

        st = Counter()
        seen_artists = set()
        if kind == "biennale":
            for a in records:
                cols, names = artist_cols(a)
                aid = artists.get_or_create(cols, names, args.apply)
                st["new" if (not aid or artists.last_created) else "matched_existing"] += 1
                seen_artists.add(aid or alias_key(a["name"]))
                if args.apply:
                    cur.execute(
                        """insert into participations (edition_id, artist_id, section, name_as_listed, country_as_listed, source_id)
                           values (%s,%s,%s,%s,%s,%s) on conflict do nothing""",
                        (eid, aid, a.get("section") or "main", a["name"], a.get("country"), src_ids[a["_page"]]),
                    )
        else:
            for b in records:
                booth_id = None
                if not b.get("gallery"):
                    # 갤러리 부스가 아닌 작가 단위 프로그램(특별전·조각공원·작가상 등) — 부스 없이 섹션만
                    st["artist_level_entries"] += 1
                else:
                    gnames = [b["gallery"], b.get("gallery_ko"), b.get("gallery_en")]
                    gid = galleries.get_or_create(
                        {"name": b.get("gallery_en") or b["gallery"], "name_ko": b.get("gallery_ko"),
                         "name_en": b.get("gallery_en"), "city": b.get("gallery_city")}, gnames, args.apply)
                    st["booths"] += 1
                if args.apply and b.get("gallery"):
                    section = b.get("section") or "main"
                    cur.execute(
                        """insert into fair_booths (edition_id, gallery_id, section, booth, gallery_name_as_listed, source_id)
                           values (%s,%s,%s,%s,%s,%s)
                           on conflict (edition_id, gallery_id, section) do update set booth=coalesce(fair_booths.booth, excluded.booth)
                           returning id""",
                        (eid, gid, section, b.get("booth"), b["gallery"], src_ids[b["_page"]]),
                    )
                    booth_id = str(cur.fetchone()[0])
                for a in b.get("artists") or []:
                    cols, names = artist_cols(a)
                    aid = artists.get_or_create(cols, names, args.apply)
                    st["artist_links"] += 1
                    seen_artists.add(aid or alias_key(a["name"]))
                    if args.apply:
                        cur.execute(
                            """insert into participations (edition_id, artist_id, section, booth_id, name_as_listed, source_id)
                               values (%s,%s,%s,%s,%s,%s) on conflict do nothing""",
                            (eid, aid, b.get("section") or "main", booth_id, a["name"], src_ids[b["_page"]]),
                        )
        if args.apply:
            conn.commit()
        st["unique_artists"] = len(seen_artists)
        report["editions"][eid] = {"label": ed["label"], "announced": ed.get("announced"),
                                   "coverage": ed.get("coverage"), "pages": len(metas), **st}
        print(f"{eid:26s} pages={len(metas):3d} announced={ed.get('announced')!s:>5} "
              + " ".join(f"{k}={v}" for k, v in sorted(st.items())), flush=True)

    report["artists_created"] = artists.created
    report["galleries_created"] = galleries.created
    report["artist_alias_conflicts"] = artists.conflicts[:200]
    report["gallery_alias_conflicts"] = galleries.conflicts[:200]
    report["artist_merges"] = artists.merges
    report["gallery_merges"] = galleries.merges
    if args.apply:  # 대표 표기 규칙(영문명 우선) 재적용 — 병합·보충으로 name_en이 새로 생긴 행
        cur.execute("update artists set name = name_en where name_en is not null and name <> name_en")
        conn.commit()
    print(f"artists_created={artists.created} galleries_created={galleries.created} "
          f"alias_conflicts={len(artists.conflicts)}/{len(galleries.conflicts)} merges={len(artists.merges)}/{len(galleries.merges)}")
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    out = LOG_DIR / f"load_{'apply' if args.apply else 'report'}_{datetime.now():%Y%m%d_%H%M%S}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("report ->", out)


if __name__ == "__main__":
    main()
