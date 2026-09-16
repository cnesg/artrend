"""역할 접두어 작가명("Photographer: Edward Steichen", "Designer: Unknown") 정리 (2026-09-15 §M4).

mia(구 로더)·smithsonian 등에서 "<역할>: <이름>" 형태가 artists.name에 그대로 들어간 행이
약 3,100건(작품 3만+)이다(진단 audit5). 규칙:
  - 역할이 창작 역할(_MAKER_ROLES — pipeline/mia.py와 동일 목록)이면 접두어를 떼고
    같은 이름의 기존 행에 재연결(없으면 in-place 개명). "Photographer: Edward Steichen" → "Edward Steichen".
  - 역할이 비창작(Publisher/Manufacturer/Producer/Printer/Editor/Author/Distributor 등)이면
    이름은 그대로 두고 entity_kind='organization'(note='role:<역할>')로 표시 — 그 행은 작가가 아니라
    유통/제작 주체라 작가 레벨 Q&A에서 제외돼야 한다.
  - 떼어낸 이름이 익명 표기(Unknown/Unidentified …)면 개명하지 않고 분류 스크립트에 맡긴다.
기본 리포트, --apply 시 반영. idempotent.
"""
from __future__ import annotations

import argparse
import re
import sys

from artist_merge_util import fill_missing_meta, get_conn, norm_exact, relink_and_delete

sys.stdout.reconfigure(encoding="utf-8")

ROLE_RE = re.compile(r"^(?P<role>[A-Za-z][A-Za-z ]{1,25}):\s+(?P<name>.+)$")
MAKER_ROLES = {
    "designer", "engraver", "painter", "photographer", "lithographer", "carver", "etcher",
    "delineator", "sculptor", "draftsman", "cartoonist", "calligrapher", "illustrator", "colorist",
    "architect", "weaver", "decorator", "potter", "silversmith", "woodcutter", "gilder", "goldsmith",
    "jeweler", "embroiderer", "ceramist", "enameller", "modeler", "caster", "fabricator", "composer",
    "poet", "performer", "miniaturist", "creator", "maker", "printmaker", "artist", "author of design",
}
NON_MAKER_ROLES = {
    "publisher", "manufacturer", "producer", "printer", "editor", "author", "distributor", "retailer",
    "workshop", "firm", "factory", "foundry", "founder", "patron", "commissioner", "sitter", "subject",
    "owner", "dealer", "translator", "compiler", "binder", "bookbinder", "lender", "donor",
}
ANON_RE = re.compile(r"^(unknown|unidentified|anonymous|anonyme|anoniem|unbekannt|various)\b", re.I)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(r"select id::text, name, entity_kind from artists where name ~ '^[A-Za-z][A-Za-z ]{1,25}:\s'")
    rows = cur.fetchall()
    cur.execute("select id::text, name from artists where name !~ '^[A-Za-z][A-Za-z ]{1,25}:\\s'")
    by_key: dict[str, str] = {}
    for aid, name in cur.fetchall():
        by_key.setdefault(norm_exact(name), aid)

    relink, inplace, mark_org, anon, unknown_role = [], [], [], [], {}
    taken: dict[str, str] = {}
    for aid, name, kind in rows:
        m = ROLE_RE.match(name)
        if not m:
            continue
        role = m.group("role").strip().lower()
        base = " ".join(m.group("name").split())
        if ANON_RE.match(base):
            anon.append(name)
            continue
        if role in MAKER_ROLES:
            key = norm_exact(base)
            if key in by_key:
                relink.append((aid, by_key[key], name, base))
            elif key in taken:
                relink.append((aid, taken[key], name, base))
            else:
                taken[key] = aid
                inplace.append((aid, name, base))
        elif role in NON_MAKER_ROLES:
            if kind != "organization":
                mark_org.append((aid, name, role))
        else:
            unknown_role[role] = unknown_role.get(role, 0) + 1

    print(f"대상 {len(rows)} → 재연결 {len(relink)} / in-place 개명 {len(inplace)} / organization 표시 {len(mark_org)} / 익명 스킵 {len(anon)}")
    print("미분류 역할:", sorted(unknown_role.items(), key=lambda x: -x[1])[:20])
    for x in relink[:8]:
        print("  relink:", x[2], "→", x[3])
    for x in inplace[:5]:
        print("  inplace:", x[1], "→", x[2])
    for x in mark_org[:5]:
        print("  org:", x[1])
    if not args.apply:
        print("--apply 없음: 리포트만")
        return
    n = 0
    for aid, cid, _, _ in relink:
        fill_missing_meta(cur, cid, aid)
        n += relink_and_delete(cur, aid, cid)
        conn.commit()
    for aid, _, base in inplace:
        cur.execute("update artists set name = %s, updated_at = now() where id = %s", (base, aid))
    for aid, _, role in mark_org:
        cur.execute(
            "update artists set entity_kind = 'organization', entity_kind_note = %s, updated_at = now() where id = %s",
            (f"role:{role}", aid),
        )
    conn.commit()
    print(f"완료: 재연결 {n}건, 개명 {len(inplace)}, organization {len(mark_org)}")


if __name__ == "__main__":
    main()
