# Lyon & Turnbull(에든버러/영국) 경매 확장 — 2026-09-22

## 최종 판정: **가능 — 착수 완료**

## 조사 근거

- **robots.txt**(`https://www.lyonandturnbull.com/robots.txt`, 직접 확인):
  ```
  User-agent: *
  Disallow: /account/
  Disallow: /auth/
  Disallow: /search
  Disallow: /collection_story
  Disallow: /collection_event
  Disallow: /collection_location
  ```
  과거경매 목록(`/auctions/past-auctions`)과 개별 경매 상세(`/auctions/<slug>`)는 제한에
  걸리지 않는다. `User-agent: *`에는 crawl-delay 명시가 없음(SemrushBot/SiteAuditBot에만
  `Crawl-delay: 5`) — 지시서의 최소 기준대로 1.5초 간격을 지켰다.

- **이용약관** 전문 확인(2026-09-22):
  - `/terms`(Website Terms of Use, 정제 후 약 4,850자) — "Acceptable Use" 조항은 스팸·보안
    침해·명예훼손·바이러스 유포 등을 금지할 뿐, crawling/scraping/spidering/robot/harvest/
    data mining/automated collection/personal-non-commercial-only 키워드는 **전혀 없음**.
    저작권 조항(웹사이트 콘텐츠는 Lyon & Turnbull 소유, 재사용 시 출처 표시)만 있음.
  - `/conditions-of-sale`(경매 매매조건, 약 71,000자) — 마찬가지로 크롤링/스크래핑/데이터
    마이닝/데이터베이스권 관련 조항 없음(입찰·낙찰·보증 등 거래 조건 중심 문서).
  - `/privacy` — 관련 조항 없음.
  - Sworders·Grisebach·칸옥션과 같은 패턴: robots 통과 + ToS 3종 전문에 금지 조항 없음
    → 오늘 이 프로젝트의 기준대로 진행 가능 판정.

- **구조**: Next.js SSR 사이트. `/auctions/past-auctions` 페이지의 `__NEXT_DATA__` 스크립트
  안에 **과거 경매 310건 전체가 페이지네이션 없이 한 번에** 들어있다(연동 크롤링 불필요).
  개별 경매 페이지(`/auctions/<slug>`)의 `__NEXT_DATA__.props.pageProps.lots` 배열에는
  로트별 lot_no/title/dynamic_fields.sub_title/low/high/hammer_price/status(sold/unsold)가
  **서버가 이미 구조화한 JSON**으로 들어있다 — HTML 정규식 파싱이 필요 없고, 스크립트 태그
  안의 JSON 텍스트를 원문 그대로 저장하면 그게 곧 raw 원본이다. 통화는 전부 GBP(£).

## 만든 것

- `crawlers/lyonandturnbull.py` — 2단계(`list`/`sales`), `common.py`의 save_raw/
  already_fetched/with_retry 재사용, UA `Mozilla/5.0 (artgraph-research-bot)`, 요청 간
  1.5초 딜레이, 이미지 수집 안 함(사실 데이터만 저장).
- `pipeline/lyonandturnbull.py` — 로더. `get_or_create_artist_safe`/`insert_auction_lot_batch`
  사용. 작가는 `title.en`이 "이름 (국적 YYYY-YYYY)" 형태로 끝날 때만 후보로 보고, 다음은
  보수적으로 스킵: 공동작가("AND"), 귀속 한정어(after/attributed to/circle of/manner of/
  school of/studio of/style of — 문중 어디에 있든), 설명문 스타일(A/An/The로 시작 또는
  60자 초과 — 장식미술·가구 자연 배제), 이름에 숫자 포함(상품명 오탐 방지, 실측: "LAPHROAIG
  15 YEAR OLD (1990)"을 사람으로 오인할 뻔한 걸 이 규칙으로 잡음), 불확실한 연대 표기
  (ca./ac./circa/fl./"C1685"류 마침표 없는 circa 축약 — 실측: "CHRISTIAN FRIEDRICH ZINCKE
  (GERMAN C1685-1767)"). 이름/존칭은 그대로 저장(이름 유사도 병합 금지 원칙).

  **알려진 한계**: 같은 인물이 경매마다 존칭 나열 순서가 달라 서로 다른 artists 행으로 들어갈
  수 있음(예: "ANNE REDPATH O.B.E., R.S.A., A.R.A., A.R.W.S., ..." vs 존칭 순서만 다른 버전).
  이름 유사도 병합은 프로젝트 정책상 금지라 자동 정리하지 않았다.

## 파일럿 실행 결과

- `python crawlers/lyonandturnbull.py --phase list` → 과거 경매 310건 목록 저장.
- `python crawlers/lyonandturnbull.py --phase sales --max-sales 8` → 임의 8개 경매(로트
  1,860건) 저장.
- `pipeline/_scratch/load_lyonandturnbull_20260922.py`로 적재 → **230건 적재**(작가 없음/
  유찰 등 스킵 1,630건, 세일 8개). SELECT 표본 확인 완료 — 낙찰가 최고 £130,000
  (John William Waterhouse, "MIRANDA", 2026-07-02) 포함 정상 적재. 기존 Wikidata 소스가
  이미 만들어 둔 "Lyon & Turnbull" auction_houses 행을 정상적으로 재사용(중복 생성 안 함).
  일부 작가명이 기존 DB의 다른 대소문자 표기와 case-insensitive 매칭으로 재사용된 것도 확인
  (project 기존 정책대로 정상 동작).

## `pipeline/run.py`에 추가할 한 줄

```python
"lyonandturnbull": lyonandturnbull,
```
(다른 사이트 로더들과 같은 위치의 dict/if-분기에, `import lyonandturnbull` 추가와 함께 —
정확한 삽입 지점은 `pipeline/run.py`의 기존 사이트 등록 패턴을 따르면 됨. 이 세션은
`pipeline/run.py` 편집 금지 지시라 실제 수정은 하지 않았다.)

## 후속 과제(전체 수집 시 참고)

- 과거 경매 310건 전체를 `--phase sales`(max-sales 없이)로 돌리면 1.5초 간격 기준 약
  8분 내외(요청 자체는) — 다만 사이트 응답 지연 포함하면 더 걸릴 수 있음.
- 존칭 순서 차이로 인한 동일 인물 중복 artists 행 — authority-ID(ULAN/Wikidata) 기반 병합
  대상으로 남김(이름 유사도 병합은 금지).
