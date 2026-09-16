"""SMK 로더가 그대로 넣은 덴마크어 국적(Dansk/Tysk/Fransk …)을 기존 관행(영문 demonym)으로 정규화. 다중값("Dansk, Tysk")은 첫 값만.
기본 리포트, --apply 시 UPDATE. idempotent."""
from __future__ import annotations
import argparse, sys
from artist_merge_util import get_conn
sys.stdout.reconfigure(encoding="utf-8")
DA = {"dansk": "Danish", "tysk": "German", "fransk": "French", "italiensk": "Italian", "hollandsk": "Dutch", "nederlandsk": "Dutch",
      "svensk": "Swedish", "flamsk": "Flemish", "norsk": "Norwegian", "engelsk": "English", "schweizisk": "Swiss", "britisk": "British",
      "østrigsk": "Austrian", "spansk": "Spanish", "amerikansk": "American", "japansk": "Japanese", "belgisk": "Belgian", "finsk": "Finnish",
      "tjekkisk": "Czech", "polsk": "Polish", "litauisk": "Lithuanian", "islandsk": "Icelandic", "ungarsk": "Hungarian", "russisk": "Russian",
      "grønlandsk": "Greenlandic", "irsk": "Irish", "færøsk": "Faroese", "skotsk": "Scottish", "portugisisk": "Portuguese", "græsk": "Greek",
      "kinesisk": "Chinese", "canadisk": "Canadian", "australsk": "Australian", "estisk": "Estonian", "lettisk": "Latvian", "rumænsk": "Romanian",
      "ukrainsk": "Ukrainian", "mexicansk": "Mexican", "brasiliansk": "Brazilian", "argentinsk": "Argentine", "koreansk": "Korean", "indisk": "Indian",
      "tyrkisk": "Turkish", "israelsk": "Israeli", "sydafrikansk": "South African", "kroatisk": "Croatian", "serbisk": "Serbian", "slovakisk": "Slovak",
      "bulgarsk": "Bulgarian", "hviderussisk": "Belarusian", "luxembourgsk": "Luxembourgish"}

ap = argparse.ArgumentParser(); ap.add_argument("--apply", action="store_true"); args = ap.parse_args()
conn = get_conn(); cur = conn.cursor()
cur.execute("select nationality, count(*) from artists where nationality is not null group by 1")
plan, unknown = [], {}
for nat, n in cur.fetchall():
    first = nat.split(",")[0].strip().lower()
    if first in DA:
        plan.append((DA[first], nat, n))
    elif first.endswith("sk") and n >= 1 and first not in ("polish",):
        unknown[nat] = n
print(f"정규화 대상 값 {len(plan)} (행 {sum(n for *_, n in plan)}), 미매핑 -sk 값: {sorted(unknown.items(), key=lambda x: -x[1])[:20]}")
for new, old, n in sorted(plan, key=lambda x: -x[2])[:10]:
    print("  ", old, "→", new, n)
if args.apply:
    cur.executemany("update artists set nationality = %s, updated_at = now() where nationality = %s", [(a, b) for a, b, _ in plan])
    conn.commit(); print("완료")
else:
    print("--apply 없음: 리포트만")
