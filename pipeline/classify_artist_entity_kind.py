"""artists.entity_kind 분류 (2026-09-15 작업분담 §M4, 진단 §3-2-3, 마이그레이션 0007).

행을 지우지 않고 종류만 표시한다. 우선순위(먼저 맞는 규칙이 이김):
  1. anonymous   — anoniem/Unknown/Unidentified/Anonymous, French, 19th century/Master unknown …
  2. attribution — "Attributed to X" / "X (Attributed to)" / "After X" / "D'après X" / "École de X" /
                   "Circle of X" / "Follower of X" / "Workshop of X" / "Manner of X" / "Pupil of X" /
                   "Possibly X" … → attribution_qualifier + 본체 X를 exact/loose 이름으로 찾아 attribution_of
  3. culture     — 국가/민족/지역/시대명 단독("China", "France (Paris)", "Italian 16th Century",
                   "Deutsch 18. Jahrh.", "Chinese Qing Dynasty", "Islamic", "Byzantine" …)
  4. organization — 회사/공방/제작소/출판사/담배회사 등 접미어("& Co.", "Inc.", "Manufactory",
                   "Tobacco Company", "Glassworks", "Design Studio" …) — 단 역할 접두어 "Photographer: X"는
                   merge_role_prefix_artists.py가 먼저 처리했다고 가정
  그 외는 person 유지. 이미 person이 아닌 행은 건드리지 않는다(사람이 수동 지정한 값 보존).
기본 리포트(규칙별 건수·샘플), --apply 시 반영. idempotent.
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter, defaultdict

from artist_merge_util import get_conn, norm_exact, norm_loose

sys.stdout.reconfigure(encoding="utf-8")

# ---------------------------------------------------------------- 1. anonymous
ANON_RE = re.compile(
    r"^(anoniem|anonymous|anonyme|anonym|anonimo|anónimo|anonimous|unknown|unbekannt|unidentified|ubekendt|ukendt|"
    r"okänd|onbekend|artist unknown|artiste inconnu|inconnu|maître anonyme|maitre anonyme|meister unbekannt|"
    r"master unknown|various artists?|miscellaneous|작자 ?미상|작가 ?미상|미상|作者不詳|作者不明|不詳|不明|"
    r"(?:designer|photographer|maker|master|painter|engraver|woodcutter|artist|sculptor|printmaker) (?:unknown|unidentified)|"
    r"(?:[a-z]+ )?(?:unknown|anonymous|unidentified)(?: [a-z]+)? (?:artist|maker|designer|photographer|master|painter|sculptor|craftsman)s?)\b",
    re.I,
)

# ---------------------------------------------------------------- 2. attribution
_Q = {
    "attributed": r"attributed to|attr\.? to|attribué à|attribuée à|zugeschrieben|toegeschreven aan|atribuido a|attribuito a",
    "after": r"after|d'après|d’après|nach|naar|copy after|copie d'après|copia da|kopie nach|copy of",
    "school": r"school of|école de|ecole de|scuola di|schule des|schule von|escuela de|school van|de l'école de|de l’école de",
    "circle": r"circle of|cercle de|umkreis|kreis des|omgeving van|cerchia di",
    "follower": r"follower of|suiveur de|nachfolger|navolger van|seguace di",
    "workshop": r"workshop of|studio of|atelier de|atelier of|werkstatt des|werkstatt von|bottega di|taller de",
    "manner": r"manner of|in the manner of|style of|in the style of|manière de|maniere de|imitator of|imitateur de|genre de|art des|in the taste of",
    "pupil": r"pupil of|élève de|eleve de|student of|schüler des",
    "possibly": r"possibly|probably|formerly attributed to|formerly|questionably|perhaps",
}
ATTR_PREFIX = {k: re.compile(rf"^(?:[A-Za-z ]{{1,25}}:\s*)?(?:{v})\s+(?P<base>.+)$", re.I) for k, v in _Q.items()}
ATTR_SUFFIX = {
    k: re.compile(rf"^(?P<base>.+?)[\s,]*\(\s*(?:{v})(?:\s+le|\s+la)?\s*\)\s*$", re.I) for k, v in _Q.items()
}
ATTR_SUFFIX_WORD = re.compile(r"^(?P<base>.+?)\s+(?:school|skole|schule|werkstatt|workshop|atelier|studio)\s*$", re.I)
ATTR_TRAIL_COMMA = re.compile(r"^(?P<base>.+?),\s*(?:school of|circle of|follower of|workshop of|after|attributed to|manner of)\s*$", re.I)
ATTR_PAREN_WORD = {
    "workshop": re.compile(r"^(?P<base>.+?)\s*\((?:workshop|studio|atelier|værksted|werkstatt|bottega)\)\s*$", re.I),
    "attributed": re.compile(r"^(?P<base>.+?)\s*\((?:attributed|attr\.?|attribué|zugeschrieben|toegeschreven)\)\s*$", re.I),
    "after": re.compile(r"^(?P<base>.+?)\s*\((?:after|d'après|d’après|nach|naar|copy after)\)\s*$", re.I),
}

# ---------------------------------------------------------------- 3. culture
CULTURE_WORDS = (
    "china|chinese|japan|japanese|korea|korean|india|indian|italy|italian|france|french|germany|german|england|english|"
    "britain|british|great britain|united kingdom|netherlands|dutch|holland|flemish|flanders|spain|spanish|greece|greek|"
    "roman|rome|egypt|egyptian|persia|persian|iran|iranian|turkey|turkish|ottoman|russia|russian|america|american|"
    "united states|europe|european|tibet|tibetan|nepal|nepalese|nepali|peru|peruvian|mexico|mexican|byzantine|byzantium|"
    "islamic|africa|african|native american|thai|thailand|siam|vietnam|vietnamese|cambodia|cambodian|khmer|burma|burmese|"
    "myanmar|indonesia|indonesian|java|javanese|bali|balinese|syria|syrian|iraq|iraqi|mesopotamia|mesopotamian|coptic|"
    "etruscan|hellenistic|celtic|viking|scandinavia|scandinavian|sweden|swedish|denmark|danish|norway|norwegian|finland|"
    "finnish|austria|austrian|switzerland|swiss|belgium|belgian|portugal|portuguese|poland|polish|hungary|hungarian|"
    "czech|bohemia|bohemian|moravia|moravian|scotland|scottish|ireland|irish|wales|welsh|australia|australian|canada|"
    "canadian|brazil|brazilian|cuba|cuban|colombia|colombian|argentina|argentine|chile|chilean|venice|venetian|florence|"
    "florentine|siena|sienese|bologna|bolognese|naples|neapolitan|milan|milanese|genoa|genoese|lombardy|umbria|"
    "umbrian|padua|paduan|ferrara|ferrarese|verona|tuscany|tuscan|piedmont|piedmontese|liguria|ligurian|"
    "north italian|south german|north german|north netherlandish|south netherlandish|netherlandish|western european|"
    "eastern european|central european|asia|asian|east asian|south asian|southeast asian|central asian|middle east|"
    "middle eastern|near east|near eastern|north africa|north african|west africa|west african|central africa|"
    "central african|east africa|east african|south africa|south african|oceania|oceanic|polynesia|polynesian|melanesia|"
    "melanesian|micronesia|micronesian|pre-columbian|precolumbian|mesoamerica|mesoamerican|andes|andean|inuit|aboriginal|"
    "maori|aztec|mayan|inca|nazca|olmec|zapotec|mixtec|toltec|qing|meiji|joseon|goryeo|"
    "silla|mughal|rajput|pahari|deccan|safavid|qajar|timurid|mamluk|abbasid|fatimid|seljuk|sasanian|achaemenid|parthian|"
    "qing dynasty|ming dynasty|tang dynasty|song dynasty|yuan dynasty|han dynasty|edo period|meiji period|joseon dynasty|"
    "assyrian|babylonian|sumerian|akkadian|hittite|phoenician|nabataean|minoan|mycenaean|cycladic|attic|corinthian|"
    "apulian|campanian|lucanian|sicilian|sardinian|iberian|visigothic|carolingian|ottonian|romanesque|gothic|"
    "medieval|renaissance|baroque|rococo|neoclassical|miao|hmong|yoruba|edo people|kongo|dogon|bamana|senufo|"
    "asante|ashanti|chokwe|makonde|zulu|ndebele|tibet or nepal|india or pakistan|pakistan|pakistani|afghanistan|"
    "afghan|uzbek|kazakh|mongolia|mongolian|manchu|tibetan or chinese|sri lanka|sinhalese|ceylon|philippines|filipino|"
    "malaysia|malay|singapore|laos|lao|taiwan|taiwanese|hong kong|okinawa|ryukyu|ainu|korea or japan|china or japan"
)
CULTURE_RE = re.compile(
    rf"^(?:{CULTURE_WORDS})(?:\s*\((?:[A-Za-z .'\-]+)\))?(?:\s*,?\s*(?:\d{{1,2}}(?:st|nd|rd|th)\s+century|\d{{1,2}}\.\s*(?:jahrh(?:undert)?\.?|jh\.?)|century|dynasty|period|artist|school|workshop|manufactory|maker|painter|potter|weaver|sculptor|culture|people|tribe))*\s*$",
    re.I,
)
PERIOD_RE = re.compile(
    r"^(?:[A-Za-zÀ-ÿ ,'\-()]+?)\s*,?\s*(?:\d{1,2}(?:st|nd|rd|th)\s+century|\d{1,2}\.\s*(?:jahrh(?:undert)?\.?|jh\.?)|\d{1,2}(?:th|de|e)?\s*(?:eeuw|siècle|secolo|siglo)|[a-z]+ dynasty|qing|ming|edo|joseon|goryeo)(?:\s*(?:artist|school|workshop|maker|painter|period))?\s*$",
    re.I,
)
PERIOD_PERSON_GUARD = re.compile(r"\b(?:born|died|active|fl\.|geb\.|gest\.)\b|\d{4}\s*[-–]\s*\d{4}", re.I)

# ---------------------------------------------------------------- 4. organization
ORG_RE = re.compile(
    r"((?<!\w)(?:inc|ltd|llc|plc|gmbh|s\.p\.a|corp|corporation|company|co\.|& co\b|and co\b|bros\.?|brothers|& sons|and sons|"
    r"& son\b|and son\b|& fils|frères|freres|hermanos|manufactory|manufacture|manufacturing|manufacturers?|factory|"
    r"glassworks|glass works|iron ?works|porcelain|pottery|potteries|ceramics|tobacco|cigarette|chewing gum|gum company|press|"
    r"publishers?|publishing|publications?|verlag|éditions?|editions|editeur|foundry|mills?|studios|design studio|"
    r"workshop|atelier|firm|society|association|guild|institute|agency|bureau|department|ministry|government|army|navy|"
    r"magazine|newspaper|journal|gazette|photo company|photographic company|photographers|lithographic|printing|"
    r"printers|engravers|architects|associates|partners|partnership|group|collective|cooperative|co-operative|"
    r"committee|council|commission|railway|railroad|airlines?|motors|telephone|telegraph|insurance|brewery|distillery|"
    r"winery|hotel|theatre|theater|productions|broadcasting|television|ballet|opera|orchestra|"
    r"academy|college|university|museum|gallery|galerie|library|archive|foundation|fund|trust|church|abbey|"
    r"monastery|convent|temple|mosque|cathedral|hospital|laboratory|observatory|kiln|tapestry works|"
    r"rug company|card company|card co|"
    r"manufactura|fabrik|fabriek|werke|werkstätte|werkstaette|wiener werkstätte|bauhaus)\b\.?)",
    re.I,
)
ORG_GUARD = re.compile(r"^(?:school of|workshop of|studio of|atelier de|atelier of|circle of|follower of|manner of)\b", re.I)
# "Mills, William" / "Bank, Moses" 같은 "성, 이름" 표기는 조직이 아님
LAST_FIRST_RE = re.compile(r"^[A-Za-zÀ-ÿ'\-]{1,30},\s+[A-Za-zÀ-ÿ.\-]{1,20}(?: [A-Za-zÀ-ÿ.\-]{1,20})?$")


def classify(name: str) -> tuple[str, str, str | None, str | None]:
    """(kind, rule, qualifier, base_name)"""
    n = " ".join(name.split())
    if ANON_RE.match(n):
        return "anonymous", "anon-prefix", None, None
    if (
        re.search(r"\b(?:anonymous|anonyme|anoniem|unknown|unidentified|unbekannt|ubekendt|various artists?)\b", n, re.I)
        and not re.search(r"\b(?:after|attributed|société anonyme|societe anonyme)\b", n, re.I)
        and ", " not in n  # "David Burliuk, Unknown artist" 같은 MoMA 병렬 나열은 앞 작가가 실존 → person 유지
    ):
        return "anonymous", "anon-word", None, None
    for q, rx in ATTR_PREFIX.items():
        m = rx.match(n)
        if m:
            return "attribution", f"attr-prefix:{q}", q, m.group("base").strip(" ,;")
    for q, rx in ATTR_SUFFIX.items():
        m = rx.match(n)
        if m:
            return "attribution", f"attr-suffix:{q}", q, m.group("base").strip(" ,;")
    for q, rx in ATTR_PAREN_WORD.items():
        m = rx.match(n)
        if m:
            return "attribution", f"attr-paren:{q}", q, m.group("base").strip(" ,;")
    m = ATTR_TRAIL_COMMA.match(n)
    if m:
        return "attribution", "attr-trailing", "school", m.group("base").strip(" ,;")
    m = ATTR_SUFFIX_WORD.match(n)
    if m and not ORG_GUARD.match(n):
        base = m.group("base").strip(" ,;")
        if re.search(r"(school|skole|schule)$", n, re.I):
            # "Raimondi School" → 귀속(유파). 단 "Prior-Hamblin School"처럼 익명 유파명도 같은 취급
            return "attribution", "attr-suffix-word", "school", base
        # "Saracchi Workshop"/"Silver Studio"/"Bauhaus Workshop" → 공방·스튜디오 = 조직
        return "organization", "org-workshop", None, None
    if CULTURE_RE.match(n):
        return "culture", "culture-word", None, None
    if PERIOD_RE.match(n) and not PERIOD_PERSON_GUARD.search(n) and len(n) < 60:
        return "culture", "culture-period", None, None
    if (
        ORG_RE.search(n) and not ORG_GUARD.match(n)
        and not re.search(r"^[A-Za-z][A-Za-z ]{1,25}:\s", n)
        and not LAST_FIRST_RE.match(n)
    ):
        return "organization", "org-suffix", None, None
    return "person", "", None, None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--sample", type=int, default=12)
    args = ap.parse_args()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("select id::text, name, entity_kind from artists")
    rows = cur.fetchall()
    exact: dict[str, str] = {}
    loose: dict[str, str] = {}
    loose_amb: set[str] = set()
    for aid, name, _ in rows:
        exact.setdefault(norm_exact(name), aid)
        k = norm_loose(name)
        if k in loose and loose[k] != aid:
            loose_amb.add(k)
        loose.setdefault(k, aid)
    cur.execute("select artist_id, count(*) from artworks where artist_id is not null group by 1")
    works = {str(a): c for a, c in cur.fetchall()}

    plan = []  # (aid, kind, rule, qualifier, attribution_of)
    by_rule = Counter()
    works_by_kind = Counter()
    samples = defaultdict(list)
    unresolved_base = Counter()
    for aid, name, kind in rows:
        if kind != "person":
            continue
        k, rule, q, base = classify(name)
        if k == "person":
            continue
        att = None
        if k == "attribution" and base:
            att = exact.get(norm_exact(base))
            if att is None:
                lk = norm_loose(base)
                if lk in loose and lk not in loose_amb:
                    att = loose[lk]
            if att == aid:
                att = None
            if att is None:
                unresolved_base[base] += 1
        plan.append((aid, k, rule, q, att))
        by_rule[(k, rule)] += 1
        works_by_kind[k] += works.get(aid, 0)
        if len(samples[(k, rule)]) < args.sample:
            samples[(k, rule)].append((name, works.get(aid, 0), (base or "")[:40], bool(att)))

    print(f"person 중 재분류 대상 {len(plan)}건")
    for (k, rule), c in sorted(by_rule.items(), key=lambda x: -x[1]):
        print(f"  {k:12} {rule:24} {c:6}")
    print("작품 수 기준:", dict(works_by_kind))
    print(f"attribution 본체 미해결 {sum(unresolved_base.values())}건, 상위: {unresolved_base.most_common(10)}")
    for key, ss in samples.items():
        print(f"\n[{key[0]} / {key[1]}]")
        for s in ss:
            print("   ", s)
    if not args.apply:
        print("\n--apply 없음: 리포트만")
        return
    from psycopg2.extras import execute_values

    execute_values(
        cur,
        """update artists a set entity_kind = v.kind, entity_kind_note = v.rule,
              attribution_qualifier = v.q, attribution_of = v.att::uuid, updated_at = now()
           from (values %s) as v(id, kind, rule, q, att) where a.id = v.id::uuid""",
        plan, page_size=1000,
    )
    conn.commit()
    cur.execute("select entity_kind, count(*) from artists group by 1 order by 2 desc")
    print("결과:", cur.fetchall())


if __name__ == "__main__":
    main()
