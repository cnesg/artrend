# Dorotheum(오스트리아 빈) 조사 기록 — 2026-09-23

`docs/경매소스확장_20260922.md`가 세운 판정 기준(robots.txt 통과 **+** ToS 전문 확인,
둘 다 통과해야 진행)을 그대로 적용했다. 배경: 어제까지 독일(Grisebach/Lempertz/Nagel/
Hampel)·북유럽(Bukowskis)·영국(Sworders/Dreweatts/Lyon&Turnbull)·프랑스(Artcurial)·
스위스(Koller)·한국(칸옥션/K-ARTMARKET)·일본(Kogire-kai)·중국(Poly)을 훑었고,
**오스트리아는 미착수**였다 — 유럽 주요 경매사 중 남아 있던 Dorotheum(1707년 설립,
중부유럽 최대급, 연 700회 이상 세일)을 조사했다.

## 판정: **불가 — 완전 제외 (수집 금지)**

robots.txt는 통과하지만 **이용약관 제4조가 크롤링·스크래핑·TDM·임베딩/벡터DB 투입을
조목조목 명시 금지**하고, 그 위에 **EU DSM 지침 제4조 TDM 옵트아웃을 법적으로 유보**해
두었다. 이 프로젝트가 하는 일(크롤 → 자체 DB → `vault_curated` → `vault_embeddings`
임베딩 → LLM 질의응답)과 금지 항목이 **문자 그대로 일치**한다. 파일럿 수집도 하지 않았고,
DB 적재 건수는 **0건**이다.

### 1. robots.txt (2026-09-23 직접 GET, HTTP 200)

```
User-agent: *
Allow: *

User-agent: PetalBot
Disallow: /

Sitemap: https://www.dorotheum.com/sitemap.xml
```

전면 허용에 PetalBot만 차단. `ClaudeBot`/`GPTBot`/`CCBot`/`anthropic-ai`/`Bytespider`/
`Google-Extended` 등 AI봇 지목 차단도, Gagosian식 `Content-Signal: ai-train=no`도 **없다**.
**robots.txt만 보면 통과**다 — 이 프로젝트가 "robots.txt 통과 ≠ ToS 통과"를 규칙으로
못박아 둔 이유가 그대로 드러난 사례다.

### 2. 기술적 차단 — 콘텐츠 페이지 전면 Cloudflare 403

robots.txt와 정적 파일(`/fileadmin/**.pdf`)은 200을 주는데, **동적 HTML 페이지는 전부
403**이다. 브라우저 UA·Accept·Accept-Language·Upgrade-Insecure-Requests를 모두 맞춰도
동일했다:

| URL | 결과 |
|---|---|
| `/robots.txt` | 200 (text/plain) |
| `/fileadmin/user_upload/Download/Agb/AGB_Versteigerung_englisch.pdf` | 200 (application/pdf) |
| `/en/` | **403** |
| `/sitemap.xml` | **403** |
| `/en/c/terms-of-use-2445/` | **403** |
| `/de/c/nutzungsbedingungen-2445/` | **403** |
| `/en/auction-detail/`, `/en/l/` | **403** |

403 응답 헤더/바디가 차단 주체를 특정해준다 — `Server: cloudflare`, `CF-RAY:
a3f5a7662f878b5b-ICN`, `Set-Cookie: __cf_bm=…`, 바디는 `<title>Attention Required! |
Cloudflare</title>`. **Cloudflare Bot Management의 의도적 차단 룰**이지 일시적 레이트리밋이
아니다(Bukowskis의 간헐적 403과는 성격이 다르다 — 그쪽은 재시도하면 200이 났고, 여기는
100% 결정론적으로 막힌다).

이 프로젝트의 **Hauser & Wirth 선례**("robots.txt 요청 자체가 Vercel 봇 차단에 막혀 429…
우회는 ToS 위반 소지가 커서 제외")와 같은 상황이고, 오히려 더 명확하다 — H&W는 robots.txt
조차 못 읽어 판단 근거가 부족했지만, 여기는 **약관 전문을 확보해 명시적 금지를 확인**했다.

> **주의**: Cloudflare 챌린지는 실브라우저 자동화(Claude-in-Chrome)로는 통과한다. 실제로
> 리만머핀·페로탕은 그 경로로 수집한 전례가 있다. 그러나 **그 두 곳은 SPA 렌더링 문제였지
> 봇 차단이 아니었다** — 여기서 같은 수단을 쓰는 건 운영자가 일부러 세운 접근통제의
> **우회**이고, 아래 4절의 명시적 약관 금지와 겹치면 변명의 여지가 없다. 게다가
> `refresh_weekly.ps1`(헤드리스 PowerShell 주간 잡)에 연결할 수도 없어 사용자가 요구한
> "최신성" 요건도 어차피 못 채운다. **시도하지 않았다.**

### 3. 약관 전문 확보 방법

라이브 약관 페이지가 403이라 **Internet Archive의 공개 스냅샷**으로 읽었다(제3자의 적법한
아카이브를 읽는 것이지 Dorotheum WAF 우회가 아니다):

- 스냅샷: `web.archive.org/web/20260705163428id_/https://www.dorotheum.com/en/c/terms-of-use-2445/`
- CDX 조회 결과 200 스냅샷 6개(20250708 / 20251202 / 20260217 / 20260311 / 20260427 /
  **20260705**) — 20260705가 최신이고, 페이지 자체가 밝힌 **`Last update: 13.11.2025`**와
  일관된다. 즉 **현행 약관**으로 봐도 무방하다.
- 함께 받은 `AGB_Versteigerung_englisch.pdf`(경매 일반거래약관, 40,779자)는 pypdf로
  텍스트 추출해 `crawl|scrap|spider|robot|automat|data mining|index|database|96/9|sui
  generis|personal use|extract|re-utilis|third part|copyright|systematic` 전수 검색 →
  **크롤링/데이터 관련 조항 없음**(응찰·위탁 계약 조건일 뿐). 웹사이트 이용약관 쪽이
  결정적이었다.

### 4. 결정적 조항 — 이용약관 제4조 (원문 인용)

> **4. Copyright protection and prohibition of AI training / text and data mining**
>
> The elements contained on the website (in particular texts, images, graphics, video files,
> **databases, database extracts, and metadata**) are subject to copyright, ancillary
> copyright, and **database rights**. These elements may not be reproduced, distributed,
> publicly reproduced, edited, **transferred to your own databases or data sets**, or
> otherwise processed **without the express written consent of Dorotheum**.
>
> *Prohibition of AI use for training and mining purposes.* It is expressly prohibited to use
> the content of this website, in whole or in part, to
> a) **capture, extract, or copy (including scraping, crawling, harvesting)**,
> b) **analyze automatically (text and data mining)**,
> c) **feed into data sets, embeddings, vector databases, or prompt/response corpora**,
> d) use for the development, training, fine-tuning, testing, benchmarking, or quality
>    improvement of AI/ML models or comparable systems,
> e) allow third parties or third parties acting on behalf of third parties to use for the
>    above purposes.
>
> *Legal reservation (TDM opt-out).* Dorotheum objects, within the meaning of **Art. 4 of
> Directive (EU) 2019/790 ("DSM Directive")** and **§ 42h (6) UrhG (Austrian Copyright
> Act)**, to any use of the content made available on this website for the purpose of text
> and data mining by other users; Permissible exceptions in favor of research organizations
> and cultural institutions pursuant to Art. 3 …
>
> *(Last update: 13.11.2025)*

**왜 이게 이 프로젝트에 치명적인가** — 다른 경매사 약관은 보통 "이미지 저작권 유보"
정도이고(칸옥션 제7조③, Bukowskis 17조 — 그래서 "이미지는 수집 안 함"으로 지킬 수
있었다), 여기는 **파이프라인 전 단계를 하나씩 이름으로 지목**한다:

| Dorotheum 금지 조항 | artrend의 해당 단계 |
|---|---|
| a) scraping, crawling, harvesting | `crawlers/dorotheum.py` (작성 안 함) |
| "transferred to your own databases or data sets" | `pipeline/` → 로컬 Postgres 적재 |
| b) text and data mining | `build_curated_vault.py` |
| c) **embeddings, vector databases** | `embed_vault.py` → `vault_embeddings` |
| c) prompt/response corpora | `artgraph_chat.py` / `query_vault.py` |

**EU 법 층위**(Grisebach·Bukowskis 조사 때 적용한 패턴 그대로):
- **sui generis 데이터베이스권**(Directive 96/9/EC) — 경매결과 DB의 "substantial part"
  추출/재이용 금지. 약관이 `database rights`를 명시 원용한다.
- **DSM 지침 Art. 4(3) TDM 옵트아웃** — Art. 4의 상업적 TDM 예외는 권리자가 적절한 방식으로
  유보하면 **적용되지 않는다**. Dorotheum은 약관 본문에 명시적으로 유보했다. 즉 "EU에는
  TDM 예외가 있으니 괜찮다"는 논리가 **여기서는 성립하지 않는다**.
- **§ 42h(6) UrhG** — 오스트리아 저작권법상 같은 취지의 국내법 유보.
- 연구기관/문화유산기관 예외(Art. 3)는 유효하지만 **artrend는 그에 해당하지 않는다**
  (연구조직이 아닌 개인/사적 프로젝트).

## 기존 DB의 Dorotheum 데이터 — 확인 결과 **문제 없음**

DB에 이미 Dorotheum 로트가 **6,888건** 있어서 출처를 추적했다(혹시 과거 세션이
dorotheum.com을 긁었다면 컴플라이언스 문제가 되므로):

```
AUCTION_HOUSES: Dorotheum (id 45ed9e10-…, country=Austria, wikidata_qid=Q668545)
LOT SOURCE ROWS:
  getty_provenance_sales / sales_contents_7.csv   5,851
  getty_provenance_sales / sales_contents_8.csv     950
  getty_provenance_sales / sales_contents_10.csv     50
  getty_provenance_sales / sales_contents_12.csv     10
  auctions_wikidata      / (개별 QID json)           27
SOURCES(site_name/raw_path ilike '%dorotheum%'):  []   ← 없음
```

**전량이 Getty Provenance Index Sales(6,861건) + Wikidata(27건)** 출처다. `sources`에
dorotheum.com을 가리키는 행은 **0개** — dorotheum.com에서 직접 수집한 데이터는 **전혀
없다**. 두 소스 모두 제3자가 적법하게 배포하는 데이터셋이고 Dorotheum 웹사이트 약관의
적용 대상이 아니므로(약관은 dorotheum.com 이용자를 구속한다) **기존 데이터는 그대로
두면 된다. 삭제 불필요.**

## 최신성 — 바로 이 지점이 막혔다

기존 6,888건의 시간 분포(auctions 120개, 1911-02-18 ~ 2025-04-29):

| 연도 | 로트 수 |
|---|---|
| 2025 | 1 |
| 2021 | 2 |
| 2020 | 1 |
| 2019 | 3 |
| 2018 | 4 |
| 2016 | 3 |
| 2013 | 8 |
| 1943 | 37 |

**사실상 전부 역사적 데이터**(Getty PI는 1911~1940년대 세일 카탈로그 중심)이고, 2010년대
이후는 Wikidata에서 우연히 들어온 낱건뿐이다. 사용자가 중시하는 "지금도 롤링되는 최근
낙찰 기록"은 **dorotheum.com에만 있고, 그게 정확히 금지된 대상**이다. 즉 이 소스에서
최신성을 얻을 합법적 경로가 없다 — `refresh_weekly.ps1` 연결 대상에서 **영구 제외**.

## 결론 및 후속 처리

- **판정: 불가(제외).** Gagosian(AI봇 명시 차단)·Hauser & Wirth(봇 차단 우회 불가)·
  신와옥션/Van Ham(그레이존 보류)과 같은 제외 목록에 올린다. 다만 Dorotheum은
  **그레이존이 아니라 명시적 금지**라 재검토 여지가 없다 — 향후 세션이 "오스트리아가
  비어 있네"라고 다시 집어들지 않도록 이 문서를 근거로 남긴다.
- **적재 건수: 0건** (파일럿 수집 자체를 하지 않음).
- **기존 6,888건은 유지** (Getty PI/Wikidata 출처, 약관 무관).
- 재검토가 가능해지는 유일한 조건: Dorotheum의 **명시적 서면 동의**(약관 제4조가
  "without the express written consent of Dorotheum"이라고 직접 열어둔 경로). 사용자가
  원하면 `presse@dorotheum.at` 등으로 데이터 이용 문의를 넣는 건 별개 트랙이다 —
  **이건 사용자 결정 사항**이라 이 세션에서 진행하지 않았다.

### 다음 후보 (같은 세션에서 이어서 훑음)

Dorotheum이 빠지면서 오스트리아가 비어, 사용자 지침("금지 하나 찾으면 또 다른 데 훑고")대로
같은 세션에서 대체 후보를 조사했다 — 아래 **Auktionshaus im Kinsky 절 참고(판정: 가능)**.

그 외:
- **Getty Provenance Index 증분** — 이미 적법하게 쓰고 있는 소스라 마찰이 없다. 다만
  역사 데이터라 최신성 기여는 없음.
- Dorotheum 최신 낙찰가를 굳이 노린다면 **Wikidata 경매 경로**(`crawlers/auctions.py`,
  CC0)가 유일한 합법 통로다 — 다만 커버리지가 희박(27건)해 실익이 적다.
- `www.wienerkunstauktionen.com` — **DNS 해석 실패**(도메인 소멸 추정). 별도 확인 필요.

---

# [대체 후보] Auktionshaus im Kinsky (빈, 오스트리아) — 2026-09-23

## 판정: **가능 — 착수 권장 (이 세션에서는 타당성 검증까지, 파일럿 적재는 미실시)**

Dorotheum이 막힌 자리를 메울 오스트리아 소스. **1997년 설립, 빈 Palais Kinsky 소재,
오스트리아 미술 전문 경매사**(Klimt·Schiele·Lassnig·Hundertwasser 등 오스트리아 근현대
강세). Dorotheum이 종합경매사(보석·시계·자동차 혼재)인 것과 달리 **부서가 전부
미술**이라 스코프 적합도가 오히려 더 높다.

### 1. robots.txt (2026-09-23 직접 GET, 200)

표준 Drupal robots.txt. `/admin/`, `/user/*`, `/core/`, `/profiles/`, `/search/` 등
운영 경로만 차단하고 **경매결과 경로(`/ergebnisse/`, `/en/auction-results/`)는 제한 없음**.
AI봇 지목 차단·`Content-Signal` 없음.

유일한 콘텐츠 차단은 `Custom Paths` 2줄:
```
Disallow: /ergebnisse/139/723/2/94833
Disallow: /en/auction-results/139/723/2/94833
```
**단일 로트 하나**만 콕 집어 막아둔 것인데, 실제로 GET하면 **현재 404**다(양쪽 언어 모두
확인). 이미 내려간 페이지의 잔존 엔트리로 보인다 — 크롤링 정책상 의미 있는 제약이 아니다.
다만 **이 2개 URL은 코드에서 명시적으로 스킵**하는 게 맞다(robots 존중).

### 2. ToS 전수 검색 — 금지 조항 **없음**

im Kinsky는 별도 "웹사이트 이용약관" 페이지 자체가 없고, 법적 고지가 흩어져 있다. 홈페이지·
푸터에서 법률 관련 링크를 자동 수집해 전부 받아 태그 제거 후 정규식 전수 검색했다
(`crawl|scrap|spider|harvest|robot|data ?min|text and data|automat|TDM|96/9|2019/790|
sui generis|datenbank|database|index|extract|vervielf|reproduc|KI|artificial intelligence|
künstliche intelligenz|machine learning|42h|urheberrecht|copyright|privater gebrauch|
personal use|kommerziell|commercial`):

| 문서 | URL | 결과 |
|---|---|---|
| 개인정보(DE) | `/datenschutz` | **검출 0** |
| 개인정보(EN) | `/en/privacy-notice` | **검출 0** |
| 임프린트(DE/EN) | `/impressum`, `/en/impressum` | **검출 0** |
| 수수료·경매조건 | `/en/fees-and-conditions` | **검출 0** |
| 철회권 | `/widerrufsrecht` | **검출 0** |

**Dorotheum과 정반대다.** EU/오스트리아 사이트라 특히 겨눠 찾은 **sui generis 데이터베이스권
(96/9/EC), DSM 지침 Art.4 TDM 옵트아웃, § 42h UrhG 유보가 전혀 없다.** `/en/fees-and-conditions`는
낙찰수수료·추급권(droit de suite)·보험·연체이자 등 **순수 거래조건**일 뿐이다. Bukowskis와
같은 **중립(무금지)** 상태로 판정한다.

> 추출이 JS 게이트에 막힌 게 아니라 실제 SSR 본문임을 확인했다(임프린트에서 FN 34302 w,
> GISA 24265133, 대표 Michael Kovacek·Dr. Ernst Ploil 등 실제 텍스트 확인).

### 3. 기술 구조 — 완전 SSR, WAF 없음

Dorotheum과 달리 **Cloudflare 챌린지가 없다**. 평범한 `Invoke-WebRequest`/`urllib`로 200이
떨어진다. URL 구조:

| 패턴 | 의미 | 예 |
|---|---|---|
| `/en/auction-results/<auction_id>` | 세일 인덱스(부서별 세션 목록 + 날짜) | `/en/auction-results/139` → "Results Big Summer Auction 2022" |
| `/en/auction-results/<auction>/<dept>/<n>/<lot_id>` | **로트 상세** | `/en/auction-results/100/439/7/55615` |
| `/en/artists/<artist_id>` | 작가 페이지 | `/en/artists/86236` |
| `/ergebnisse/...`, `/kuenstler/...` | 독일어 동일 구조 | — |

**로트 상세 페이지 하나에 필요한 게 전부 평문으로 들어 있다**(표본 3건 직접 확인):

```
Auction: Modern Art | 13. May 2014, 5:00 pm
Lot no. 0048
Medardo Rosso (Turin 1858 - 1928 Mailand)
„Aetas Aurea (The Golden Age)“ | circa 1902 | bronze, marble socle
H. 52.5 cm (with socle); H. 60.1 cm (without socle)
Estimate: € 50.000 - 100.000
Realized price: € 358.400 (incl. fees and Austrian VAT)
Hammer Price: € 280.000
```

- **작가명 + 생몰(도시 포함)** — `artists` 백필에 바로 쓸 수 있는 품질
- **추정가 low–high**, **낙찰가(Hammer Price)**, 수수료 포함가(Realized price) **분리 제공**
  — 이 프로젝트가 `auction_lots.hammer_price` / `estimate_low` / `estimate_high`에 요구하는
  그대로다. 유찰이면 Hammer Price 줄이 없다(Bukowskis와 같은 패턴).
- **Provenance 원문**(표본 2번 Bellotto 로트: 1850년대 영국 개인소장 → Otto Hirsch →
  Haberstock → Führermuseum(Linz) …) — `provenance_records`/`collectors` 보강에
  쓸 수 있는 **부가 가치**. NGA `provenancetext` 후처리(`provenance_extract.py`)와 같은
  경로를 태울 수 있다.
- `▲`(정상과세) 표시, `*`(추급권 대상) 표시도 평문으로 구분됨.

### 4. 최신성 — **롤링 중, 주간 잡 연결 가능**

`auction_id` 스윕으로 확인:

| auction_id | 세일 | 날짜 |
|---|---|---|
| 139 | Big Summer Auction 2022 | 2022-06-28 ~ 06-30 |
| **150** | (2025 세일) | **2025-06-16 ~ 06-17** |
| 160+ | 404 (아직 없음) |

**id 150이 2025년 6월** — 즉 **지금도 계속 새 세일이 붙는 살아있는 소스**다. Dorotheum이
막혀 못 얻은 "최신성"을 이쪽이 대신 채울 수 있다. `refresh_weekly.ps1`에 **"마지막 성공
auction_id+1부터 404 날 때까지 증분 탐색"** 패턴으로 붙이면 된다(404가 결정론적 종료
신호라 구현이 단순하다).

연 단위로 id가 촘촘하지 않고(2022→139, 2025→150) 세일 하나가 부서별 세션 여러 개로
쪼개지므로, **세일 인덱스(`/en/auction-results/<id>`)를 먼저 긁어 부서 세션 목록과 날짜를
얻고 → 각 세션의 로트를 도는** 2단 구조가 맞다.

### 5. 이 세션에서 **하지 않은 것** (다음 세션 인계)

타당성 검증까지만 했고 **크롤러·로더 작성과 DB 적재는 하지 않았다**(이번 과제 범위가
Dorotheum이었고, `pipeline/run.py` 등 공용 파일은 동시 작업 충돌 방지 대상이라 새 소스
배선은 담당 세션이 하는 게 맞다고 판단). 인계 사항:

1. `crawlers/imkinsky.py` 신규 — `save_raw`/`already_fetched`/`with_retry` 재사용,
   상단에 `sys.stdout.reconfigure(encoding="utf-8")`. 2단 구조(세일 인덱스 → 로트).
   robots.txt의 `.../139/723/2/94833` 2개 URL은 명시 스킵.
2. 로트 상세가 **로트당 1요청**이라 Bukowskis의 그리드(100건/페이지)보다 비싸다 —
   `DELAY` 넉넉히 두고 백그라운드 장시간 전제로 설계할 것. 세일 인덱스에서 로트 수를
   미리 세어 규모를 추정한 뒤 착수 권장.
3. 적재는 `pipeline/_scratch/load_imkinsky_*.py`로 시작하고, 안정되면 정규 로더로 승격.
   `get_or_create_artist_safe` 사용(동시 세션 경쟁조건).
4. **`auction_houses` 중복 확인은 이 세션에서 이미 해뒀다** — `name ilike '%kinsky%'`,
   `'%wiener%'` 조회 결과 **0건**(현재 738개 행 기준, 2026-09-23). Dorotheum과 달리
   Getty PI 경유로도 들어와 있지 않은 **완전 신규 경매사**다. 새로 만들되 Wikidata QID
   (`Auktionshaus im Kinsky`)를 같이 채워 넣을 것 — 병합은 authority ID 정확일치만.
5. 이미지는 수집하지 않는다(다른 경매사와 동일한 보수적 기본값).
