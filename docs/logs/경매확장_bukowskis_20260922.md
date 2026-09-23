# Bukowskis(스웨덴, 북유럽) 착수 기록 — 2026-09-22

`docs/경매소스확장_20260922.md`가 오늘 이 프로젝트가 적용해 온 판정 기준(robots.txt
통과 + ToS 명시 허용/무금지 둘 다 확인해야 진행)을 그대로 적용했다. 배경: 독일
(Grisebach 성공)·한국(칸옥션/K-ARTMARKET)·일본(Kogire-kai)·영국/미국(Phillips
부분성공)은 훑었지만 북유럽(스칸디나비아)은 미착수였다 — 이번에 Bukowskis
(bukowskis.com, 스웨덴, 북유럽 최대급 경매사, Bonhams 그룹 계열)를 조사·착수했다.

## 판정: 가능 — 착수 완료

### 1. robots.txt (2026-09-22 직접 GET 확인)

```
User-agent: *
Disallow: /admin/
Disallow: /cms/
Disallow: /*/pdf$

Sitemap: https://www.bukowskis.com/sitemaps/sitemap.xml.gz
```

경매/로트 경로에 아무 제한이 없다. `the-saleroom.com`류의 명시적 금지도, Grisebach처럼
`anthropic-ai`/`ClaudeBot`을 이름으로 지목한 명시 허용도 없는 **중립** 상태 — 다만
차단 목록이 전혀 없다는 것 자체가 우호적 신호다.

### 2. 이용약관 전문 확인 — 4개 문서, 금지 조항 전혀 없음

Bukowskis는 별도의 "웹사이트 이용약관(website ToU)"이 없고, `/legal` 허브 페이지가
구매/판매약관·배송약관·개인정보처리방침으로 흩어져 있다. 실제 GET으로 받아 태그를
제거한 순수 텍스트에서 `crawl|scrap|spider|harvest|data ?min|robot|automat(ed|ic)
(means|tool|access)|extract|database right|sui generis` 정규식으로 전수 검색했다:

| 문서 | URL | 결과 |
|---|---|---|
| 구매약관(온라인 경매) | `/en/tos` | 검출 없음 |
| 구매약관(라이브 경매) | `/en/help/buyer_terms/hammer` | 검출 없음 |
| 판매약관(온라인 경매) | `/en/help/seller_terms/online` | 검출 없음 |
| 개인정보처리방침 | `/en/privacy` | 검출 없음 |

**스웨덴/EU 사이트라 특히 주의해서 찾은 sui generis database right(EU Directive
96/9/EC) 조항도 전혀 없다** — Artcurial(B-5절, 프랑스 데이터베이스권 조항 흔함)과
달리 Bukowskis 약관에는 그 자체가 없다. "IMAGE REPRODUCTION" 조항(구매약관
17조/판매약관 12조: "Bukowskis has the right to photograph or otherwise depict
Items…")은 Bukowskis 자신이 찍은 사진의 저작권을 스스로 유보하는 조항일 뿐 — 칸옥션
제7조③과 동일 성격이라 **이미지는 수집하지 않는 것으로 지켰다**.

### 3. 구조 확인 — 완전 SSR, 그리드 페이지 하나로 낙찰가까지 다 나온다

개별 로트 상세 페이지(`/en/lots/<id>-<slug>`, `/en/auctions/<id>/<lot>-<slug>`)도
SSR이지만(예: Damien Hirst 로트에서 "Hammer price 50 000 SEK", "Estimate 80 000 -
100 000 SEK"를 직접 GET으로 확인), **더 좋은 경로**를 찾았다 — 세일 단위 로트 그리드
`/en/auctions/<auction_id>/lots/page/<N>`(100로트/페이지)가 로트 하나하나를 개별
요청할 필요 없이 그 안에 이미 낙찰가·추정가까지 평문으로 들어 있다(Grisebach의
list 페이지와 같은 패턴, Lempertz처럼 로트별 개별 요청이 강제되는 구조가 아니다).
그리드 항목 하나(`data-lot-id="..."`)의 필드:

- `c-lot-index-lot__catalogue-number` — 로트번호
- `c-lot-index-lot__artist` — 작가명(단, 가구/장식은 설명 문장의 앞부분이 들어온다 — 아래 참고)
- `c-lot-index-lot__title` — 작품명/설명 나머지
- `c-lot-index-lot__result-value` — "16 000 SEK"(낙찰가, 유찰이면 없음)
- `c-lot-index-lot__estimate-value` — "30 000 - 40 000 SEK"(추정가, 단일값도 있음)

페이지네이션은 `/lots/page/N` 경로 기반이고 범위를 벗어나면 200 + 로트 0건으로
응답한다(에러 아님 — Grisebach의 "0건이면 마지막 페이지" 패턴 그대로 씀).

### 4. 규모 — sitemap 기반

`sitemaps/sitemap.xml.gz` → `archived_lots0~88.xml.gz`(89개 샤드)가 sv/en/fi 3개
언어 URL 합쳐 약 190만 loc, 언어당 약 63만 로트. 이 로트들이 속한 **고유 auction_id는
2,121개**(2026-09-22 집계).

auction_id 접두사별 분포(2,121개 중):

| 접두사 | 개수 | 실제 성격(표본 확인) |
|---|---|---|
| E | 1,257 | 온라인 상시경매. 표본은 유리공예(Orrefors 등) 등 혼재 |
| F | 682 | 온라인/피처드 경매. 시계·도자기·가구와 **순수미술이 섞여 있음**(에스토니아 화가 Leonhard Lapin, Evald Okas 등 확인) |
| (숫자) | 122 | **Live "Important/Fine Art" 세일** — Zorn·Strindberg·Warhol·Klein·Hockney 등 고가 순수미술 다수 확인 |
| H | 26 | 디자인 가구 전문(Svenskt Tenn/Josef Frank 표본 확인) — 미술 아님 |
| S | 23 | 명품 가방/시계(Louis Vuitton 표본 확인) — 미술 아님 |
| G | 10 | 은제품/보석(표본 확인) — 미술 아님 |
| V | 1 | 패션/의류(표본 확인) — 미술 아님 |

**스코프 판단**: H/S/G/V(도합 60개, 가방·시계·은제품·패션·가구 전문)는 이번 착수에서
제외한다 — Bonhams WOA(가구/장식) 제외와 같은 논리. E(1,257개)는 표본이 유리공예·
일상 소품 위주라 우선순위를 낮췄다(전량 배제는 아니고, 이번 1차 착수에서는 시간상
숫자형(122개)·F(682개) 두 그룹만 돌렸다 — 아래 "다음 단계" 참고).

### 5. 로트 단위 스코프 판단 — 부서 코드가 없어 텍스트 휴리스틱으로 근사

본햄스는 `department.code`로 가구/장식(WOA)을 걸러냈는데, Bukowskis 그리드에는
그런 코드가 없다. 대신 표본을 눈으로 확인해 다음 휴리스틱을 세웠다(`pipeline/
bukowskis.py`의 `_looks_like_artist`):

- 실제 작가명은 그리드에서 **쉼표·마침표 없이 끝난다**("Damien Hirst", "Yves Klein",
  "Arman (Armand Pierre Fernandez)", "Nathalie Djurberg & Hans Berg")
- 가구/장식 설명은 앞부분이 "artist" 필드에 들어오는데 **항상 쉼표나 마침표로
  끝나며 title 필드로 문장이 이어진다**("A Swedish late baroque burr-alder
  cabinet," + "first part 18th century.")
- 부정관사/수량사로 시작하는 경우(A/An/The/Two/Pair/Set/Group/…)도 추가로 걸러낸다

이 휴리스틱을 통과 못 하면 **그 로트는 적재하지 않는다**(작가 미상으로 남기는 게
아니라 가구/장식으로 보고 스킵 — 칸옥션의 "작자미상 고미술 유지" 방침과 다르게 간
이유는, 칸옥션은 애초에 미술품경매 전문이라 무작가 로트도 스코프 안이지만 Bukowskis는
본햄스처럼 종합 경매사라 부서 필터가 필요하기 때문). **한계**: 텍스트 근사치라
"A. Munthe" 같은 이니셜 포함 이름이나 마침표로 끝나는 진짜 작가명이 있다면 오탐(과
배제)될 수 있다 — 정밀 분류가 필요해지면 로트 상세 페이지의 카테고리 브레드크럼
(`/lots/category/<id>-<slug>`)을 활용하는 방법이 있다(다만 그리드 방식의 "1페이지에
100건" 효율을 포기하고 로트별 개별 요청이 필요해진다).

## 파일럿 실행 결과 (2026-09-22)

`crawlers/bukowskis.py --phase grid --auction-id 654 --auction-id 673
--auction-id F533` (3개 세일, 19페이지) → `pipeline/_scratch/
load_bukowskis_20260922.py`로 적재:

```
[pipeline:bukowskis] 655건 적재, 유찰 스킵 464건, 작가 미확인(가구/장식 추정) 스킵 685건, 세일 3개
```

SELECT 표본(낙찰가 내림차순 상위):

| 작가 | 작품명 | 낙찰가 |
|---|---|---|
| Anders Zorn | "Hämta vatten" ("The Water Pails") | 12,500,000 SEK |
| August Strindberg | "Enslingen" ("The Solitary One") | 8,700,000 SEK |
| Joachim Beuckelaer | A fish market outside the city gate of Antwerp | 5,900,000 SEK |
| Alex Katz | 'Cane Garden Bay 2' | 5,600,000 SEK |
| Carl Larsson | "Häxans dotter" | 2,250,000 SEK |
| Yves Klein | 'Untitled Blue Monochrome (IKB 327)' | 1,950,000 SEK |
| Andy Warhol | 'Venus', from Details of renaissance paintings | 1,250,000 SEK |
| Helene Schjerfbeck | "Dam vid spinnrocken" | 1,650,000 SEK |

세일 654("Contemporary Art & Design Spring 2024")·673("Important Spring Sale
Spring 2026")·F533에서 나온 데이터로, 이전 조사(`docs/경매소스확장_20260922.md`)에서
뉴스 기사가 언급했던 "Scandinavian Beauty II by Andy Warhol", Zorn "Hämta vatten",
Strindberg "Enslingen" 같은 고가 낙찰이 실제로 확인된다.

## 다음 단계 (이번엔 일부러 안 한 것)

1. **auction_id 2,121개 중 숫자형(122개)+F(682개)=804개 전체 크롤** — 파일럿
   3개(19페이지) 이후, 나머지 801개 세일에 대해 `crawlers/bukowskis.py --phase
   grid`(전체 auction_id 목록 자동 로드)를 백그라운드로 계속 돌리는 중
   (아래 "실행 상태" 참고). 완료되면 `pipeline/run.py --site bukowskis` 1회 실행으로
   전량 적재하면 된다(로더가 idempotent — `sources.raw_path` 유니크 인덱스로 재적재
   스킵).
2. **E(1,257개) 착수 여부** — 표본이 유리공예·일상소품 위주였으나 전수 확인은 아니다.
   순수미술이 섞여 있을 가능성이 있어 필요하면 후속 세션이 표본을 더 넓게 확인 후
   판단.
3. **로트 스코프 휴리스틱 정밀화** — 위 5번 항목의 오탐 가능성. 필요해지면 카테고리
   브레드크럼 기반으로 전환.
4. 이미지는 여전히 수집하지 않는다(약관 17/12조 때문).

## 실행 상태 메모 (이 세션 종료 시점, 2026-09-22)

- auction_id 전체 목록(`crawlers/raw/bukowskis/_auction_ids.txt`, 2,121개)과 필터된
  숫자형+F 목록(`crawlers/raw/bukowskis/_auction_ids_fineart.txt`, 804개)을
  `--phase auction-ids` + 수동 필터로 생성 완료.
- 파일럿(654/673/F533, 3개 세일 19페이지) 이후, `--ids-file _auction_ids_fineart.txt`로
  나머지 801개 세일 전체 그리드 크롤을 백그라운드로 계속 돌렸다. **세션 종료 시점까지
  4개 세일(301/553/554/555) 추가 완료 확인**(파일 개수로 직접 검증, 로그만 신뢰하지
  않음 — `ls crawlers/raw/bukowskis/*.html | wc -l`로 실측). 나머지 797개 세일은
  미완료 — 이 크롤은 서브에이전트 세션과 함께 죽을 수 있어(과거 사례 있음)
  **재개 세션이 살아있는지 먼저 확인하고, 죽었으면 아래 명령으로 이어서 돌려야 한다**:
  `python crawlers/bukowskis.py --phase grid --ids-file crawlers/raw/bukowskis/_auction_ids_fineart.txt`
  (already_fetched 기반이라 이미 받은 페이지는 건너뛰고 이어서 받는다. 완료까지
  숫자형 122개는 세일당 페이지 수가 커서 — 표본 3·13·16·14페이지 — 전체 3~4시간
  가량 걸릴 수 있다는 게 이번 세션에서 관측한 추정치다.)
- **DB 적재는 이 세션에서 두 차례(파일럿 직후 + 추가 4개 세일 이후) 실행해 반영을
  완료했다** — `pipeline/_scratch/load_bukowskis_20260922.py`(idempotent, 몇 번을
  다시 돌려도 안전). 최종 확인(2026-09-22 세션 종료 시점):

  | 지표 | 값 |
  |---|---|
  | auction_lots(Bukowskis) | 2,376건 |
  | auctions(세일) | 8개 |
  | distinct artist | 994명 |

  나머지 크롤이 이어지면 같은 스크립트를 다시 돌리면(`sources.raw_path` 유니크 인덱스로
  이미 적재분은 자동 스킵) 새로 받은 페이지만 추가 적재된다.

## 2026-09-23 재개 — pgportable 재기동 후 이어받기 + 레이트리밋 대응 튜닝

**배경**: 2026-09-22 세션 종료 후 pgportable(로컬 DB)이 밤새 죽으면서 그와 함께 돌던
백그라운드 크롤(`--ids-file _auction_ids_fineart.txt`)도 중단됐다(정확한 원인은 네트워크
DNS 해석 실패 — `[Errno 11001] getaddrinfo failed` — 로 로그에 남아 있고, 이 프로젝트가
과거에도 겪은 "PISupervisor.exe 크래시루프 상관관계" 패턴과 일치). 좌표 세션이 pgportable을
재기동했고, 이 세션이 이어받았다. **DB의 적재분(2,376건)은 pgportable이 죽어도 보존돼
있었다** — Postgres 자체 durability 덕분, 별도 조치 불필요.

### 새로 발견한 문제 — `/lots/page/N` 경로의 간헐적 403

크롤을 재개하자(801개 세일 중 이미 131개까지 진행했던 지점부터) `/en/auctions/<id>/lots/page/<N>`
경로에서 **간헐적 403 Forbidden**이 나타났다. 직접 조사한 결과:

- **완전한 IP 차단은 아니다** — `robots.txt`와 다른 페이지(`/lots`, 다른 auction_id의
  `/lots/page/N`)는 403이 뜨는 동안에도 계속 200을 반환했다.
- **결정론적 "세일 끝" 신호도 아니다** — 처음엔 "혹시 세일이 실제로 그 페이지에서
  끝나서 그런가" 의심했는데, 실패했던 `auction F165`의 4~5페이지를 잠시 후(몇 분 뒤)
  처음부터 재수집해보니 **실제로는 7페이지까지 전부 정상적으로 존재**했다. 즉 **일시적·
  간헐적 레이트리밋**으로 판단한다 — 봇 차단 의사 표시가 아니라 순수 트래픽 제어로 보인다
  (그렇다고 우회 대상은 아니다 — robots.txt·ToS가 여전히 허용하는 자원을 정상 속도로
  받는 것뿐).
- 대응: `crawlers/bukowskis.py`의 `DELAY`를 1.5초 → 3.0초로 올리고, 그리드 페이지
  요청의 재시도/포기 기준을 튜닝했다(자세한 트레이드오프는 코드 내 주석 참고) —
  **재시도 3회(최대 35초)까지만 시도하고, 한 세일이 연속 2페이지 실패하면 그 세일을
  포기하고 다음으로 넘어간다**(기존 5회 재시도·5페이지 연속실패 기준은 막힌 세일 하나당
  최악 13분까지 걸려 804개 세일 전체를 도는 게 비현실적이었다). **트레이드오프**: 막힌
  세일의 뒤쪽 몇 페이지(진짜 로트가 있을 수 있음)를 놓칠 수 있다 — Grisebach가 약 2%를
  같은 이유로 후속 과제로 남긴 것과 같은 성격의, 의도적으로 받아들인 손실이다. 특정
  세일을 나중에 다시 노리려면 `--auction-id <id> --no-skip-existing`로 재수집하면 된다
  (F165가 실제로 이 방법으로 7페이지 전부 회수됐다).

### 진행 상황 (이 세션 기준 스냅샷, 2026-09-23)

크롤은 **여전히 백그라운드에서 실행 중**이다(801개 세일 중 순차 진행). 안전하게
검증 가능한 지표(파일 개수 직접 세기 + DB 재적재)로 스냅샷:

| 지표 | 값 |
|---|---|
| 저장된 그리드 페이지 파일 수 | 1,047 |
| 페이지가 하나라도 있는 세일 수 | 139 / 804 |
| auction_lots(Bukowskis, DB) | **37,778건** |
| auctions(세일, DB) | 120개 |
| distinct artist(DB) | 5,168명 |

DB 적재는 idempotent 로더(`pipeline/_scratch/load_bukowskis_20260922.py`)를 이 세션에서도
재실행해 반영했다 — 몇 번을 다시 돌려도 안전하니, 크롤이 더 진행된 뒤 다시 돌리면
새로 받은 페이지만 추가 적재된다.

**세션 종료 시점에도 크롤은 미완료다** — 외부 사이트의 간헐적 레이트리밋 특성상 804개
세일 전체를 도는 데 몇 시간이 걸릴 것으로 추정된다(이 세션에서 실측한 속도 기준). 다음
세션/재개 시:

1. 프로세스가 살아있는지 먼저 확인(`Get-Process`류로 `bukowskis.py` 커맨드라인을 가진
   python3 프로세스가 있는지) — **subagent 세션이 끝나면 그 세션이 띄운 백그라운드
   작업이 함께 죽을 수 있다**는 이 프로젝트의 기존 교훈이 이번에도 재현됐다(2026-09-22
   야간 pgportable/네트워크 장애로 실제 발생).
2. 죽었으면 그대로 재실행: `python crawlers/bukowskis.py --phase grid --ids-file crawlers/raw/bukowskis/_auction_ids_fineart.txt`
   (already_fetched 기반이라 이어받는다).
3. 완료 후(또는 중간에라도) `pipeline/_scratch/load_bukowskis_20260922.py`를 다시 돌려
   DB에 반영.
