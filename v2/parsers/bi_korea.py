"""
parsers_korea.py -- main-exhibition artist-list parsers for Korean biennales, 2016-2026.

Covers:
  * Gwangju Biennale        (gwangjubiennale.org official archive)        gwangju_2016 .. gwangju_2026
  * Busan Biennale          (busanbiennale.org archive, busanbiennale2026.com) busan_2016 .. busan_2026
  * Seoul Mediacity Biennale (sema.seoul.go.kr -- the organiser's site; the
    biennale microsite mediacityseoul.kr is robots-disallowed and is NOT used)
                                                                             seoul_mediacity_2016 .. _2025

Contract
--------
* Every ``parse_<edition_id>(text)`` takes the raw text of ONE fetched page and
  returns ``list[dict]``.  Dicts always carry the public keys
  ``name, name_ko, name_en, country, birth_year`` (None when the page does not
  give it) and may carry extra keys (``section``, ``role``, ``slug`` ...).
  Keys starting with ``_`` are join helpers and are stripped by ``finalize``.
* Several editions need more than one page (ko + en, pagination, an exclusion
  tab).  ``EDITION_SOURCES[edition_id]`` lists every URL in fetch order; the
  crawler applies ``parser`` to each page's text, then passes the list of
  per-page results (same order as ``urls``) to ``combine`` (default:
  ``combine_concat``).  ``run_edition(edition_id, get_text)`` does exactly that.
* ``name`` = English name when known, else the Korean name.
* Only stdlib + beautifulsoup4 + lxml are needed.

Fetch notes: www.busanbiennale.org currently serves an untrusted TLS chain;
the archive answers on plain http://, which is what the URLs below use.
"""
from __future__ import annotations

import difflib
import re
import unicodedata
from typing import Callable, Iterable

from bs4 import BeautifulSoup

# --------------------------------------------------------------------------
# generic helpers
# --------------------------------------------------------------------------
HANGUL_RE = re.compile(r"[\uac00-\ud7a3]")
LATIN_RE = re.compile(r"[A-Za-z\u00c0-\u024f]")
PUBLIC_KEYS = ("name", "name_ko", "name_en", "country", "birth_year")


def clean(s: str | None) -> str | None:
    if s is None:
        return None
    s = s.replace("\xa0", " ").replace("\u200b", "").replace("\ufeff", "")
    s = re.sub(r"\s+", " ", s).strip()
    return s or None


def has_hangul(s: str | None) -> bool:
    return bool(s and HANGUL_RE.search(s))


def norm_key(s: str | None) -> str:
    """Accent/space/punctuation-insensitive key for de-duplication."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = unicodedata.normalize("NFC", "".join(c for c in s if not unicodedata.combining(c)))  # re-compose Hangul
    return re.sub(r"[^0-9a-z\uac00-\ud7a3]+", "", s.lower())


def split_ko_en(s: str) -> tuple[str | None, str | None]:
    """'강서경 Suki Seokyeong Kang' -> ('강서경', 'Suki Seokyeong Kang').

    Splits after the last Hangul syllable (plus any closing brackets/quotes
    that follow it).  Works for 'R.I.P. 제르메인 R.I.P. Germain',
    '5D (쌔미리, 마크 로우, 사라 신) 5D (Sammy Lee, ...)', etc.
    """
    s = clean(s) or ""
    idx = [m.end() for m in HANGUL_RE.finditer(s)]
    if not idx:
        return None, (s or None)
    j = idx[-1]
    while j < len(s) and s[j] in ")]}\"'”’》>":
        j += 1
    return clean(s[:j]), clean(s[j:])


def make_artist(name_ko=None, name_en=None, country=None, birth_year=None, **extra) -> dict:
    name_ko, name_en, country = clean(name_ko), clean(name_en), clean(country)
    rec = {
        "name": name_en or name_ko,
        "name_ko": name_ko,
        "name_en": name_en,
        "country": country,
        "birth_year": birth_year,
    }
    for k, v in extra.items():
        if v is not None:
            rec[k] = v
    return rec


def _merge_into(a: dict, b: dict) -> None:
    """Fill missing fields of ``a`` from ``b``; union list-valued extras."""
    for k, v in b.items():
        if v is None:
            continue
        if a.get(k) is None:
            a[k] = v
        elif isinstance(a[k], list) and isinstance(v, list):
            for x in v:
                if x not in a[k]:
                    a[k].append(x)
    a["name"] = a.get("name_en") or a.get("name_ko")


def dedupe(artists: Iterable[dict]) -> list[dict]:
    """Merge records that share a normalised ko or en name (order kept)."""
    out: list[dict] = []
    by_key: dict[str, dict] = {}
    for rec in artists:
        keys = [k for k in (("ko:" + norm_key(rec.get("name_ko"))) if rec.get("name_ko") else None,
                            ("en:" + norm_key(rec.get("name_en"))) if rec.get("name_en") else None) if k]
        hit = next((by_key[k] for k in keys if k in by_key), None)
        if hit is None:
            hit = dict(rec)
            out.append(hit)
        else:
            _merge_into(hit, rec)
        for k in (("ko:" + norm_key(hit.get("name_ko"))) if hit.get("name_ko") else None,
                  ("en:" + norm_key(hit.get("name_en"))) if hit.get("name_en") else None):
            if k:
                by_key[k] = hit
    return out


def finalize(artists: Iterable[dict]) -> list[dict]:
    """Drop internal ``_`` keys, recompute ``name``, de-duplicate."""
    res = []
    for a in artists:
        b = {k: v for k, v in a.items() if not k.startswith("_")}
        for k in ("name_ko", "name_en"):
            if b.get(k) and b[k].endswith("?"):  # data-entry doubt mark in the source DB
                b[k] = b[k].rstrip("?").strip()
                b["source_note"] = f"trailing '?' removed from {k}"
        b["name"] = b.get("name_en") or b.get("name_ko")
        res.append(b)
    return dedupe(res)


def combine_concat(per_page: list[list[dict]]) -> list[dict]:
    return finalize(x for page in per_page for x in page)


def split_top_level(s: str, seps: str = ",") -> list[str]:
    """Split on separators that are not inside (), [], <>, 《》."""
    out, buf, depth = [], [], 0
    for ch in s:
        if ch in "([<《〈":
            depth += 1
        elif ch in ")]>》〉":
            depth = max(0, depth - 1)
        if ch in seps and depth == 0:
            out.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    out.append("".join(buf))
    return [x for x in (clean(p) for p in out) if x]


def _balance_parens(s: str) -> str:
    """Remove unmatched closing brackets (e.g. a stray ')' typo on the page)."""
    res, depth = [], 0
    for ch in s:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            if depth == 0:
                continue
            depth -= 1
        res.append(ch)
    return clean("".join(res)) or ""


# --------------------------------------------------------------------------
# cross-lingual matcher (Korean transliteration <-> English) for lists that
# have no shared key.  Revised-Romanization per syllable + consonant skeleton.
# --------------------------------------------------------------------------
_INI = ["g", "kk", "n", "d", "tt", "r", "m", "b", "pp", "s", "ss", "", "j", "jj", "ch", "k", "t", "p", "h"]
_MED = ["a", "ae", "ya", "yae", "eo", "e", "yeo", "ye", "o", "wa", "wae", "oe", "yo", "u", "wo", "we", "wi",
        "yu", "eu", "ui", "i"]
_FIN = ["", "k", "k", "k", "n", "n", "n", "t", "l", "k", "m", "l", "l", "l", "p", "l", "m", "p", "p", "t",
        "t", "ng", "t", "t", "k", "t", "p", "t"]


def romanize_hangul(s: str) -> str:
    out = []
    for ch in s:
        o = ord(ch)
        if 0xAC00 <= o <= 0xD7A3:
            o -= 0xAC00
            out.append(_INI[o // 588] + _MED[(o % 588) // 28] + _FIN[o % 28])
        else:
            out.append(ch)
    return "".join(out)


def _skeleton(s: str) -> str:
    """Consonant skeleton with coarse phonetic classes (P,K,T,S,L,M,N)."""
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.replace("ph", "f").replace("ck", "k").replace("ng", "n")
    s = re.sub(r"(tch|ch|sh|zh|ts|tz|c(?=[eiy]))", "S", s)
    s = re.sub(r"[sxzjç]", "S", s)
    s = re.sub(r"[bpfvw]", "P", s)
    s = re.sub(r"[gkqc]", "K", s)
    s = re.sub(r"[dt]", "T", s)
    s = re.sub(r"[rl]", "L", s)
    s = re.sub(r"[^SPKTLmn]", "", s).upper()
    return re.sub(r"(.)\1+", r"\1", s)


def _tokens(s: str) -> list[str]:
    return [t for t in re.split(r"[\s,&+/()\-\u2013.\u00b7]+|\band\b|\bwith\b", s) if t]


def _strip_paren(s: str) -> str:
    t = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", s)
    return clean(t) or s


def _ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio() if a and b else 0.0


def _pair_score(ko: str, en: str) -> float:
    """Similarity of a Hangul transliteration and a Latin-script name (0..1).

    Combines a coarse consonant-skeleton ratio (robust to transliteration
    vowels) with a full-letter romanisation ratio (discriminates short names),
    each also computed on alphabetically sorted tokens (family-name order).
    A spaceless 2-4 syllable Korean name is also tried as family + given name.
    """
    ko, en = _strip_paren(ko), _strip_paren(en)
    variants = [_tokens(romanize_hangul(ko))]
    if re.fullmatch(r"[가-힣]{2,4}", ko):
        variants.append([romanize_hangul(ko[0]), romanize_hangul(ko[1:])])
    et = _tokens(en)
    e_sk, e_full = _skeleton("".join(et)), norm_key("".join(et))
    e_sk_s = "".join(sorted(_skeleton(t) for t in et))
    e_full_s = "".join(sorted(norm_key(t) for t in et))
    best_sk = best_full = 0.0
    for kt in variants:
        best_sk = max(best_sk, _ratio(_skeleton("".join(kt)), e_sk),
                      _ratio("".join(sorted(_skeleton(t) for t in kt)), e_sk_s))
        best_full = max(best_full, _ratio(norm_key("".join(kt)), e_full),
                        _ratio("".join(sorted(norm_key(t) for t in kt)), e_full_s))
    return 0.6 * best_sk + 0.4 * best_full


def _hungarian_max(score: list[list[float]]) -> list[int]:
    """Optimal 1:1 assignment maximising total score (rows <= cols).
    Returns col index per row.  O(n^2 m), pure Python (e-maxx potentials)."""
    n, m = len(score), len(score[0])
    INF = float("inf")
    u, v = [0.0] * (n + 1), [0.0] * (m + 1)
    p, way = [0] * (m + 1), [0] * (m + 1)
    for i in range(1, n + 1):
        p[0], j0 = i, 0
        minv, used = [INF] * (m + 1), [False] * (m + 1)
        while True:
            used[j0] = True
            i0, delta, j1 = p[j0], INF, 0
            for j in range(1, m + 1):
                if not used[j]:
                    cur = (1.0 - score[i0 - 1][j - 1]) - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j], way[j] = cur, j0
                    if minv[j] < delta:
                        delta, j1 = minv[j], j
            for j in range(m + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break
    res = [-1] * n
    for j in range(1, m + 1):
        if p[j]:
            res[p[j] - 1] = j - 1
    return res


def match_ko_en(ko_names: list[str], en_names: list[str], threshold: float = 0.55):
    """Globally optimal 1:1 ko<->en assignment on transliteration similarity
    (Hungarian algorithm); pairs scoring below ``threshold`` are dropped.
    Returns {ko_index: (en_index, score)}."""
    if not ko_names or not en_names:
        return {}
    S = [[_pair_score(k, e) for e in en_names] for k in ko_names]
    transpose = len(ko_names) > len(en_names)
    M = [list(r) for r in zip(*S)] if transpose else S
    assign = _hungarian_max(M)
    res, low = {}, {}
    for r, c in enumerate(assign):
        if c < 0:
            continue
        i, j = (c, r) if transpose else (r, c)
        (res if S[i][j] >= threshold else low)[i] = (j, round(S[i][j], 3))
    # Equal-length lists describe the same artists: keep up to 3 leftover
    # optimal pairs even below threshold (callers flag them as low-confidence),
    # e.g. 2023 '아서 자파' <-> 'Arthur Jafa' (Korean drops the post-vocalic r).
    if low and len(ko_names) == len(en_names) and len(low) <= 3:
        res.update(low)
    return res


def _join_label(sc: float, threshold: float = 0.55) -> str:
    return f"transliteration_match{'_lowconf' if sc < threshold else ''}:{sc}"


def combine_by_matching(ko_recs: list[dict], en_recs: list[dict], threshold: float = 0.55,
                        tag: str = "name_en_join") -> list[dict]:
    """Attach English names to Korean records via ``match_ko_en``; unmatched
    English names are kept as English-only records (flagged)."""
    m = match_ko_en([r["name_ko"] for r in ko_recs], [r["name_en"] for r in en_recs], threshold)
    out, used = [], set()
    for i, r in enumerate(ko_recs):
        r = dict(r)
        if i in m:
            j, sc = m[i]
            used.add(j)
            r["name_en"] = en_recs[j]["name_en"]
            r[tag] = _join_label(sc)
        out.append(r)
    for j, e in enumerate(en_recs):
        if j not in used:
            e = dict(e)
            e[tag] = "unmatched_en_only"
            out.append(e)
    return finalize(out)


# --------------------------------------------------------------------------
# GWANGJU  (www.gwangjubiennale.org) -- server-rendered JSP pages
# --------------------------------------------------------------------------
GJ = "https://www.gwangjubiennale.org"


def _gj_is_en(text: str) -> bool:
    """English archive pages post their forms to /en/...; the <html lang> is
    'ko' on both language versions, so it cannot be used."""
    return bool(re.search(r'action="/en/', text))


def _gj_writer_list(text: str) -> list[tuple[int, str]]:
    soup = BeautifulSoup(text, "lxml")
    res = []
    for a in soup.select(".writer-b li a"):
        m = re.search(r"pf_WorkList\('(\d+)'", a.get("href", "") + (a.get("onclick") or ""))
        nm = clean(a.get_text(" "))
        if m and nm:
            res.append((int(m.group(1)), nm))
    return res


def parse_gwangju_list_page(text: str) -> list[dict]:
    """Archive 'past/NN.do' page (main-exhibition tab or ?subPageCode=artists):
    one ``<div class="writer-b"><ul><li><a href="javascript:pf_WorkList('ID',..)">NAME``
    per artist.  Korean and English pages carry different IDs; see
    ``combine_gwangju``."""
    en = _gj_is_en(text)
    out = []
    for gid, nm in _gj_writer_list(text):
        if en:
            out.append(make_artist(name_en=nm, _gb_id=gid, _lang="en"))
        else:
            out.append(make_artist(name_ko=nm, _gb_id=gid, _lang="ko"))
    if not out:  # GB-commission style tab: plain list after a '참여작가' heading
        out = _gj_commission_tab(text)
    return out


def _gj_commission_tab(text: str) -> list[dict]:
    """2021 '?subPageCode=gbCommission' tab -> names flagged ``_exclude``."""
    soup = BeautifulSoup(text, "lxml")
    wrap = soup.select_one(".tab-wrap")
    if not wrap or "GB커미션" not in wrap.get_text():
        return []
    lines = [clean(x) for x in wrap.get_text("\n").split("\n")]
    lines = [x for x in lines if x]
    try:
        start = lines.index("참여작가") + 1
    except ValueError:
        return []
    names = []
    for ln in lines[start:]:
        if ln in names:  # list ends where the per-artist write-ups repeat names
            break
        if len(ln) > 25:
            break
        names.append(ln)
    return [make_artist(name_ko=n, _exclude=True, _lang="ko") for n in names]


def _id_blocks(recs: list[dict], gap: int = 3) -> list[list[dict]]:
    recs = sorted(recs, key=lambda r: r["_gb_id"])
    blocks: list[list[dict]] = []
    for r in recs:
        if blocks and r["_gb_id"] - blocks[-1][-1]["_gb_id"] <= gap:
            blocks[-1].append(r)
        else:
            blocks.append([r])
    return blocks


def _gj_structural_join(ko: list[dict], en: list[dict]):
    """Candidate join from the archive record IDs, or None.
    (a) constant offset en_id = ko_id + k; (b) rank-join inside contiguous ID
    blocks after dropping repeated English names."""
    ko_ids = {r["_gb_id"]: r for r in ko}
    en_ids = {r["_gb_id"]: r for r in en}
    off = min(en_ids) - min(ko_ids)
    pairs = [(r, en_ids[i + off]) for i, r in sorted(ko_ids.items()) if i + off in en_ids]
    if len(pairs) >= 0.9 * min(len(ko), len(en)):
        return pairs, "archive_id_offset"
    seen_en: set[str] = set()
    en_blocks = []
    for blk in _id_blocks(en):
        nb = []
        for r in blk:
            k = norm_key(r["name_en"])
            if k not in seen_en:
                seen_en.add(k)
                nb.append(r)
        en_blocks.append(nb)
    ko_blocks = _id_blocks(ko)
    if len(ko_blocks) == len(en_blocks) and all(len(x) == len(y) for x, y in zip(ko_blocks, en_blocks)):
        return [p for kb, eb in zip(ko_blocks, en_blocks) for p in zip(kb, eb)], "archive_id_block_rank"
    return None


def _gj_join(ko: list[dict], en: list[dict]) -> list[dict]:
    """Join the Korean and English archive lists of one Gwangju edition.

    The two language versions are separate DB rows with different IDs.  A
    structural (ID-based) pairing is tried first and accepted only if it is
    *validated* by transliteration similarity (median pair score >= 0.6) --
    in 2023 the IDs line up numerically but the two lists were entered in
    different orders, so the structural pairing is rejected there.  Otherwise
    (and for rows left over by the structural pairing) names are paired by a
    globally optimal transliteration match.  Korean-only spelling-variant
    duplicates are folded (``_fold_ko_variants``).  ``name_en_join`` records
    how each English name was attached.
    """
    if not ko or not en:
        return ko + en
    out: list[dict] = []
    cand = _gj_structural_join(ko, en)
    if cand:
        pairs, how = cand
        scores = sorted(_pair_score(k["name_ko"], e["name_en"]) for k, e in pairs)
        median = scores[len(scores) // 2] if scores else 0.0
        if median >= 0.6:
            used_k, used_e = set(), set()
            for k, e in pairs:
                r = dict(k)
                r["name_en"] = e["name_en"]
                r["name_en_join"] = how
                out.append(r)
                used_k.add(k["_gb_id"])
                used_e.add(e["_gb_id"])
            ko = [r for r in ko if r["_gb_id"] not in used_k]
            en = [r for r in en if r["_gb_id"] not in used_e]
    # remaining rows (all rows when no validated structural join exists)
    seen = {norm_key(r["name_en"]) for r in out}
    en = [r for r in en if norm_key(r["name_en"]) not in seen]  # repeated English rows
    if ko and en:
        m = match_ko_en([r["name_ko"] for r in ko], [r["name_en"] for r in en])
        used_e = set()
        for i, r in enumerate(ko):
            r = dict(r)
            if i in m:
                j, sc = m[i]
                used_e.add(j)
                r["name_en"] = en[j]["name_en"]
                r["name_en_join"] = _join_label(sc)
            out.append(r)
        out += [dict(e, name_en_join="unmatched_en_only") for j, e in enumerate(en) if j not in used_e]
    else:
        out += [dict(r) for r in ko] + [dict(e, name_en_join="unmatched_en_only") for e in en]
    return _fold_ko_variants(out)


def _fold_ko_variants(recs: list[dict]) -> list[dict]:
    """A Korean-only record whose romanised consonant skeleton equals that of
    an already ko+en-joined record is a spelling-variant duplicate in the
    source DB (2016: '리리 레이너드 드워' ~ '릴리 레노 드와'); fold it in as
    ``name_ko_variants`` instead of counting it twice."""
    joined = [r for r in recs if r.get("name_ko") and r.get("name_en")]
    out = []
    for r in recs:
        if r.get("name_ko") and not r.get("name_en"):
            sk = _skeleton(romanize_hangul(r["name_ko"]))
            twin = next((o for o in joined if _skeleton(romanize_hangul(o["name_ko"])) == sk), None)
            if twin is not None and len(sk) >= 3:
                twin.setdefault("name_ko_variants", []).append(r["name_ko"])
                continue
        out.append(r)
    return out


def combine_gwangju(per_page: list[list[dict]]) -> list[dict]:
    recs = [r for page in per_page for r in page]
    excl = {norm_key(r["name_ko"]) for r in recs if r.get("_exclude")}
    ko = [r for r in recs if r.get("_lang") == "ko" and not r.get("_exclude") and "_gb_id" in r]
    en = [r for r in recs if r.get("_lang") == "en" and "_gb_id" in r]
    joined = _gj_join(ko, en)
    if excl:
        # drop excluded (GB Commission) names; joined English names go with them
        joined = [r for r in joined if norm_key(r.get("name_ko")) not in excl]
    return finalize(joined)


# per-edition aliases (same template)
parse_gwangju_2016 = parse_gwangju_list_page
parse_gwangju_2021 = parse_gwangju_list_page
parse_gwangju_2023 = parse_gwangju_list_page
parse_gwangju_2024 = parse_gwangju_list_page


def _gj_fix_en(ko: str | None, en: str | None) -> tuple[str | None, str | None]:
    """Repair the 2018 tables' cell glitches: ('하산 M.', '엘라히 Hasan M. Elahi'),
    ('엘라 서덜랜드 Ella', 'Sutherland') and glued 'KaderAttia'."""
    ko, en = clean(ko), clean(en)
    if (ko and LATIN_RE.search(ko.split()[-1]) and not has_hangul(ko.split()[-1])) or has_hangul(en):
        ko, en = split_ko_en(f"{ko or ''} {en or ''}")
    if en and ko and " " not in en and " " in ko:
        en = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", en)
    return ko, en


# The seven curated exhibitions of the 12th edition, as titled on the archive page.
GJ2018_SECTIONS = [
    (r"Imagined Nations", "Imagined Nations/Modern Utopias (curator: Clara Kim)"),
    (r"Facing Phantom Borders", "Facing Phantom Borders (curator: Gridthiya Gaweewong)"),
    (r"Post-?\s*Internet", "Art and the Global Post-Internet Condition (curators: Christine Y. Kim, Rita Gonzalez)"),
    (r"Fault ?[Ll]ine", "Whose Fault Line Is It? / Faultlines (curators: Yeon Shim Chung, Yeewan Koon)"),
    (r"\bReturns\b", "Returns (curator: David Teh)"),
    (r"Art of Survival", "The Art of Survival: Assembly, Sustainability, Shift "
                         "(curators: Man Seok Kim, Sung woo Kim, Chong-Ok Paek)"),
    (r"North Korean Art", "North Korean Art: Paradoxical Realism (curator: B.G. Muhn)"),
    (r"GB\s*(커미션|Commission)", "GB Commission"),
]


def _gj_is_en_page(text: str) -> bool:
    return _gj_is_en(text) or bool(re.search(r'location\.href\s*=\s*"/en/', text))


def parse_gwangju_2018(text: str) -> list[dict]:
    """12th edition (2018) -- two page kinds:

    * ``12.do`` (main tab, ko or en): one table per curated exhibition
      (7 exhibitions + GB Commission + a regional-summary table).  The GB
      Commission table is skipped.  ko tables give ko/en/country, en tables
      give en/country.  Both are pre-opening snapshots ("2018.06 현재") and
      differ slightly from each other.
    * ``12.do?subPageCode=artists`` (ko or en): the final archive artist DB
      (no sections, no countries); delegated to ``parse_gwangju_list_page``.
    """
    if "writer-b" in text:
        recs = parse_gwangju_list_page(text)
        for r in recs:
            r["_src"] = "archive_list"
        return recs
    soup = BeautifulSoup(text, "lxml")
    en = _gj_is_en_page(text)
    out = []
    for tb in soup.find_all("table"):
        rows = [[clean(c.get_text(" ")) or "" for c in tr.find_all(["td", "th"])] for tr in tb.find_all("tr")]
        head = " ".join(" ".join(r) for r in rows[:2])
        if not re.search(r"작가명|Name", head):
            continue  # regional summary table
        sec = None
        for prev in tb.find_all_previous(string=True, limit=300):
            p = clean(prev) or ""
            hit = next((label for pat, label in GJ2018_SECTIONS if re.search(pat, p)), None)
            if hit:
                sec = hit
                break
        if sec == "GB Commission" or any("Villar Rojas" in " ".join(r) for r in rows):
            continue  # GB Commission is out of scope
        for r in rows:
            if not r or not re.fullmatch(r"\d+", r[0] or ""):
                continue
            if en and len(r) >= 3:
                out.append(make_artist(name_en=r[1], country=r[2], section=[sec] if sec else None,
                                       _src="table_en"))
            elif not en and len(r) >= 4:
                ko, e = _gj_fix_en(r[1], r[2])
                out.append(make_artist(name_ko=ko, name_en=e, country=None, country_ko=r[3],
                                       section=[sec] if sec else None, _src="table_ko"))
    return out


def _parts(name: str | None) -> list[str]:
    if not name:
        return []
    return [norm_key(x) for x in re.split(r"\s*(?:\+|&|,|\band\b|\bwith\b|/)\s*", name) if norm_key(x)]


def _same_en(a: str | None, b: str | None, thr: float = 0.86) -> bool:
    if not a or not b:
        return False
    ka, kb = norm_key(a), norm_key(b)
    if ka == kb or _ratio(ka, kb) >= thr:
        return True
    ta = sorted(norm_key(t) for t in a.split())
    tb = sorted(norm_key(t) for t in b.split())
    return ta == tb  # 'Hyok Im' == 'Im Hyok'


def _add_sections(dst: dict, src: dict) -> None:
    dst.setdefault("section", [])
    if dst["section"] is None:
        dst["section"] = []
    for s_ in src.get("section") or []:
        if s_ not in dst["section"]:
            dst["section"].append(s_)


def combine_gwangju_2018(per_page: list[list[dict]]) -> list[dict]:
    """Union of the curated-exhibition tables (ko + en snapshots) and the final
    archive artist list.  The archive's own ko<->en row pairing is NOT trusted
    (its North-Korean rows are misaligned), so archive ko names are matched to
    table rows by Korean name and archive en names by English name separately.
    Adds ``in_curated_table`` / ``in_final_archive_list`` flags; artists only in
    the archive list get no ``section``."""
    recs = [r for p in per_page for r in p]
    tko = [r for r in recs if r.get("_src") == "table_ko"]
    ten = [r for r in recs if r.get("_src") == "table_en"]
    # 1) merge the two table snapshots (ko-table rows also carry an English column)
    merged: list[dict] = [dict(r, _en_variants=[r["name_en"]] if r.get("name_en") else []) for r in tko]
    for r in ten:
        hit = next((m for m in merged if any(_same_en(v, r["name_en"]) for v in m["_en_variants"])), None)
        lead = r["name_en"].split(" with ")[0] if " with " in r["name_en"] else None
        if hit is None and lead:  # 'Tom Nicholson with Grace Samboh' vs 'Tom Nicholson'
            hit = next((m for m in merged if any(_same_en(v, lead) for v in m["_en_variants"])
                        and set(m.get("section") or []) & set(r.get("section") or [])), None)
            if hit:
                hit["_en_variants"].append(r["name_en"])
                hit.setdefault("note", f"English table lists this entry as '{r['name_en']}'")
                hit["country"] = hit.get("country") or r.get("country")
                continue
        if hit:
            hit["name_en"] = r["name_en"]  # English-page spelling (diacritics, spacing)
            hit["country"] = hit.get("country") or r.get("country")
            hit["_en_variants"].append(r["name_en"])
            _add_sections(hit, r)
        else:
            merged.append(dict(r, _en_variants=[r["name_en"]]))
    # 2) the same artist listed in two exhibitions -> one record, two sections
    tbl: list[dict] = []
    for m in merged:
        hit = next((t for t in tbl
                    if (m.get("name_ko") and t.get("name_ko") and norm_key(m["name_ko"]) == norm_key(t["name_ko"]))
                    or any(_same_en(v, w) for v in m["_en_variants"] for w in t["_en_variants"])), None)
        if hit:
            _add_sections(hit, m)
            hit["_en_variants"] += m["_en_variants"]
            for k in ("name_ko", "country", "country_ko"):
                hit[k] = hit.get(k) or m.get(k)
        else:
            tbl.append(m)
    for t in tbl:
        t["in_curated_table"], t["in_final_archive_list"] = True, False
    # 3) final archive list, matched per language
    ako = [r for r in recs if r.get("_src") == "archive_list" and r["_lang"] == "ko"]
    aen = [r for r in recs if r.get("_src") == "archive_list" and r["_lang"] == "en"]
    left_ko, left_en = [], []
    for a in ako:
        k = norm_key(a["name_ko"])
        hit = next((t for t in tbl if t.get("name_ko") and (norm_key(t["name_ko"]) == k or (
            k in _parts(t["name_ko"]) and len(_parts(t["name_ko"])) > 1) or (
            len(norm_key(t["name_ko"])) >= 4 and k.startswith(norm_key(t["name_ko"]))))), None)
        if hit is None:
            # archive spelling differs from the table spelling ('먀오 잉' / '미아오 잉',
            # '딘 Q. 르' / '딘 Q. 레', '티파니 청' / en-only 'Tiffany Chung')
            best, best_s = None, 0.0
            for t in tbl:
                sc = max(_ratio(k, norm_key(t.get("name_ko"))) if t.get("name_ko") else 0.0,
                         _pair_score(a["name_ko"], t["name_en"]) if t.get("name_en") else 0.0)
                if sc > best_s:
                    best, best_s = t, sc
            if best is not None and best_s >= 0.7:
                hit = best
                if not hit.get("name_ko"):
                    hit["name_ko"] = a["name_ko"]
                elif norm_key(hit["name_ko"]) != k:
                    hit.setdefault("name_ko_archive", a["name_ko"])
        if hit:
            hit["in_final_archive_list"] = True
        else:
            left_ko.append(a)
    for a in aen:
        hit = next((t for t in tbl if any(_same_en(a["name_en"], v) for v in t["_en_variants"])), None)
        if hit is None:
            hit = next((t for t in tbl if norm_key(a["name_en"]) in _parts(" + ".join(t["_en_variants"]))), None)
        if hit:
            hit["in_final_archive_list"] = True
            if norm_key(hit["name_en"]) != norm_key(a["name_en"]):
                hit.setdefault("name_en_archive", a["name_en"])
        else:
            left_en.append(a)
    for t in tbl:  # English country from the en table when available, else the Korean value
        t["country"] = t.get("country") or t.get("country_ko")
    extra = combine_by_matching(left_ko, left_en) if (left_ko or left_en) else []
    for e in extra:
        e["in_curated_table"], e["in_final_archive_list"] = False, True
    return finalize(tbl + extra)


def parse_gwangju_2026(text: str) -> list[dict]:
    """16th edition (2026) current site, mainexhibition.do?subPage=artists:
    ``<div class="new_author_box"><ul class="list"><li>국문<br>(English)</li>``.
    Commented-out duplicate <li> are ignored by the HTML parser."""
    soup = BeautifulSoup(text, "lxml")
    out = []
    for li in soup.select(".new_author_box ul.list > li"):
        parts = [clean(x) for x in li.get_text("\n").split("\n")]
        parts = [p for p in parts if p]
        if not parts:
            continue
        ko = parts[0]
        en = " ".join(parts[1:]) if len(parts) > 1 else None
        if en and en.startswith("(") and en.endswith(")"):
            en = en[1:-1]
        if not has_hangul(ko):
            ko, en = None, ko
        out.append(make_artist(name_ko=ko, name_en=en))
    return out


# --------------------------------------------------------------------------
# BUSAN  (www.busanbiennale.org archive -- PHP board pages, 12-15 items/page)
# --------------------------------------------------------------------------
BB = "http://www.busanbiennale.org"


def busan_page_urls(first_page_text: str, base_url: str) -> list[str]:
    """All pagination URLs of a board, derived from page 1 (for crawlers)."""
    pages = [int(x) for x in re.findall(r"[?&](?:amp;)?pg=(\d+)", first_page_text)]
    last = max(pages) if pages else 1
    return [base_url] + [f"{base_url}&pg={p}" for p in range(2, last + 1)]


def parse_busan_board(text: str) -> list[dict]:
    """Archive gallery board (``ul.gallery-list > li``).

    * artwork boards (2016, 2018): artist = ``span.writer``; section = active
      tab (Project 1/2 or venue);
    * artist boards (2022, 2024): artist = ``p.ptitle``.
    Language from the page's search-form action (``/BBOCen/`` = English).
    Comma-joined entries get a ``members`` list."""
    soup = BeautifulSoup(text, "lxml")
    en = bool(re.search(r'action="/BBOCen/', text))
    sec = None
    for li in soup.select(".b-tab01 li.over"):
        t = clean(li.get_text(" "))
        if t and not re.fullmatch(r"\d{4}", t):
            sec = t
    out = []
    for li in soup.select("ul.gallery-list > li"):
        w = li.select_one(".writer")
        t = li.select_one(".ptitle")
        name = clean(w.get_text(" ")) if w else (clean(t.get_text(" ")) if t else None)
        if not name:
            continue
        kw = {"section": [sec] if sec else None}
        # comma-joined entries are joint works of separately counted artists
        # ('박민희, 송민정, 조율'); '&' / '+' entries are kept as one team.
        parts = split_top_level(name, ",")
        if len(parts) > 1:
            kw["members"] = parts
        if en:
            out.append(make_artist(name_en=name, _lang="en", **kw))
        else:
            out.append(make_artist(name_ko=name, _lang="ko", **kw))
    return out


parse_busan_2016 = parse_busan_board
parse_busan_2018 = parse_busan_board
parse_busan_2022 = parse_busan_board
parse_busan_2024 = parse_busan_board


def combine_busan_ko_en(per_page: list[list[dict]]) -> list[dict]:
    """Korean board + (optional) English board without a shared key:
    de-dupe each side, then transliteration matching (``combine_by_matching``)."""
    recs = [r for p in per_page for r in p]
    ko = dedupe(r for r in recs if r.get("_lang") == "ko")
    en = dedupe(r for r in recs if r.get("_lang") == "en")
    if not en:
        return finalize(ko)
    return combine_by_matching(ko, en)


def parse_busan_2020(text: str) -> list[dict]:
    """2020 '작가/작품보기' (pCode=2020_05): chapters x roles, each name is
    ``<a href="...pCode=2020_051&CgCode=NN">``; CgCode is shared by the ko and
    en pages and is used as the join key."""
    soup = BeautifulSoup(text, "lxml")
    en = bool(re.search(r'action="/BBOCen/', text)) or "/BBOCen/index.php?pCode=2020_051" in text
    role_map = {"문필가": "writer", "Author": "writer", "시각예술가": "visual artist", "Artist": "visual artist",
                "음악가": "musician", "Musician": "musician", "사운드아티스트": "musician"}
    out = []
    for li in soup.select("ul.wr-li > li"):
        ch = clean(li.select_one("p").get_text(" ")) if li.select_one("p") else None
        role = None
        for el in li.find_all(["h4", "p"]):
            if el.name == "h4":
                role = role_map.get(clean(el.get_text(" ")), clean(el.get_text(" ")))
                continue
            a = el.find("a", href=True)
            if not a:
                continue
            m = re.search(r"CgCode=(\d+)", a["href"])
            nm = clean(a.get_text(" "))
            if not (m and nm):
                continue
            kw = dict(role=[role] if role else None, section=[ch] if ch else None, _cg=m.group(1))
            if en:
                out.append(make_artist(name_en=nm, _lang="en", **kw))
            else:
                out.append(make_artist(name_ko=nm, _lang="ko", **kw))
    return out


def combine_busan_2020(per_page: list[list[dict]]) -> list[dict]:
    recs = [r for p in per_page for r in p]
    en_by_cg = {r["_cg"]: r["name_en"] for r in recs if r.get("_lang") == "en"}
    out = []
    for r in recs:
        if r.get("_lang") != "ko":
            continue
        r = dict(r)
        r["name_en"] = en_by_cg.get(r["_cg"])
        out.append(r)
    if not out:  # only the English page was supplied
        out = [r for r in recs if r.get("_lang") == "en"]
    return finalize(out)


def parse_busan_2026(text: str) -> list[dict]:
    """busanbiennale2026.com/artists (Kirby CMS, server-rendered).  The
    bilingual name is only in the alt text of the name image
    (``<img class="artist-name-img" alt="강서경 Suki Seokyeong Kang">``); the alt
    is not HTML-escaped (e.g. ``"토가르" ... "Togar"``), so it is read with a
    regex anchored on the following ``loading=`` attribute."""
    out = []
    for m in re.finditer(r'<a class="artist-item[^"]*"[^>]*href="([^"]+)"[^>]*?data-tags="([^"]*)"', text):
        href, tags = m.group(1), m.group(2)
        seg = text[m.end(): m.end() + 6000]
        am = re.search(r'class="artist-name-img"\s+src="[^"]*"\s+alt="(.*?)"\s+loading=', seg, re.S)
        if not am:
            continue
        ko, en = split_ko_en(am.group(1))
        venues = [t.split(":", 1)[1] for t in tags.split() if t.startswith("venue:")]
        out.append(make_artist(name_ko=ko, name_en=en, slug=href.rstrip("/").rsplit("/", 1)[-1],
                               section=venues or None))
    return out


# --------------------------------------------------------------------------
# SEOUL MEDIACITY  (sema.seoul.go.kr/kr/whatson/series/detail?exNo=..&clftCd=E1)
# robots.txt of sema.seoul.go.kr: Disallow / but Allow /kr/whatson -> OK.
# --------------------------------------------------------------------------
SEMA = "https://sema.seoul.go.kr/kr/whatson/series/detail?exNo={}&clftCd=E1"


def _sema_field(text: str, label: str = "참여작가") -> str | None:
    soup = BeautifulSoup(text, "lxml")
    for el in soup.find_all(["div", "dt", "th", "span", "strong"]):
        if clean(el.get_text(" ")) == label:
            nxt = el.find_next_sibling()
            if nxt is not None:
                return clean(nxt.get_text(" "))
    return None


def _sema_split_names(field: str) -> list[dict]:
    field = re.sub(r"^\[총[^\]]*\]\s*", "", field)  # '[총 41명/팀]'
    out = []
    for part in split_top_level(field, ","):
        part = _balance_parens(part)
        ko, en, members = part, None, None
        # 'ko(en)' or 'ko[en]' or 'ko (members)[en]'
        m = re.match(r"^(.*?)\s*\[([^\]]+)\]$", part)
        if m:
            ko, en = m.group(1), m.group(2)
        m = re.match(r"^(.*?)\s*\(([^)]+)\)$", ko)
        if m:
            inner = m.group(2)
            if has_hangul(inner):
                members = split_top_level(inner, ",")  # e.g. 보물섬 콜렉티브(김동찬, 민성홍, ...)
                ko = m.group(1)
            elif not en and LATIN_RE.search(inner):
                ko, en = m.group(1), inner
        if not has_hangul(ko) and not en:
            ko, en = None, ko
        out.append(make_artist(name_ko=ko, name_en=en, members=members))
    return out


def parse_seoul_mediacity_2018(text: str) -> list[dict]:
    """10th (2018) -- comma-separated '참여작가' field (Korean only)."""
    f = _sema_field(text)
    return _sema_split_names(f) if f else []


parse_seoul_mediacity_2021 = parse_seoul_mediacity_2018  # '[총 41명/팀] 한글(English), ...'
parse_seoul_mediacity_2023 = parse_seoul_mediacity_2018


def parse_seoul_mediacity_2016(text: str) -> list[dict]:
    """9th (2016) -- the '참여작가' field only gives a count; the artists are in
    per-venue work tables (연번 | 작가 '국문<br>English' | 작품 | 제작연도)."""
    soup = BeautifulSoup(text, "lxml")
    out = []
    for tb in soup.find_all("table"):
        hdr = clean(" ".join(th.get_text(" ") for th in tb.find_all("th"))) or ""
        cap = clean(tb.find("caption").get_text(" ")) if tb.find("caption") else ""
        if "작가" not in hdr or "작품" not in hdr:
            continue
        venue = None
        mm = re.match(r"(.*?) 전시를 연번", cap or "")
        if mm:
            venue = clean(mm.group(1))
        for tr in tb.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) < 3 or not re.fullmatch(r"\d+", clean(tds[0].get_text()) or ""):
                continue
            parts = [clean(x) for x in tds[1].get_text("\n").split("\n")]
            parts = [p for p in parts if p]
            if not parts:
                continue
            ko = parts[0] if has_hangul(parts[0]) else None
            en = " ".join(p for p in parts if not has_hangul(p)) or None
            if en:
                en = re.sub(r"\s*&\s*", " & ", en)
            if ko:
                ko = re.sub(r"\s*&\s*", " & ", ko)
            out.append(make_artist(name_ko=ko, name_en=en, section=[venue] if venue else None))
    return out


def parse_seoul_mediacity_2025(text: str) -> list[dict]:
    """13th (2025) -- names are links to mediacityseoul.kr participant pages
    (not fetched: robots-disallowed).  A long name can be split over several
    <a> with the same href, so anchors are grouped by href; the href slug is
    kept as ``slug`` (a romanised identifier, NOT an authoritative English name)."""
    soup = BeautifulSoup(text, "lxml")
    order, names = [], {}
    for a in soup.find_all("a", href=True):
        if "/participants/" not in a["href"]:
            continue
        slug = a["href"].rstrip("/").rsplit("/", 1)[-1]
        t = clean(a.get_text(" "))
        if not t:
            continue
        if slug not in names:
            order.append(slug)
            names[slug] = []
        names[slug].append(t)
    return [make_artist(name_ko=clean(" ".join(names[s])), slug=s) for s in order]


# --------------------------------------------------------------------------
# edition registry
# --------------------------------------------------------------------------
def _pages(base: str, n: int) -> list[str]:
    return [base] + [f"{base}&pg={p}" for p in range(2, n + 1)]


EDITION_SOURCES: dict[str, dict] = {
    # ---------------- Gwangju ----------------
    "gwangju_2016": {"urls": [f"{GJ}/gb/exhibition/past/11.do?subPageCode=artists",
                              f"{GJ}/en/exhibition/past/11.do?subPageCode=artists"],
                     "parser": "parse_gwangju_2016", "combine": "combine_gwangju", "fetch": "html"},
    "gwangju_2018": {"urls": [f"{GJ}/gb/exhibition/past/12.do",  # 7 curated-exhibition tables (ko/en/country)
                              f"{GJ}/en/exhibition/past/12.do",  # same tables, English snapshot
                              f"{GJ}/gb/exhibition/past/12.do?subPageCode=artists",  # final archive list ko
                              f"{GJ}/en/exhibition/past/12.do?subPageCode=artists"],  # final archive list en
                     "parser": "parse_gwangju_2018", "combine": "combine_gwangju_2018", "fetch": "html"},
    "gwangju_2021": {"urls": [f"{GJ}/gb/exhibition/past/13.do",
                              f"{GJ}/en/exhibition/past/13.do",
                              f"{GJ}/gb/exhibition/past/13.do?subPageCode=gbCommission"],  # exclusion list
                     "parser": "parse_gwangju_2021", "combine": "combine_gwangju", "fetch": "html"},
    "gwangju_2023": {"urls": [f"{GJ}/gb/exhibition/past/14.do", f"{GJ}/en/exhibition/past/14.do"],
                     "parser": "parse_gwangju_2023", "combine": "combine_gwangju", "fetch": "html"},
    "gwangju_2024": {"urls": [f"{GJ}/gb/exhibition/past/15.do", f"{GJ}/en/exhibition/past/15.do"],
                     "parser": "parse_gwangju_2024", "combine": "combine_gwangju", "fetch": "html"},
    "gwangju_2026": {"urls": [f"{GJ}/gb/exhibition/biennale/mainexhibition.do?subPage=artists"],
                     "parser": "parse_gwangju_2026", "fetch": "html"},
    # ---------------- Busan ----------------
    "busan_2016": {"urls": _pages(f"{BB}/BBOCkr/index.php?pCode=MN1000156", 6)      # Project 1
                   + _pages(f"{BB}/BBOCkr/index.php?pCode=MN1000157", 5),            # Project 2 (본전시)
                   "parser": "parse_busan_2016", "combine": "combine_busan_ko_en", "fetch": "html",
                   "optional_en_urls_untested": [f"{BB}/BBOCen/index.php?pCode=MN2000153"]},
    "busan_2018": {"urls": _pages(f"{BB}/BBOCkr/index.php?pCode=2018_06_01", 5)     # MOCA Busan
                   + _pages(f"{BB}/BBOCkr/index.php?pCode=2018_06_02", 2),           # former Bank of Korea
                   "parser": "parse_busan_2018", "combine": "combine_busan_ko_en", "fetch": "html",
                   "optional_en_urls_untested": [f"{BB}/BBOCen/index.php?pCode=MN2000197"]},
    "busan_2020": {"urls": [f"{BB}/BBOCkr/index.php?pCode=2020_05", f"{BB}/BBOCen/index.php?pCode=2020_05"],
                   "parser": "parse_busan_2020", "combine": "combine_busan_2020", "fetch": "html"},
    "busan_2022": {"urls": _pages(f"{BB}/BBOCkr/index.php?pCode=2022_051_1", 4)     # MOCA Busan
                   + [f"{BB}/BBOCkr/index.php?pCode=2022_051_2", f"{BB}/BBOCkr/index.php?pCode=2022_051_2&pg=2",
                      f"{BB}/BBOCkr/index.php?pCode=2022_051_3", f"{BB}/BBOCkr/index.php?pCode=2022_051_4"],
                   "parser": "parse_busan_2022", "combine": "combine_busan_ko_en", "fetch": "html",
                   "optional_en_urls_untested": [f"{BB}/BBOCen/index.php?pCode=2022_051_1"]},
    "busan_2024": {"urls": _pages(f"{BB}/BBOCkr/index.php?pCode=MN1000529", 5)
                   + _pages(f"{BB}/BBOCen/index.php?pCode=MN2000461", 5),
                   "parser": "parse_busan_2024", "combine": "combine_busan_ko_en", "fetch": "html"},
    "busan_2026": {"urls": ["https://busanbiennale2026.com/artists"],
                   "parser": "parse_busan_2026", "fetch": "html"},
    # ---------------- Seoul Mediacity ----------------
    "seoul_mediacity_2016": {"urls": [SEMA.format(492)], "parser": "parse_seoul_mediacity_2016", "fetch": "html"},
    "seoul_mediacity_2018": {"urls": [SEMA.format(231879)], "parser": "parse_seoul_mediacity_2018", "fetch": "html"},
    "seoul_mediacity_2021": {"urls": [SEMA.format(573192)], "parser": "parse_seoul_mediacity_2021", "fetch": "html"},
    "seoul_mediacity_2023": {"urls": [SEMA.format(1199259)], "parser": "parse_seoul_mediacity_2023", "fetch": "html"},
    "seoul_mediacity_2025": {"urls": [SEMA.format(1429611)], "parser": "parse_seoul_mediacity_2025", "fetch": "html"},
}


def run_edition(edition_id: str, get_text: Callable[[str], str]) -> list[dict]:
    """Fetch every URL of an edition with ``get_text`` and return the final list."""
    cfg = EDITION_SOURCES[edition_id]
    parser = globals()[cfg["parser"]]
    per_page = [parser(get_text(u)) for u in cfg["urls"]]
    combine = globals()[cfg.get("combine", "combine_concat")]
    return combine(per_page)


# --------------------------------------------------------------------------- #
# v2 어댑터 — load.py의 edition_parser 계약: (회차 원본 텍스트들, 소스 순서) -> list[dict]
# --------------------------------------------------------------------------- #
# 작가가 아닌 출품 대상(자연물 등)은 참가작가 목록에서 뺀다 (2026-10-12 검토)
V2_EXCLUDE = {"제주 화산암(제주돌문화공원)", "Volcanoes of Jeju (Jeju Stone Park)"}


# 한/영 보드 음차 매칭 육안 검수(2026-10-13) 결과 틀린 쌍 교정: {회차: {한글 표기: 올바른 영문 표기 | None(영문 없음)}}
V2_PAIR_FIX = {
    "busan_2016": {"청년작가연립전": "Korean Young Artists Association Exhibition",
                   "강국진,정강자(퍼포머, performer),정찬승": None},
    "busan_2018": {"천민정": "Mina CHEON", "서민정": "Min Jeong Seo"},
}


def parse_pages(pages: list[str], edition_id: str) -> list[dict]:
    cfg = EDITION_SOURCES[edition_id]
    parser = globals()[cfg["parser"]]
    recs = globals()[cfg.get("combine", "combine_concat")]([parser(t) for t in pages])
    fix = V2_PAIR_FIX.get(edition_id, {})
    out = []
    for r in recs:
        if r.get("name_ko") in fix:
            r["name_en"] = fix[r["name_ko"]]
            r["name"] = r["name_en"] or r["name_ko"]
            r["name_en_join"] = "manual_fix_2026-10-13"
        if r.get("name") in V2_EXCLUDE or r.get("name_ko") in V2_EXCLUDE:
            continue
        sec = r.get("section")
        if isinstance(sec, (list, tuple)):
            sec = " / ".join(str(s) for s in sec if s) or None
        if edition_id == "gwangju_2018" and r.get("in_final_archive_list") is False:
            # 2018년 6월 전시표에만 있고 최종 아카이브 명단엔 없는 16명 — 철회 가능성, 구분 표시
            sec = f"{sec or 'main'} · 최종명단 미등재"
        r["section"] = sec
        if r.get("slug"):  # SeMA 영문 슬러그 -> 매칭용 별칭(표시명으로는 쓰지 않음)
            r.setdefault("aliases", []).append(r["slug"].replace("-", " "))
        out.append(r)
    return out
