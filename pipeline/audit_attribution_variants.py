"""'귀속 표기 변형'(Attributed to / school of / d'apres / manner of 등) 스코프 리포트.

목적: 특정 작가(예: Rembrandt)가 원작자 본인 표기와 화파/모작/귀속불확실
표기로 artists 테이블에 여러 행으로 쪼개져 있는 문제가 얼마나 광범위한지
파악한다. **이 스크립트는 아무것도 수정하지 않는다** — 리포트만 생성.

분류 기준:
  1. 순수 철자변형(spelling variant): 귀속 수식어 없이 core name의 철자만
     다른 것 (예: "Rembrandt van Rhijn" vs "Rembrandt van Rijn"). 기존
     dedup 스크립트들과 같은 성격이라 병합해도 정보 손실이 없어 보이는 후보.
  2. 귀속 수식어 포함(attribution-qualified): "Attributed to", "school of",
     "d'apres", "manner of", "circle of", "follower of", "workshop of",
     "copy after", "Nachahmer", "Schule von", "Umkreis von" 등 다국어 수식어가
     붙은 것 — 원작자 본인과 실제로 다른 미술사적 카테고리이므로 **병합 후보에서
     제외**하고 별도로만 분류한다.

core name을 정규화(악센트 제거, 소문자, 공백/구두점 정리)해서 묶고, 같은
core name 그룹 안에 "순수 표기"와 "귀속 수식어 표기"가 함께 있으면
richness(연결된 artworks/museum_holdings 건수)와 함께 리포트에 남긴다.
"""
from __future__ import annotations

import os
import re
import sys
import unicodedata
from collections import defaultdict

import psycopg2

sys.stdout.reconfigure(encoding="utf-8")

# 다국어 귀속 수식어 패턴 (소문자 매칭, 정규화된 문자열에 대해 적용)
ATTRIBUTION_PATTERNS = [
    # 영어
    r"^attributed to\b",
    r"^attr\.?\s*to\b",
    r"^school of\b",
    r"^circle of\b",
    r"^follower of\b",
    r"^studio of\b",
    r"^workshop of\b",
    r"^manner of\b",
    r"^style of\b",
    r"^copy after\b",
    r"^after\b",
    r"^imitator of\b",
    r"^in the manner of\b",
    r"^pupil of\b",
    r"^assistant to\b",
    r"^possibly\b",
    r"^attributed\b",
    # 프랑스어
    r"^attribu[ée] [àa]\b",
    r"^[ée]cole de\b",
    r"^d'apr[èe]s\b",
    r"^mani[èe]re de\b",
    r"^atelier de\b",
    r"^suiveur de\b",
    r"^cercle de\b",
    r"^entourage de\b",
    r"^copie d'apr[èe]s\b",
    # 독일어
    r"^nachahmer\b",
    r"^schule von\b",
    r"^umkreis von\b",
    r"^werkstatt von\b",
    r"^nach\b",
    r"^kopie nach\b",
    r"^art des?\b",
    # 이탈리아어
    r"^attribuito a\b",
    r"^scuola di\b",
    r"^seguace di\b",
    r"^bottega di\b",
    r"^cerchia di\b",
    r"^copia da\b",
    # 네덜란드어
    r"^naar\b",
    r"^school van\b",
    r"^atelier van\b",
    r"^navolger van\b",
    r"^omgeving van\b",
    r"^kring van\b",
    # 스페인어
    r"^atribuido a\b",
    r"^escuela de\b",
    r"^taller de\b",
    r"^seguidor de\b",
    r"^c[íi]rculo de\b",
    r"^copia de\b",
]
ATTRIBUTION_RE = re.compile("|".join(ATTRIBUTION_PATTERNS), re.IGNORECASE)

# core name 뒤에 붙는 수식어 (예: "Rembrandt, school of")
TRAILING_ATTRIBUTION_RE = re.compile(
    r",?\s*(school|circle|studio|workshop|atelier)\s*$", re.IGNORECASE
)


def strip_accents(s: str) -> str:
    nf = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nf if not unicodedata.combining(c))


def normalize(name: str) -> str:
    n = strip_accents(name).lower()
    n = re.sub(r"[.,;:()\[\]\"']", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n


def extract_core(norm_name: str) -> tuple[str, bool]:
    """attribution 수식어를 제거한 core name과, 수식어가 있었는지 여부를 반환."""
    has_attr = False
    core = norm_name
    m = ATTRIBUTION_RE.match(core)
    if m:
        has_attr = True
        core = core[m.end():].strip()
        # "attributed to rembrandt van rijn" -> 이미 뒤에 이름
    if TRAILING_ATTRIBUTION_RE.search(core):
        has_attr = True
        core = TRAILING_ATTRIBUTION_RE.sub("", core).strip()
    return core, has_attr


def levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    la, lb = len(a), len(b)
    if la == 0:
        return lb
    if lb == 0:
        return la
    prev = list(range(lb + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * lb
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
        prev = cur
    return prev[lb]


def main() -> None:
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()

    cur.execute(
        """
        select a.id, a.name,
               coalesce(aw.n, 0) as artwork_n,
               coalesce(mh.n, 0) as holding_n
        from artists a
        left join (select artist_id, count(*) n from artworks group by artist_id) aw
          on aw.artist_id = a.id
        left join (
          select w.artist_id, count(*) n
          from museum_holdings mh
          join artworks w on w.id = mh.artwork_id
          group by w.artist_id
        ) mh
          on mh.artist_id = a.id
        """
    )
    rows = cur.fetchall()
    print(f"[audit] 전체 artists {len(rows)}건 로드 완료")

    # core name -> list of (id, name, richness, has_attr)
    groups: dict[str, list[tuple[str, str, int, bool]]] = defaultdict(list)
    attr_marked = 0
    for aid, name, artwork_n, holding_n in rows:
        norm = normalize(name)
        core, has_attr = extract_core(norm)
        if not core:
            core = norm
        if has_attr:
            attr_marked += 1
        richness = artwork_n + holding_n
        groups[core].append((str(aid), name, richness, has_attr))

    print(f"[audit] 귀속 수식어가 감지된 artists 행: {attr_marked}건")

    # 같은 core에 2개 이상 행이 있고, 그 중 attribution-qualified가 하나라도 있는 그룹만 리포트
    mixed_groups = {
        core: entries
        for core, entries in groups.items()
        if len(entries) > 1 and any(e[3] for e in entries)
    }
    print(f"[audit] core name 기준 '섞인' 그룹(순수+귀속 또는 귀속 여러 개): {len(mixed_groups)}개")

    # 순수 철자변형 후보: core 문자열이 다르지만 첫 단어가 같고(블로킹) 전체
    # 유사도가 높은 것 — attribution 없는 행끼리만 비교. 예: "rembrandt van rijn"
    # vs "rembrandt van ryn" vs "rembrandt vanryn". O(n^2) 방지를 위해 첫 단어로
    # 먼저 블로킹한다.
    import difflib

    pure_entries: dict[str, list[tuple[str, str, str, int]]] = defaultdict(list)
    for core, entries in groups.items():
        first_word = core.split(" ", 1)[0] if core else ""
        if not first_word:
            continue
        for aid, name, richness, has_attr in entries:
            if not has_attr:
                pure_entries[first_word].append((core, aid, name, richness))

    MAX_BLOCK = 300  # 이보다 큰 블록(흔한 이름 등)은 O(n^2) 비용이 커서 스킵
    skipped_blocks = 0
    spelling_clusters = []
    for first_word, items in pure_entries.items():
        if len(items) < 2:
            continue
        distinct_cores = sorted(set(i[0] for i in items))
        if len(distinct_cores) < 2:
            continue
        if len(distinct_cores) > MAX_BLOCK:
            skipped_blocks += 1
            continue
        seen_cores = set()
        for i, core_a in enumerate(distinct_cores):
            if core_a in seen_cores:
                continue
            cluster_cores = {core_a}
            for core_b in distinct_cores[i + 1:]:
                if difflib.SequenceMatcher(None, core_a, core_b).ratio() >= 0.80:
                    cluster_cores.add(core_b)
            if len(cluster_cores) > 1:
                seen_cores |= cluster_cores
                cluster_items = [it for it in items if it[0] in cluster_cores]
                spelling_clusters.append(cluster_items)

    print(f"[audit] 순수 철자변형 후보 클러스터: {len(spelling_clusters)}개 (스킵된 대형 블록 {skipped_blocks}개, 흔한 이름이라 비용 과다)")

    lines = []
    lines.append("# 귀속 표기 변형(Attribution Variant) 스코프 리포트")
    lines.append("")
    lines.append(f"생성: audit_attribution_variants.py (읽기 전용, DB 변경 없음)")
    lines.append("")
    lines.append(f"- 전체 artists: {len(rows)}건")
    lines.append(f"- 귀속 수식어(attributed to/school of/d'apres/manner of 등)가 감지된 행: {attr_marked}건")
    lines.append(f"- core name이 겹치면서 순수표기+귀속표기(또는 귀속표기 여럿)가 섞인 그룹: {len(mixed_groups)}개")
    lines.append("")
    lines.append("## 분류 원칙")
    lines.append("")
    lines.append("- **귀속 수식어 포함 행은 병합하지 않음** — 원작자 본인/화파/모작/귀속불확실은")
    lines.append("  미술사적으로 실제 다른 카테고리이므로 그대로 별도 artists 행 유지 권장.")
    lines.append("- 순수 철자변형(수식어 없이 이름 철자만 다른 것)만 기존 방식대로 병합 후보.")
    lines.append("- 이 리포트는 두 카테고리를 분류만 하고 **실제 병합은 수행하지 않음**.")
    lines.append("")
    lines.append("## Mixed 그룹 상세 (richness 내림차순 정렬, richness 합 상위 100개)")
    lines.append("")

    def group_total_richness(item):
        core, entries = item
        return sum(e[2] for e in entries)

    top_groups = sorted(mixed_groups.items(), key=group_total_richness, reverse=True)[:100]

    for core, entries in top_groups:
        entries_sorted = sorted(entries, key=lambda e: -e[2])
        lines.append(f"### {core!r} ({len(entries)}건)")
        for aid, name, richness, has_attr in entries_sorted:
            tag = "[귀속표기]" if has_attr else "[순수표기]"
            lines.append(f"- {tag} `{name}` (id={aid}, artworks+holdings={richness})")
        lines.append("")

    lines.append("## 순수 철자변형 후보 (귀속 수식어 없음, richness 합 상위 100개)")
    lines.append("")
    lines.append("병합 후보 — 워커1이 확인 후 기존 방식(merge_accent_variant_dup_artists.py 등)으로 처리 권장.")
    lines.append("")

    def cluster_total_richness(cluster):
        return sum(it[3] for it in cluster)

    top_spelling = sorted(spelling_clusters, key=cluster_total_richness, reverse=True)[:100]
    for cluster in top_spelling:
        cluster_sorted = sorted(cluster, key=lambda it: -it[3])
        core_label = " / ".join(sorted(set(it[0] for it in cluster)))
        lines.append(f"### {core_label!r} ({len(cluster)}건)")
        for core, aid, name, richness in cluster_sorted:
            lines.append(f"- `{name}` (id={aid}, artworks+holdings={richness})")
        lines.append("")

    out_path = os.path.join(os.path.dirname(__file__), "..", "docs", "귀속표기변형_스코프리포트.md")
    out_path = os.path.abspath(out_path)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[audit] 리포트 저장: {out_path}")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
