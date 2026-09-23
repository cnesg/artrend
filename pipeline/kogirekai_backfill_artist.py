"""古裂會(kogirekai) 낙찰품 11,778건의 artist_id 백필 — 제목 선두 토큰 ↔ authority 정확매칭.

배경
====
`pipeline/kogirekai.py` 로더는 **의도적으로** artist_id=None 으로 적재했다(모듈 docstring 참고).
"伝"(전 ~ 작) 접두어만으로는 "伝来"(가문 전래) 같은 무관한 복합어와 구분할 수 없어 오탐을
피할 수 없다고 판단했기 때문이다. 그 판단 자체는 옳았지만, **판단의 전제가 틀렸다**:

원본 PDF 표는 `番号 / 品名 / 最低価格 / 落札価格` 4열뿐이라 작가 컬럼이 따로 없는 것은
맞다. 그러나 品名 안에서 작가명과 품목명은 **넓은 공백으로 구분**돼 있다
(제135~150회는 U+3000 전각공백, **제132·133회는 U+2003 EM SPACE** — 회차별로 다르다):

    #002 藤原定家　小倉色紙幅          → 작가 "藤原定家" + 품목 "小倉色紙幅"
    #006 伝信實　柿本人麻呂画幅        → 귀속 "伝" + 작가 "信實" + 품목
    #001 春日鹿曼荼羅幅                 → 구분자 없음 = 작가 개념 없는 골동품
    #098 香木                           → 〃

즉 "伝"으로 시작하는 접두어를 보는 대신 **넓은 공백 앞 첫 세그먼트**를 보면 되고, 이것이
로더 docstring이 아쉬워한 "칸옥션의 생몰년 같은 명확한 2차 신호"에 해당한다. 그런데
로더의 `re.sub(r"\\s+", " ", name)` 이 이 공백들을 일반 공백으로 접어버려 DB에는 이 신호가
남아 있지 않다 — 그래서 **DB title이 아니라 raw PDF를 다시 파싱**한다.

두 번째로 발견한 것: pypdf가 뽑은 텍스트에 **康熙부수(Kangxi Radicals, U+2F00~) 코드포인트가
섞여 있다**. 낙찰품 11,778건 중 6,469건(54.9%)이 해당한다.

    ⻫⽩⽯  (U+2EEB U+2F65 U+2F5F)  ≠  齊白石  (U+9F4A U+767D U+77F3)   ← 제백석

눈으로는 같아 보이지만 바이트가 달라 정확매칭이 전부 실패한다. NFKC 정규화로 해소된다
(康熙부수 → 통합한자는 유니코드 표준 호환 분해라 무손실이다). 단 **NFKC는 U+3000도 일반
공백으로 접기 때문에 구분자로 먼저 자른 뒤 세그먼트별로 NFKC를 걸어야 한다** — 순서를
바꾸면 구분자가 사라져 후보가 0건이 된다(실측).

연결 규칙 (추정·유사도·LLM 없음)
================================
이 프로젝트는 결손 메타를 유사도/LLM으로 채우는 것을 금지한다(CLAUDE.md). 여기서도
**문자열 정확일치 + authority ID(Wikidata QID/ULAN)** 만 쓴다. 후보 → 작가 해소 순서:

  1. Wikidata: ja **rdfs:label 정확일치**(별칭 altLabel은 일부러 안 봄) + P31=Q5(사람)
     + P106 직업이 미술 계열. 같은 라벨의 사람이 2명 이상이면 **동명이인 위험 → 보류**.
  2. 얻은 QID로 artists 조회 → 있으면 그 행에 연결(언어를 건너뛴 authority 연결.
     "葛飾北斎" 후보가 DB의 "Hokusai, Katsushika"(Q5586) 행에 붙는 게 이 경로다).
  3. QID로 못 찾으면 artists.name NFKC 정확일치(entity_kind='person', 유일할 때만).
  4. 그래도 없고 Wikidata 검증을 통과했으면 artists 행 신규 생성(QID/ULAN 동반).
  Wikidata에 없고 DB 이름 정확일치만 되는 경우도 3번 규칙으로 연결한다.

직업 필터는 QID 목록을 외워 쓰지 않고 **영문 직업 라벨 키워드 allowlist**(ART_OCC)로 판정한다
(painter/sculptor/calligrapher/potter/printmaker/…). 이것은 동일성 판정이 아니라 범주
필터라 유사도 금지 원칙과 무관하다. 사람이지만 미술 직업이 아닌 경우(예: 徳川慶喜 —
쇼군의 二行書幅처럼 "역사적 인물의 서예"는 작가로 볼지 애매)는 **연결하지 않고 별도
버킷으로 집계만** 한다. `--include-nonart-humans` 로만 포함시킬 수 있다.

"伝X"(전 X 작 = attributed to)는 접두어를 떼고 X로 해소하되 `artworks.attribution_qualifier`
에 '伝'을 남긴다(`mark_getty_attribution.py`의 귀속 한정어 관례와 동일).

사용법
======
    python pipeline/kogirekai_backfill_artist.py --fetch    # Wikidata SPARQL 수집(raw 저장, 재실행시 스킵)
    python pipeline/kogirekai_backfill_artist.py            # 리포트만(기본)
    python pipeline/kogirekai_backfill_artist.py --apply    # 반영
    python pipeline/kogirekai_backfill_artist.py --fix-titles --apply   # 康熙부수 깨짐 title NFKC 교정(별도)

재실행 안전(idempotent): artist_id가 이미 있는 행은 건드리지 않고, artists 신규 생성은
wikidata_qid 유니크 확인 후에만 한다. --fetch 는 already_fetched 로 중복 요청을 막는다.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import importlib.util
import json
import re
import sys
import time
import unicodedata
from pathlib import Path

import requests
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "crawlers"))

from common import already_fetched, save_raw, with_retry  # noqa: E402
from db import get_connection  # noqa: E402

# crawlers/kogirekai.py 와 pipeline/kogirekai.py 가 이름이 같다 — 평범한 import 는
# sys.path 순서에 따라 crawlers 쪽이 이겨서 엉뚱한 모듈을 집는다. 경로로 명시 로드한다.
_spec = importlib.util.spec_from_file_location(
    "kogirekai_loader", Path(__file__).resolve().parent / "kogirekai.py"
)
K = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(K)

sys.stdout.reconfigure(encoding="utf-8")

SITE_NAME = "kogirekai"
WD_SITE = "wikidata_kogirekai_artists"
RAW_PDF = ROOT / "crawlers" / "raw" / SITE_NAME
RAW_WD = ROOT / "crawlers" / "raw" / WD_SITE
SPARQL_URL = "https://query.wikidata.org/sparql"
HEADERS = {"User-Agent": "artgraph-research-bot/1.0 (https://github.com/cnesg/artrend)"}
LICENSE_NOTE = "Wikidata CC0 1.0 (https://www.wikidata.org/wiki/Wikidata:Licensing)"
BATCH = 100

# 미술 계열 직업 판정용 영문 라벨 키워드(동일성 판정 아님 — 범주 필터).
ART_OCC = (
    "painter", "sculptor", "artist", "calligrapher", "potter", "ceramic", "printmaker",
    "engraver", "photographer", "illustrator", "designer", "lacquer", "weaver", "dyer",
    "swordsmith", "architect", "draughtsman", "draftsman", "woodcut", "ukiyo-e",
    "animator", "cartoonist", "goldsmith", "silversmith", "metalsmith", "carver",
    "printer", "bookbinder", "glass", "textile", "master of tea ceremony", "tea master",
    "art collector",
)

# 후보 자리에 오지만 작가가 아닌 것이 명백한 표현(정확일치 게이트로도 걸러지지만 명시).
BLOCKLIST = {
    "無銘", "無地", "無款", "作者不詳", "伝来", "不詳", "一括", "其他", "他",
}

ATTRIB_PREFIX_RE = re.compile(r"^(伝|傳)\s*")
# 후보로 받아들일 최소 형태: 한자/가나/반복기호로만 이루어진 2~12자.
# 々(U+3005 반복기호)를 빠뜨리면 野々村仁清·柳々居辰斎·藪内休々斎 같은 실존 작가가
# 통째로 탈락한다(실측 2026-09-23: 이것만으로 30여 건 유실).
CAND_RE = re.compile(
    r"^[一-鿿㐀-䶿぀-ゟ゠-ヿ"
    r"ー・々〆·]{2,12}$"
)

# pypdf 텍스트에 섞이는 **CJK Radicals Supplement(U+2E80~U+2EFF)** 는 NFKC로 안 풀린다.
# 康熙부수(U+2F00~)는 호환분해가 있어 NFKC가 처리하지만, 이 블록은 표준 분해가 아예
# 없어서 그대로 남는다(실측: U+2EEB ⻫ 는 NFKC 후에도 U+2EEB). 결과적으로 "⻫白石"이
# "斉白石"과 바이트가 달라 정확매칭이 조용히 실패한다. 부수 → 통상 자형 대응은 1:1로
# 확정적이라(유사도 추정이 아니다) 표로 둔다. kogirekai raw 에 실제로 나타난 10자 전부.
RADICAL_SUPPLEMENT = {
    "⻘": "青", "⻑": "長", "⻄": "西", "⻩": "黄", "⺠": "民",
    "⻲": "亀", "⻁": "虎", "⻫": "斉", "⺟": "母", "⻭": "歯",
}
RADICAL_RE = re.compile("[" + "".join(RADICAL_SUPPLEMENT) + "]")

QUERY = """
SELECT ?ja ?item ?en ?ulan ?born ?died
       (GROUP_CONCAT(DISTINCT ?occLabel; separator="|") AS ?occs) WHERE {{
  VALUES ?ja {{ {values} }}
  ?item rdfs:label ?ja . FILTER(LANG(?ja) = "ja")
  ?item wdt:P31 wd:Q5 .
  OPTIONAL {{ ?item rdfs:label ?en FILTER(LANG(?en) = "en") }}
  OPTIONAL {{ ?item wdt:P245 ?ulan }}
  OPTIONAL {{ ?item wdt:P569 ?born }}
  OPTIONAL {{ ?item wdt:P570 ?died }}
  OPTIONAL {{ ?item wdt:P106 ?occ . ?occ rdfs:label ?occLabel FILTER(LANG(?occLabel) = "en") }}
}} GROUP BY ?ja ?item ?en ?ulan ?born ?died
"""

# ---------------------------------------------------------------- 무명 골동품 분류
# "작가 개념이 없는 게 정상"인 카테고리. 구분자 없는 품명에 이 키워드가 있으면
# artist_id NULL 이 결손이 아니라 정상이라는 근거로 집계한다(연결 판단에는 안 씀).
ANON_CATEGORIES = {
    "불상·불교조각": ("佛", "仏", "菩薩", "観音", "如来", "明王", "天部", "曼荼羅", "厨子",
                      "舎利", "経", "梵鐘", "地蔵", "羅漢", "尊", "神像", "狛犬"),
    "갑주·무구": ("具足", "兜", "甲冑", "鎧", "陣羽織", "旗指物", "馬具", "鞍", "鐙"),
    "도검·도장구": ("鐔", "鍔", "小柄", "笄", "目貫", "刀装", "拵", "鞘", "刀", "脇差",
                    "槍", "薙刀", "鉄砲"),
    "석조·비석": ("板碑", "石碑", "石造", "石仏", "灯籠", "石塔", "五輪塔", "磨崖"),
    "다도구": ("茶碗", "茶入", "水指", "棗", "茶杓", "釜", "炉縁", "建水", "香合", "花入",
               "天目", "茶器", "急須", "煎茶"),
    "도자기": ("皿", "鉢", "壺", "徳利", "瓶", "碗", "猪口", "香炉", "染付", "青磁", "白磁",
               "織部", "志野", "備前", "唐津", "伊万里", "九谷", "瀬戸"),
    "칠기·공예": ("蒔絵", "漆", "螺鈿", "根来", "堆朱", "印籠", "重箱", "膳", "盆", "櫃",
                  "簞笥", "箱"),
    "염직·복식": ("裂", "唐織", "打掛", "小袖", "袈裟", "帯", "更紗", "絞", "刺繍", "能装束",
                  "襦袢", "羽織"),
    "고문서·전적": ("文書", "書状", "消息", "古文書", "折本", "巻物", "断簡", "版本", "写本",
                    "絵図", "地図", "証文"),
    "금工·기타": ("銅", "金銅", "鉄地", "鍍金", "根付", "煙管", "簪", "鏡", "燭台", "香木",
                  "玉", "翡翠", "硯", "墨", "筆"),
}


# ------------------------------------------------------------------------ 파싱
def nfkc(s: str) -> str:
    """NFKC + CJK Radicals Supplement 치환. 둘 다 해야 정확매칭이 성립한다."""
    return RADICAL_RE.sub(lambda m: RADICAL_SUPPLEMENT[m.group()],
                          unicodedata.normalize("NFKC", s))


# 작가/품목 구분자로 쓰이는 넓은 공백. 회차마다 다르다 — 제135~150회는 U+3000(전각),
# **제132·133회는 U+2003(EM SPACE)을 쓴다**(실측 2026-09-23: 132회 694건 중 368건이 U+2003,
# U+3000은 1건뿐). NFKC가 이 둘을 모두 일반 공백으로 접어버리므로 U+2003을 빼먹으면 그
# 두 회차의 작가 표기가 통째로 "구분자 없음"으로 오분류된다.
# 반면 ASCII U+0020(154회 출현)은 구분자가 아니라 PDF 줄바꿈 아티팩트라 일부러 제외한다.
SEPARATOR_RE = re.compile(r"[　   -  ]+")


def segments(name: str) -> list[str]:
    """品名을 넓은 공백 기준으로 자르고 세그먼트별 NFKC.

    NFKC가 U+3000/U+2003을 일반 공백으로 접으므로 **자르기 → 정규화** 순서가 중요하다.
    순서를 바꾸면 구분자가 사라져 후보가 0건이 된다(실측).
    """
    name = re.sub(r"[ \t\r\n ]+", " ", name)
    return [p for p in (nfkc(x).strip() for x in SEPARATOR_RE.split(name)) if p]


def parse_raw_items() -> list[dict]:
    """raw PDF를 다시 파싱해 낙찰품 목록을 (회차, 로트, 세그먼트) 형태로 돌려준다."""
    out: list[dict] = []
    for pdf in sorted(RAW_PDF.glob("result_*.pdf")):
        rnd = int(pdf.stem.split("_")[1])
        text = "\n".join(p.extract_text() or "" for p in PdfReader(str(pdf)).pages)
        cleaned = K.TITLE_LINE_RE.sub(" ", K.HEADER_NOISE_RE.sub(" ", text))
        date = K._parse_date(text)
        for lot, name, _lo, hammer in K.ITEM_RE.findall(cleaned):
            if not hammer:  # 유찰 — 애초에 적재되지 않았다
                continue
            segs = segments(name)
            if segs:
                out.append({"round": rnd, "lot": lot, "date": date, "segs": segs,
                            "title": " ".join(segs)})
    return out


def candidate_of(segs: list[str]) -> tuple[str | None, str | None]:
    """(작가후보, 귀속한정어) — 후보가 아니면 (None, None)."""
    if len(segs) < 2:
        return None, None  # 구분자 없음 = 작가 표기 없음
    # 세그먼트 안쪽의 ASCII 공백은 PDF 줄바꿈 아티팩트다("木庵性 瑫" → 木庵性瑫).
    # 진짜 작가/품목 구분자는 U+3000 이고 그건 이미 잘라냈으므로 여기서는 제거해도 안전.
    head = segs[0].replace(" ", "")
    m = ATTRIB_PREFIX_RE.match(head)
    qualifier = None
    if m:
        qualifier, head = "伝", head[m.end():].strip()
    if not head or head in BLOCKLIST or not CAND_RE.match(head):
        return None, None
    return head, qualifier


def anon_category(title: str) -> str | None:
    for cat, keys in ANON_CATEGORIES.items():
        if any(k in title for k in keys):
            return cat
    return None


# -------------------------------------------------------------------- Wikidata
def sparql(query: str) -> list[dict]:
    def _do():
        r = requests.get(SPARQL_URL, params={"query": query, "format": "json"},
                         headers=HEADERS, timeout=180)
        if r.status_code == 429:
            time.sleep(int(r.headers.get("Retry-After", "15")))
            raise RuntimeError("429 rate limited")
        r.raise_for_status()
        return [{k: v.get("value") for k, v in b.items()}
                for b in r.json()["results"]["bindings"]]
    return with_retry(_do)


def fetch_wikidata(names: list[str], limit: int | None) -> None:
    batches = [names[i:i + BATCH] for i in range(0, len(names), BATCH)]
    print(f"[{WD_SITE}] 후보 {len(names)}개 → 배치 {len(batches)}개")
    done = skipped = 0
    for i, batch in enumerate(batches[:limit] if limit else batches):
        key = f"b{i:04d}_" + hashlib.md5("|".join(batch).encode()).hexdigest()[:8]
        if already_fetched(WD_SITE, key):
            skipped += 1
            continue
        values = " ".join('"' + n.replace('"', "") + '"@ja' for n in batch)
        rows = sparql(QUERY.format(values=values))
        save_raw(WD_SITE, key, json.dumps({"names": batch, "rows": rows}, ensure_ascii=False),
                 url=SPARQL_URL, license_note=LICENSE_NOTE)
        done += 1
        print(f"  배치 {i + 1}/{len(batches)} — 응답 {len(rows)}행")
        time.sleep(1.2)
    print(f"[{WD_SITE}] 저장 {done}, 이미있음 {skipped}")


def load_wikidata() -> dict[str, list[dict]]:
    by_name: dict[str, list[dict]] = collections.defaultdict(list)
    if not RAW_WD.exists():
        return by_name
    for fp in sorted(RAW_WD.glob("*.json")):
        if fp.name.endswith(".meta.json"):
            continue
        for r in json.loads(fp.read_text(encoding="utf-8"))["rows"]:
            by_name[nfkc(r["ja"])].append(r)
    # 같은 배치를 여러 번 받았을 수 있으니 QID로 중복 제거
    return {k: list({r["item"]: r for r in v}.values()) for k, v in by_name.items()}


def is_art_occupation(row: dict) -> bool:
    occs = (row.get("occs") or "").lower()
    return any(k in occs for k in ART_OCC)


def qid_of(row: dict) -> str:
    return row["item"].rsplit("/", 1)[-1]


def year_of(v: str | None) -> int | None:
    if v and len(v) >= 4 and v[:4].isdigit():
        y = int(v[:4])
        return y if 1 <= y <= 2100 else None
    return None


# ------------------------------------------------------------------------ main
def main() -> None:
    ap = argparse.ArgumentParser(description="kogirekai artist_id 백필")
    ap.add_argument("--fetch", action="store_true", help="Wikidata SPARQL 수집만")
    ap.add_argument("--apply", action="store_true", help="DB 반영(기본은 리포트)")
    ap.add_argument("--limit", type=int, help="--fetch 시 배치 수 제한")
    ap.add_argument("--sample", type=int, default=25, help="리포트 표본 개수")
    ap.add_argument("--include-nonart-humans", action="store_true",
                    help="미술 직업이 아닌 실존 인물(쇼군 서예 등)도 연결")
    ap.add_argument("--fix-titles", action="store_true",
                    help="康熙부수 깨짐 artworks.title 을 NFKC로 교정(별도 작업)")
    args = ap.parse_args()

    items = parse_raw_items()
    print(f"raw PDF 재파싱: 낙찰품 {len(items)}건\n")

    if args.fetch:
        # DB 없이도 도는 경로 — 후보 이름만 뽑아 Wikidata에 묻는다.
        names = sorted({c for c, _q in (candidate_of(it["segs"]) for it in items) if c})
        fetch_wikidata(names, args.limit)
        return

    conn = get_connection()
    cur = conn.cursor()

    # ---- DB 대조: (auction_date, lot_number) → artwork
    cur.execute("""
        select a.auction_date, al.lot_number, aw.id::text, aw.title, aw.artist_id
        from auctions a
        join auction_houses h on a.auction_house_id = h.id
        join auction_lots al on al.auction_id = a.id
        join artworks aw on al.artwork_id = aw.id
        where h.name = %s
    """, (K.HOUSE_NAME,))
    db_rows = cur.fetchall()
    # 대조 키는 (경매일, 로트번호, NFKC(title)) 3중 — 로트번호만으로는 안 된다.
    # 로더 ITEM_RE 가 접두어를 버리고 숫자만 lot_number 로 저장해서 같은 회차의
    # "#001" 과 "A-001" 이 둘 다 "001" 로 들어가 충돌한다(실측: 11,778건 중 9,457건 충돌).
    # title 까지 넣으면 11,778건이 1:1로 정확히 대응한다(실측, 중복·누락 0).
    db_by_key: dict[tuple, list] = collections.defaultdict(list)
    for date, lot, aid, title, artist_id in db_rows:
        db_by_key[(str(date) if date else None, lot, nfkc(title))].append(
            (aid, title, artist_id))
    print(f"DB 대조 대상: kogirekai 낙찰 로트 {len(db_rows)}건 "
          f"(artist_id 이미 있음 {sum(1 for r in db_rows if r[4])}건)")

    if args.fix_titles:
        fix = [(nfkc(t), aid) for _d, _l, aid, t, _a in db_rows if nfkc(t) != t]
        print(f"\n[--fix-titles] 康熙부수 등 NFKC로 바뀌는 title: {len(fix)}건 / {len(db_rows)}")
        for new, aid in fix[:args.sample]:
            old = next(t for _d, _l, a, t, _ in db_rows if a == aid)
            print(f"   {old}  ->  {new}")
        if args.apply:
            cur.executemany("update artworks set title=%s, updated_at=now() where id=%s", fix)
            conn.commit()
            print(f"[--fix-titles] {len(fix)}건 반영")
        else:
            print("[--fix-titles] --apply 없음: 리포트만")
        return

    # ---- 후보 추출 + 분류
    wd = load_wikidata()
    if not wd:
        print("\n주의: Wikidata raw 가 없다 — 먼저 `--fetch` 를 돌려라. "
              "지금은 DB 이름 정확일치만으로 판정한다.\n")

    cur.execute("select name, id::text, entity_kind, wikidata_qid from artists "
                "where name ~ '[一-鿿぀-ヿ]'")
    db_by_name: dict[str, list] = collections.defaultdict(list)
    for name, aid, kind, qid in cur.fetchall():
        db_by_name[nfkc(name)].append((aid, kind, qid))
    cur.execute("select wikidata_qid, id::text from artists where wikidata_qid is not null")
    db_by_qid = dict(cur.fetchall())

    stats: collections.Counter = collections.Counter()
    anon_stats: collections.Counter = collections.Counter()
    plan: list[tuple] = []           # (artwork_id, artist_id|None, qid|None, cand, qualifier)
    new_artists: dict[str, dict] = {}  # qid -> row
    buckets: dict[str, list] = collections.defaultdict(list)
    unmatched: collections.Counter = collections.Counter()

    for it in items:
        keys = db_by_key.get((it["date"], it["lot"], it["title"]), [])
        if not keys:
            stats["DB 대조 실패"] += 1
            continue
        if len(keys) > 1:  # 같은 세일에 같은 로트번호가 둘 — 안전하게 보류
            stats["로트 중복(보류)"] += 1
            continue
        artwork_id, db_title, existing = keys[0]
        if existing:
            stats["이미 연결됨(건드리지 않음)"] += 1
            continue

        cand, qualifier = candidate_of(it["segs"])
        if not cand:
            cat = anon_category(it["title"])
            stats["작가표기 없음"] += 1
            anon_stats[cat or "(분류 미상)"] += 1
            if cat:
                buckets["anon"].append((it["title"], cat))
            else:
                buckets["anon_unclassified"].append((it["title"], None))
            continue

        rows = wd.get(cand, [])
        art_rows = [r for r in rows if is_art_occupation(r)]
        use = art_rows if art_rows else (rows if args.include_nonart_humans else [])

        if len(use) > 1:
            stats["동명이인 모호(보류)"] += 1
            buckets["ambiguous"].append((cand, [r.get("en") for r in use][:4]))
            continue

        if len(use) == 1:
            row = use[0]
            qid = qid_of(row)
            target = db_by_qid.get(qid)
            if target:
                stats["연결: Wikidata QID → 기존 artists"] += 1
            else:
                exact = [x for x in db_by_name.get(cand, []) if x[1] == "person"]
                if len(exact) == 1:
                    target = exact[0][0]
                    stats["연결: Wikidata 검증 + DB 이름 정확일치"] += 1
                elif len(exact) > 1:
                    stats["DB 동명이인 모호(보류)"] += 1
                    buckets["ambiguous"].append((cand, ["DB 내 동명 %d건" % len(exact)]))
                    continue
                else:
                    new_artists[qid] = {
                        "name": cand, "en": row.get("en"), "ulan": row.get("ulan"),
                        "born": year_of(row.get("born")), "died": year_of(row.get("died")),
                    }
                    stats["연결: artists 신규 생성(Wikidata 검증)"] += 1
            plan.append((artwork_id, target, qid, cand, qualifier))
            buckets["linked"].append((cand, qualifier, row.get("en"), qid, db_title))
            continue

        # Wikidata 미검증 — DB 이름 정확일치만 있는 경우
        exact = [x for x in db_by_name.get(cand, []) if x[1] == "person"]
        if len(exact) == 1:
            plan.append((artwork_id, exact[0][0], None, cand, qualifier))
            stats["연결: DB 이름 정확일치(Wikidata 미검증)"] += 1
            buckets["linked_dbonly"].append((cand, qualifier, db_title))
        elif len(exact) > 1:
            stats["DB 동명이인 모호(보류)"] += 1
        elif rows:
            stats["사람이지만 미술 직업 아님(보류)"] += 1
            buckets["nonart"].append((cand, rows[0].get("en"), rows[0].get("occs")))
            unmatched[cand] += 1
        else:
            stats["authority 미발견(한계)"] += 1
            unmatched[cand] += 1

    # ------------------------------------------------------------------ 리포트
    n = len(items)
    print("\n" + "=" * 72)
    print("분류 집계")
    print("=" * 72)
    for k, v in stats.most_common():
        print(f"  {v:6d}  ({v / n * 100:5.1f}%)  {k}")

    print("\n" + "-" * 72)
    print("작가표기 없음(구분자 없는 품명) — 카테고리별")
    print("-" * 72)
    tot_anon = sum(anon_stats.values())
    for k, v in anon_stats.most_common():
        print(f"  {v:6d}  ({v / max(tot_anon, 1) * 100:5.1f}% of 무표기)  {k}")

    def show(title, rows, fmt):
        print(f"\n-- {title} (표본 {min(len(rows), args.sample)}/{len(rows)}) --")
        for r in rows[:args.sample]:
            print("   " + fmt(r))

    show("연결 예정(Wikidata 검증)", buckets["linked"],
         lambda r: f"{r[0]}{' [伝]' if r[1] else ''}  ({r[2]}, {r[3]})   ← {r[4]}")
    show("연결 예정(DB 이름 정확일치만)", buckets["linked_dbonly"],
         lambda r: f"{r[0]}{' [伝]' if r[1] else ''}   ← {r[2]}")
    show("보류: 동명이인 모호", buckets["ambiguous"], lambda r: f"{r[0]}  후보={r[1]}")
    show("보류: 사람이지만 미술 직업 아님", buckets["nonart"],
         lambda r: f"{r[0]}  ({r[1]})  직업={r[2]}")
    show("무명 골동품(정상)", buckets["anon"], lambda r: f"[{r[1]}] {r[0]}")
    show("무표기 + 카테고리 미분류", buckets["anon_unclassified"], lambda r: r[0])

    print(f"\n-- authority 미발견 상위 후보 (한계, 총 {len(unmatched)}종) --")
    for k, v in unmatched.most_common(args.sample):
        print(f"   {v:4d}  {k}")

    # --------------------------------------------------- 3구간 요약(핵심 결론)
    # 구간 나누는 기준은 내 키워드 추측이 아니라 **원본이 스스로 남긴 신호**다:
    # 品名에 넓은 공백 구분자가 있으면 그 회차 편집자가 작가를 적은 것이고, 없으면
    # 작가 표기 자체를 하지 않은 것이다. 그래서 B는 "결손"이 아니라 정상값이다.
    tier_a = len(plan)
    tier_b = stats["작가표기 없음"]
    tier_c = n - tier_a - tier_b - stats["이미 연결됨(건드리지 않음)"] \
        - stats["DB 대조 실패"] - stats["로트 중복(보류)"]
    print("\n" + "=" * 72)
    print("3구간 요약 (전체 %d건 기준)" % n)
    print("=" * 72)
    print(f"  A. 작가 연결 복구        {tier_a:6d}  ({tier_a / n * 100:5.1f}%)")
    print(f"  B. 원래 작가 없음(정상)  {tier_b:6d}  ({tier_b / n * 100:5.1f}%)"
          "   ← 원본 品名에 구분자 자체가 없음 = 소스가 작가를 안 적음")
    print(f"  C. 작가 있으나 미해소    {tier_c:6d}  ({tier_c / n * 100:5.1f}%)"
          "   ← 구분자는 있는데 authority 정확매칭 실패")
    for k in ("authority 미발견(한계)", "사람이지만 미술 직업 아님(보류)",
              "동명이인 모호(보류)", "DB 동명이인 모호(보류)"):
        if stats[k]:
            print(f"        - {k}: {stats[k]}")

    print(f"\n연결 예정 작품 {len(plan)}건 / artists 신규 생성 예정 {len(new_artists)}명")

    if not args.apply:
        print("\n--apply 없음: 리포트만. 표본 검수 후 --apply 로 반영하라.")
        return

    # -------------------------------------------------------------------- 반영
    created = 0
    for qid, info in new_artists.items():
        # 동시에 도는 다른 세션이 같은 QID를 만들었을 수 있어 매번 재확인(idempotent)
        cur.execute("select id::text from artists where wikidata_qid = %s", (qid,))
        got = cur.fetchone()
        if got:
            db_by_qid[qid] = got[0]
            continue
        cur.execute("""
            insert into artists (name, name_en, birth_year, death_year, entity_kind,
                                 wikidata_qid, ulan_id, authority_source, created_at, updated_at)
            values (%s, %s, %s, %s, 'person', %s, %s, 'wikidata_ja_label', now(), now())
            returning id::text
        """, (info["name"], info["en"], info["born"], info["died"], qid, info["ulan"]))
        db_by_qid[qid] = cur.fetchone()[0]
        created += 1

    updates = []
    for artwork_id, artist_id, qid, _cand, qualifier in plan:
        target = artist_id or db_by_qid.get(qid)
        if target:
            updates.append((target, qualifier, artwork_id))
    # artist_id is null 조건으로 재실행 안전 보장
    cur.executemany("""
        update artworks
           set artist_id = %s,
               attribution_qualifier = coalesce(attribution_qualifier, %s),
               updated_at = now()
         where id = %s and artist_id is null
    """, updates)
    conn.commit()
    print(f"\n반영 완료: artists 신규 {created}명, artworks.artist_id {len(updates)}건 갱신")


if __name__ == "__main__":
    main()
