# Auctionet(auctionet.com) 착수 기록 — 2026-09-23

`docs/경매소스확장_20260922.md`가 세운 판정 기준(robots.txt 통과 + **ToS 전문 직접 확인**에서
금지 조항 없음, 둘 다 만족해야 진행)을 그대로 적용했다.

배경: Setdart/Balclis(스페인) 조사 중 **Balclis의 실제 입찰이 auctionet.com에서 돌아간다**는
사실을 발견해 역추적했다. Auctionet은 북유럽을 중심으로 한 **온라인 경매 애그리게이터**로,
단일 소스로 여러 경매사 커버리지 + 높은 최신성을 동시에 얻을 수 있는지 확인이 목적이었다.

## 판정: **가능 — 파일럿 적재 완료. 전량 백필은 규모가 커서 사용자 결정 대기**

---

## 1. 구조 — 애그리게이터이므로 "경매사"를 어떻게 다룰지가 첫 판단

Auctionet은 **경매사가 아니다**. Auction Network Sweden AB(reg. 556859-5150, Grev
Turegatan 44, Stockholm)가 운영하는 **온라인 마켓플레이스**이고, 실제 판매자는 입점
경매사다. ToU 서두가 이걸 명시한다:

> "Auctionet is only a provider of the Service and administrator of the Platform.
> Auctionet shall by no means be regarded as seller of the Auction Items ... the Customer
> will enter into a binding purchase agreement regarding the Auction Item with the specific
> Auction House"

각 경매는 **입점 경매사의 실물 경매장에서도 동시에 열린다**("Each auction is also held on
the premises of each Auction House").

### 결정: **Auctionet을 `auction_houses` 행으로 만들지 않는다**

로트마다 상세 페이지의 `House` 필드(개별 경매사)를 `auction_houses`로 쓰고, Auctionet은
`sources`(수집 출처)로만 남긴다. `pipeline/auctions.py`가 invaluable/artsy 같은
애그리게이터 도메인을 단일 경매사로 단정하지 않기로 한 것과 같은 원칙이다.
로트 상세 페이지의 `House`/`Address` 필드가 개최 경매사와 그 소재지를 그대로 주기 때문에
추측이 개입하지 않는다.

### 입점 경매사 86곳 (2026-09-23 `/en/auction_houses` + 각 경매사 페이지 전수 확인)

| 국가 | 경매사 수 | 원 통화 |
|---|---|---|
| Sweden | 59 | SEK |
| United Kingdom | 10 | GBP |
| Germany | 9 | EUR |
| Denmark | 4 | DKK |
| Spain | 3 | EUR |
| Finland | 1 | EUR |

목록·`company_id`(슬라이스 필터용)는 `crawlers/raw/auctionet_houses/_houses.json`에
저장했다. 규모가 큰 곳: **Stockholms Auktionsverk**(Fine Art/Magasin 5/Sickla/Göteborg/
Helsingborg/Helsinki/Köln/Düsseldorf/Hamburg 등 9개 지점), **Göteborgs Auktionsverk**,
**Uppsala Auktionskammare**, **Metropol Auktioner**, **Balclis**(스페인),
**Lawrences Auctioneers**(영국).

### 기존 DB와의 중복 — 전수 대조 후 1건만 매핑

DB의 `auction_houses` 740행 전체와 대조했다(토큰 교집합 기반 **후보 추출만**, 자동 병합 없음).

| Auctionet 표기 | DB 기존 | 판정 |
|---|---|---|
| `Lawrences Auctioneers` (Crewkerne) | `Lawrences Auctioneers of Crewkerne` | **동일 — 별칭 매핑**(소재지 일치) |
| `Young's Auctions` (Surrey) | `Young`, `Young (Hickman)` | **다름 — 매핑 안 함**. 뒤 둘은 Getty provenance 문자열에서 온 성씨 형태 |
| 나머지 84곳 | 동일·유사 후보 **0건** | 신규 생성 |

- **Bukowskis는 DB에 이미 있지만(`SE`) Auctionet 입점사가 아니다** — 충돌하지 않는다.
  (Bukowskis는 자체 플랫폼으로 운영한다. 스웨덴 계열이라 겹칠까 우려했으나 무관.)
- 별칭은 `pipeline/auctionet.py`의 `HOUSE_ALIAS`에 **손으로 확인한 것만** 넣었다.

---

## 2. robots.txt (2026-09-23 직접 GET 확인)

```
User-Agent: *
Disallow: /admin/
Disallow: /*/my$
Disallow: /*/my/*
Sitemap: https://auctionet-exports.s3-eu-west-1.amazonaws.com/sitemap.xml.gz
```

- 차단은 관리자(`/admin/`)와 **로그인 사용자 개인 영역**(`/*/my`)뿐. 검색·로트·경매사
  페이지는 전부 허용.
- **ClaudeBot/GPTBot/CCBot/Bytespider 등 AI 봇을 이름으로 차단하는 문구가 전혀 없다.**
  `Content-Signal: ai-train=no` 같은 헤더도 없다(Gagosian 제외 사유와 정반대).
- 응답 헤더 확인: `/en/search?...`에는 `x-robots-tag: noindex`가 붙지만 **로트 상세
  페이지에는 붙지 않는다**. 이건 필터 검색 결과를 색인에서 빼는 일반적인 SEO 처리이고
  크롤 금지가 아니다(로트 상세는 sitemap에도 올라와 있다).
- 봇임을 밝힌 UA(`Mozilla/5.0 (compatible; artgraph-research-bot)`)로도 200이 정상 응답된다
  (Cloudflare 앞단이 있으나 차단하지 않음). 크롤러는 이 UA를 쓴다.

---

## 3. ToS 전문 직접 통독 — **자동수집·재이용 제한 조항이 하나도 없다**

다른 에이전트 판단을 신뢰하지 않고 **영문·스웨덴어 전문을 직접 받아 태그 제거 후 통독**했다.

| 문서 | URL | 비고 |
|---|---|---|
| Terms of Use (영문) | `/en/terms_of_use` | 2026-06-23 발효 |
| Användarvillkor (스웨덴어) | `/sv/terms_of_use` | 같은 날짜·같은 조항 구조(1.1~1.11) |
| Terms of Purchase | `/en/terms_of_purchase` | 매매 조건 |
| Hammer auction terms | `/en/hammer_terms` | 현장 슬래그옥션 조건 |
| Privacy policy | `/en/privacy_policy` | GDPR 고지 |

전수 검색한 키워드(영/스웨덴어 양쪽):
`crawl|scrap|spider|robot|harvest|data ?min|datautvinning|text and data|databas|database|
database right|sui generis|96/9|2019/790|immateri|intellectual propert|upphovsr|copyright|
kopier|reproduc|extract|extrahera|systematisk|automatis|automated|personligt bruk|
personal use|non-commercial|icke-kommersiell|tredje part|third part|API`

**결과: 해당 금지 조항이 단 하나도 없다.** ToU는 다음만 다룬다 —
1.1 계정 등록 / 1.2 개인정보 / 1.3 로그인 관리 / 1.4 이용정지 / 1.5 보증부인 /
1.6 책임제한 / 1.7 통지 / 1.8 약관변경 / 1.9 자금세탁방지 / 1.10 제재 / 1.11 준거법.
**"콘텐츠 이용"이나 "acceptable use" 조항 자체가 존재하지 않는다.** `copyright`가
걸린 곳은 Terms of Purchase의 **추급권(droit de suite, EU 2001/84/EC) 수수료 설명** 하나뿐이고
데이터 이용과 무관하다. `automated`는 Privacy policy의 GDPR 자동화 의사결정 거부권 조항뿐.

### 오늘 다른 소스에서 걸렸던 패턴과의 대조

| 소스 | 막힌 조항 | Auctionet |
|---|---|---|
| Setdart / Balclis(자사 사이트) | 스페인 LSSI 보일러플레이트 "Independientemente de la finalidad ... requiere en todo caso de la autorización escrita previa"(목적 불문 사전 서면 동의 필요) | **해당 조항 없음** |
| Dorotheum | "prohibition of AI training / text and data mining" + DSM 지침 4조 TDM 옵트아웃 명시 | **TDM 옵트아웃 없음** |
| Auctionet | — | 자동수집 제한 조항 자체가 부재 |

**주목할 점: Balclis는 자사 사이트 ToS로는 막혔지만, 실제 입찰이 도는 Auctionet의
ToS에는 그 제한이 없다.** 같은 경매사의 같은 로트를 Auctionet 경로로는 합법적으로
수집할 수 있다. (수집한 것은 Auctionet이 자기 플랫폼에 공개한 로트 데이터이고,
`sources`에 auctionet.com URL로 출처를 남긴다.)

### EU 데이터베이스권(96/9/EC)에 대한 메모

스웨덴은 EU 회원국이라 sui generis 데이터베이스권이 자동 적용될 수 있다(약관에 없어도).
다만 이 권리는 **"상당한 부분의 추출·재이용"**에 걸리는 것이고, 이번 파일럿은 전체
3,946,061건 중 수백 건 규모다. **전량 백필(미술 74만 건)은 "상당한 부분" 논란의 여지가
있으므로 사용자 판단 항목으로 올린다**(아래 7절). 약관상 금지가 없다는 것과 데이터베이스권이
없다는 것은 다른 문제라 여기 명시해 둔다.

---

## 4. 사이트 구조 — 전부 SSR, 데이터가 프리하이드레이션 JSON으로 박혀 있다

화면은 React지만 **서버가 렌더한 HTML 안에 `data-react-props` 속성으로 JSON이 통째로
들어 있다.** 비공개 API를 때리는 게 아니라 공개 HTML이 이미 들고 있는 값을 읽는다.
(`api.auctionet.com` 같은 공개 데이터 API는 존재하지 않는다 — DNS 자체가 없다.)

### 4-1. 목록 (48건/요청)

```
/en/search/25-art?is=ended&order=end_desc&currency=<CUR>&page=<N>
```

`ItemThumbList` 프롭이 로트 48건을 준다: `id`, `longTitle`, `auctionId`, `estimate`,
`currency`(**원 통화**), `auctionEndsAtTitle`, `auctionEndTime`("Hammered 23 Sep 2026"),
`catalogNumber`, `amountLabel`("12 bids"/"Estimate"), `amountValue`("1,100 SEK"),
`hasMetReserve`, `imageUrls`.

- `25-art`가 상위 카테고리로 **회화(28)·드로잉(119)·판화(27)·사진(26)·조각(29)·기타(30)**를
  포함한다. 소스가 주는 분류 필드를 그대로 쓰므로 제목 휴리스틱 오탐 위험이 없다.
- `order=end_desc` = **최근 종료순** → 주간 증분에 그대로 쓸 수 있다.
- **딥 페이지네이션은 209페이지(48×209=10,032건)에서 막힌다** — 210페이지부터는
  1페이지 내용이 그대로 반복된다(page 210/250/400/1000 모두 page 1과 동일한 것을 실측).
  따라서 **단일 쿼리로는 최대 약 1만 건**이고, 전량 백필은 `company_id`(86개)·카테고리(6개)로
  슬라이스해야 한다.

### 4-2. 상세 (1건/요청)

```
/en/<item_id>?currency=<CUR>
```

`VipBidFormOrResult` 프롭의 `initialItem`이 **판매상태를 확정적으로** 준다:
`state`("sold"/"unsold"), `reserve_met`, `ends_at`(unix), `auction_id`, `hammer_auction`,
`original_currency`, `location`.
(같은 프롭에 `estimate`/`upper_estimate`/`bids[]`도 있지만 **금액은 여기서 읽지 않는다** —
4-4절의 함정 참고.)
그 외 페이지에서: `House`/`Address`(개최 경매사·소재지), **작가 엔티티 링크**
(`/en/artists/<id>-<slug>`, 라벨에 생몰년 포함 — "Karl Axel Pehrson (1921–2005)"),
`Description`/`Condition`/`Title`(원어 제목) 섹션, 카테고리 breadcrumb.

**상세를 반드시 거치는 이유**: 목록 JSON에는 **작가 필드가 없고** 제목 문자열에 뭉쳐 있다
("5306319. KARL AXEL PEHRSON. Nature composition, colour lithograph..."). 제목을 문자열로
쪼개 작가를 추측하지 않고 상세의 작가 링크만 신뢰한다(`duran.py`와 같은 원칙).
작가 링크는 **"Artist/designer" 섹션 안의 것만** 쓴다(페이지 전체를 훑으면 추천 로트에
섞인 다른 작가 링크가 딸려 들어온다).

### 4-3. 통화 — 환산을 원천 배제했다

페이지 금액은 **세션 표시통화로 환산돼** 나온다. 과거 낙찰가에 **현재 환율**을 먹인 값이라
그대로 쓰면 이 프로젝트가 이미 "임의 환율 시장지표"로 폐기한 것과 같은 오염이 된다.
(검증: 2020-05 낙찰 로트 25,000 SEK가 2,217 EUR로 표시 → 11.276 SEK/EUR = 현재 환율.)

로트 원 통화는 **SEK/DKK/EUR/GBP 4종뿐**이고(10페이지 480건 표본: SEK 428 / EUR 37 /
GBP 8 / DKK 7), 이 4종이 전부 표시통화로도 선택 가능하다. 그리고 **`?currency=XXX`
쿼리 파라미터 하나로 표시통화가 바뀐다**(세션 POST `/currency`도 있지만 불필요).

→ **통화별로 한 번씩 훑고, 원 통화가 그 통화인 로트만 취한다.** 환산이 전혀 개입하지 않는다.
크롤러가 `display_currency != original_currency`인 레코드는 저장하지 않고, 로더도 한 번 더
막는다(`skipped_fx`).

### 4-4. 함정 두 개 — 둘 다 그냥 지나쳤으면 틀린 값이 들어갔다

**(a) 현장 슬래그옥션 로트의 낙찰가를 `bids[]`에서 읽으면 안 된다.**
`hammer_auction: true`인 로트(예: Stockholms Auktionsverk Fine Art의 "The Signature Sale")는
사전입찰(pre-bid)만 `bids[]`에 담기고 **실제 낙찰은 현장에서 난다**. 같은 로트에서
사전입찰 최고가 798 SEK vs 실제 낙찰가 **9,000 SEK** — 그대로 썼으면 10배 넘게 틀렸을 것이다.
게다가 이런 로트는 **상세 페이지가 `?currency=` 지정을 무시**해서 `vip_item`의
`estimate`/`upper_estimate`가 환산값(EUR)으로 돌아온다.
→ **금액(통화·추정가 상하한·낙찰가·로트번호)은 전부 목록(thumb) JSON에서 읽는다.**
목록은 `?currency=`를 정확히 따르고, `amountValue`("9,000 SEK"), `amountTitle`
("Estimate: 10,000 – 12,000 SEK"), `catalogNumber`를 원 통화로 준다.
`vip_item`에서는 금액이 아닌 것만 쓴다(`state`, `ends_at`, `hammer_auction`).

**(b) 유찰 로트의 `amountValue`는 낙찰가가 아니라 추정가다.**
`amountLabel`이 `"Estimate"`면 무응찰 유찰이고 `amountValue`에 추정가가 그대로 찍힌다.
`sold`일 때만 `amountValue`를 낙찰가로 읽는다. 응찰이 있어도 내정가 미달이면
(`hasMetReserve=false`, `state='unsold'`) 유찰이다.

### 4-5. 최신성 — sitemap이 매일 재생성된다

`sitemap.xml.gz`(40MB, S3) 에는 **현재 진행 중인 로트 37,639건**이 올라와 있고
`lastmod`가 전부 `2026-09-23T03:00:00+02:00` — **매일 새벽 3시(CET) 재생성**된다.
사이트 실시간 카운트: **진행 중 38,099건 / 미술 8,016건**, **종료 3,946,061건 /
미술 739,856건**. 오늘(2026-09-23) 낙찰된 로트가 `order=end_desc` 1페이지에 바로 나온다.

---

## 5. 개인정보 — 입찰자 정보는 저장 전 제거

상세 페이지의 `VipBidFormOrResult` JSON에는 `bids[]` 배열이 통째로 들어 있고, 각 원소에
**입찰자 식별번호**(`bidder` — 경매별 익명 번호), 색상, **초 단위 입찰 시각**
(`time_string_long`: "25 May 2020, 01:25:30", `max_bid_time_string`)이 담긴다.

이 프로젝트가 쓰지 않는 제3자 정보라 **크롤러가 raw 저장 전에 `bids[]`를 통째로 버리고**
집계값(`bid_count`, `top_bid_amount`)만 남긴다(`crawlers/auctionet.py`의 `fetch_detail`,
저장 레코드에 `_bids_redacted: true` 플래그). 낙찰가는 `top_bid_amount`로 충분하다.
오늘 `astaguru.py`(`_strip_pii`)·`duran.py`(`auction_info` 블롭 제거)가 처리한 것과 같은 패턴.

`details.Address`는 **경매사 사업장 주소**(개인정보 아님), `Placement`는 경매사 창고
선반 위치라 그대로 둔다. 이미지 파일은 저장하지 않는다(URL 문자열만 남음).

---

## 5-2. 종료 직후 로트는 낙찰 상태가 아직 확정되지 않는다 — 3일 격리

종료일별 낙찰률을 실측하다가 발견했다(48건/페이지 표본, 2026-09-23):

| 종료일 | 경과 | 낙찰률 |
|---|---|---|
| 9/23(당일) | 0일 | 38~67% |
| 9/22 | 1일 | 38~50% |
| 9/21 | 2일 | **83%** |
| 9/19 | 4일 | 77% |
| 9/16 | 7일 | 75% |
| 9/11 | 12일 | 79% |
| 9/5~6 | 17일 | 90% |
| 2011년 아카이브(`order=end_asc_archive`) | — | 98% |

0~1일짜리를 바로 적재하면 **낙찰된 로트가 유찰로 박제된다**(경매사 정산 전이라 `state`가
아직 `unsold`). 2일을 넘기면 80% 전후로 안정되므로 로더 기본값을 **`min_age_days=3`**으로
두고 그보다 최근 로트는 보류한다. 주간 갱신 주기라면 실질 손실이 없다.

---

## 5-3. 작가 귀속률은 경매사에 따라 극단적으로 다르다

Auctionet은 로트마다 작가 엔티티 링크(`/en/artists/<id>`)를 달아 주지만 **필수가 아니다.**
수집분 실측:

| 경매사 | 수집 로트 | 작가 링크 있음 |
|---|---|---|
| Stockholms Auktionsverk Fine Art | 150 | **97 (65%)** |
| Uppsala Auktionskammare | 87 | 35 (40%) |
| Auktionskammaren Sydost Kalmar | 29 | 2 (7%) |
| **Balclis (스페인)** | 81 | **0** |
| **Lawrences Auctioneers (영국)** | 68 | **0** |
| Auktionshaus Blank / Arce / Karlstad 등 지방 종합 경매사 | 각 4~14 | 대부분 0 |
| 최근 종료순 전체 표본(경매사 무관) | 150 | 19 (13%) |
| **수집분 전체** | **667** | **176 (26%)** |

스페인·영국 입점사는 작가 태깅을 **아예 하지 않는다**(Balclis 81건·Lawrences 68건 전부 0).
결국 작가 귀속이 되는 것은 사실상 **스웨덴 미술 전문 경매사**뿐이고, 그래서 이번 적재분
147건이 전부 SEK다.

- 미술 전문 경매사는 작가를 태깅하고, **지방 종합 경매사는 제목에만 이름을 적는다**
  ("WILHELM SKOGLUND, OLJA PÅ DUK, SIGNERAD" — 링크 없음).
- 작가 인덱스(`/en/artists`) 전체는 **약 3,390명뿐**이다(알파벳 31개 페이지 전수).
- `q="<작가명>"` 검색은 되지만(Karl Axel Pehrson → 종료 미술 1,364건) **표본 12건 중
  엔티티 링크가 달린 건 0건**이었다(Picasso는 12건 중 2건). 즉 `q=` 결과는 제목 텍스트
  매칭이라 **작가 귀속 근거로 쓸 수 없다.**

→ **로더 기본값은 작가 엔티티 링크가 있는 로트만 적재**(`require_artist=True`)로 뒀다.
제목에서 작가를 문자열로 떼어내는 추측은 하지 않고, 작가 NULL 로트를 대량으로 넣는 것은
2026-09-15 재진단이 가비지로 지목한 패턴(Bonhams 작가 NULL 90K)의 반복이라 피했다.
`--include-artistless`로 해제는 가능하다.

---

## 6. 수집·적재 결과 (2026-09-23)

### 수집

```
python crawlers/auctionet.py --houses                              # 입점 경매사 86곳
python crawlers/auctionet.py --limit 90 --pages 12 --currencies SEK   # 통화별 파일럿
python crawlers/auctionet.py --limit 90 --pages 12 --currencies EUR
python crawlers/auctionet.py --limit 90 --pages 12 --currencies GBP
python crawlers/auctionet.py --limit 90 --pages 12 --currencies DKK
```

통화별로 나눠 돌린 이유: `--limit`이 전역이라 한 번에 돌리면 SEK(전체의 약 89%)가
한도를 다 먹어 다른 나라 경매사가 표본에 안 들어온다. 국가·경매사·통화 매핑을
검증하려고 4개 통화를 고르게 뽑았다.

추가로 경매사 슬라이스(`--company-id`)와 "상태가 확정된 코호트"(`--start-page 195`)도
같이 돌려 두 기능이 실제로 동작하는지 확인했다:

```
python crawlers/auctionet.py --limit 150 --pages 8  --currencies SEK --company-id 238   # SAV Fine Art
python crawlers/auctionet.py --limit  80 --pages 4  --currencies SEK --company-id 567   # Uppsala
python crawlers/auctionet.py --limit  80 --pages 4  --currencies EUR --company-id 223   # Balclis(ES)
python crawlers/auctionet.py --limit  60 --pages 4  --currencies GBP --company-id 319   # Lawrences(GB)
python crawlers/auctionet.py --limit 150 --pages 15 --start-page 195 --currencies SEK   # 약 3주 전 종료분
```

### 적재

```
python pipeline/_scratch/load_auctionet_20260923.py                 # 샘플 검수 + DryRun
python pipeline/_scratch/load_auctionet_20260923.py --apply         # 실제 적재
```

`pipeline/run.py`는 다른 세션이 동시에 수정 중이라 **건드리지 않고**, 로더 모듈
(`pipeline/auctionet.py`)을 직접 import하는 1회성 스크립트로 처리했다. 중간에 한 번
재실행해 **idempotent도 확인**했다(이미 적재된 raw는 `sources.raw_path`로 전부 스킵).

### 결과

| 지표 | 값 |
|---|---|
| raw 수집 로트 | **667건** (SEK 452 / EUR 120 / GBP 70 / DKK 7 — 전부 원 통화 그대로) |
| 적재된 auction_lots | **147건** |
| 적재 보류 — 종료 3일 미만 | 251건 (다음 주 갱신 때 상태 확정된 채로 들어온다) |
| 적재 보류 — 작가 엔티티 링크 없음 | 269건 |
| 환산통화라 보류 / 경매사 없음 / 제목 없음 | **각 0건** |
| distinct artist | **116명** (신규 생성 32명 / 기존 작가와 정확이름 매칭 **84명**) |
| auction_houses | 22곳이 적재에 등장, 신규 생성 25곳 |
| auctions | 29개 |
| 기간 | **2026-09-05 ~ 2026-09-19** (수집 시점 기준 4~18일 전) |
| 낙찰 / 유찰 | 126 / 21 |
| 낙찰가 범위 | 300 ~ **212,700 SEK** |
| 로트번호·추정가 상한이 있는 로트 | 96건 (현장 슬래그옥션분) |

정합성 스팟체크(전수):

- `sold=true`인데 낙찰가 NULL = **0건**, `sold=false`인데 낙찰가 있음 = **0건**
- `estimate_low` NULL = 0건, `currency` NULL = 0건
- 낙찰가/추정가하한 비율 분포: 0.3~1.0배 41건 / 1.0~1.9배 51건 / 2~3배 8건 / 3~4배 3건 /
  4~5배 1건 / 5배 초과 2건 — 실제 경매 결과다운 분포(추정가 미달 낙찰이 정상적으로 섞여 있음)
- 같은 제목 2건은 `LARS LERIN. Utan titel.`(무제) 하나뿐 — 서로 다른 작품

낙찰가 상위(검증용 SELECT):

| 작가 | 작품 | 낙찰가 | 경매사 | 경매일 |
|---|---|---|---|---|
| Herbert Gentry | Abstrakt komposition | 212,700 SEK | Stockholms Auktionsverk Fine Art | 2026-09-15 |
| Ernst Billgren | "Blå försoning" | 210,000 SEK | 〃 | 〃 |
| Lars Lerin | "Nordland IV" | 185,000 SEK | 〃 | 〃 |
| Lars Lerin | Utan titel | 125,000 SEK | 〃 | 〃 |
| Einar Jolin | Clo i svart klänning | 115,050 SEK | 〃 | 〃 |
| Oskar Bergman | Kustlandskap | 115,000 SEK | 〃 | 〃 |

### 관계망 기여 (5자 관계망 관점)

- 116명 중 **29명이 이미 미술관 소장 기록을 가진 작가**(소장 ∧ 경매 교집합에 직접 기여).
- **83명이 다른 경매사 기록과도 교차**한다.
- 신규 생성이 32명뿐이고 **84명이 기존 작가와 정확이름으로 붙었다** — 스웨덴 근현대 작가
  축이 이미 DB에 어느 정도 있었고 Auctionet이 그 위에 시장 기록을 얹는 구조다.
  (AstaGuru 착수분이 595명 중 54명만 미술관 교집합이었던 것과 비교하면 **교차율이 훨씬 높다** —
  작가 링크가 있는 로트만 적재한 효과.)
- 병합은 `get_or_create_artist_safe`의 **정확 이름 매칭만** 사용. Auctionet 내부 작가 ID는
  authority ID가 아니라 병합 근거로도, 적재 대상으로도 쓰지 않았다.

### 적재 중 발견하고 고친 것 — 연속 공백 작가명 중복 4쌍

첫 적재 직후 `Georg  Gudni`(공백 2개)가 기존 `Georg Gudni`와 따로 생긴 것을 발견했다.
Auctionet 작가 라벨에 연속 공백이 들어오는 경우가 있어서다. 로더의 `_artist_name`에
공백 정규화를 넣고, **이미 생긴 4쌍**(`Georg Gudni`, `Hans Runesson`, `Lukas Göthman`,
`Nils Kreuger`)은 artworks를 기존 행으로 재연결한 뒤 빈 중복 행을 삭제했다.

- 문자열 유사도 병합이 **아니다** — 공백만 정규화하면 완전히 같은 문자열인 쌍이고,
  한쪽이 이번 적재로 오늘 생긴 행(`artworks` 전부가 auctionet 출처)인 경우만 손댔다.
- 같은 패턴의 기존 쌍 2개(`Mirosław Bałka`, `Wolfgang Plöger` — 둘 다 2026-09-02 생성,
  auctionet과 무관)는 **손대지 않았다.** DB 전체에는 연속 공백이 든 작가명이 수십 건
  더 있는데(대부분 Getty/프랑스 경매 출처), 이번 작업 범위 밖이라 그대로 뒀다.
- `Nils Kreuger`는 기존 행에 artworks가 71건 있었다 — 안 고쳤으면 스웨덴 주요 작가 하나가
  공백 차이로 둘로 쪼개질 뻔했다.

### 남은 NULL

`auction_houses.country`가 일부 NULL이다. **현장 슬래그옥션 로트의 상세 페이지에는
`Address` 행이 없어서**(`House` + `Catalogue no`만 나온다) 그 경매사가 슬래그옥션 로트로
먼저 생성되면 국가가 비는 구조다. `crawlers/raw/auctionet_houses/_houses.json`에 86곳 전부의
국가가 있으니 나중에 백필 가능하다(이번엔 손대지 않음).

---

## 7. 전량 백필 — 규모와 선택지 (**사용자 결정 필요**)

### 규모 실측 (경매사 86곳 각각 `?is=ended&company_id=N`의 공시 건수, 2026-09-23)

- **종료된 미술 로트 합계 = 649,940건**(사이트 전체 공시 739,856건과의 차이는 플랫폼을
  떠난 과거 입점사 몫으로 보인다).
- 상위: Göteborgs Auktionsverk 51,978 / Garpenhus 44,210 / SAV Magasin 5 43,620 /
  Helsingborgs Auktionskammare 36,955 / Auktionshuset Kolonn 33,419 /
  Gomér & Andersson Linköping 32,696 / SAV Sickla 27,021 / Crafoord Stockholm 25,491 /
  … / **Balclis(스페인) 16,366** / SAV Fine Art 10,000 / **Lawrences(영국) 7,573**.
- **209페이지(10,032건) 상한을 넘는 경매사가 19곳** → 이들은 카테고리(28-paintings,
  119-drawings, 26-photography, 27-engravings-prints, 29-sculptures-bronzes, 30-other)로
  한 번 더 쪼개야 한다. 최대 규모(51,978)도 6분할하면 슬라이스당 1만 건 이하라 도달 가능.

### 비용

| 단계 | 요청 수 | 1.2초 간격 기준 소요 |
|---|---|---|
| 목록만(48건/요청) | 약 13,540 | **약 4.5시간** |
| 상세까지(1건/요청) | 649,940 | **약 9일 연속** |

상세를 건너뛰면 **작가 귀속이 아예 불가능**하다(5-3절). 그래서 선택지는 셋이다.

| 안 | 내용 | 비용 | 결과물 |
|---|---|---|---|
| **A. 최신성만** (권장 기본) | 주간으로 최근 종료분만 상세까지 수집 | 주당 **약 30~50분** | 미술 로트 주 900~1,000건, 그중 작가 링크 **약 13%(120~130건)** |
| **B. 스웨덴 미술 전문 경매사 백필** | 작가 태깅률이 실제로 높은 곳만 전량 — SAV Fine Art(10,000) · Uppsala(약 5,900) · Göteborgs Auktionsverk(51,978) · SAV Magasin 5(43,620) 등 | 약 **2~4일** | 작가 귀속 로트 수천~수만 건 |
| **C. 전량 백필** | 86곳 × 6카테고리 슬라이스 전부 | 약 **9일 연속** | 65만 로트(작가 링크는 그중 약 13%) |

B를 고를 때 주의: **Balclis(16,366)·Lawrences(7,573) 같은 스페인·영국 입점사는 작가 태깅이
0%**라 로트 수는 커도 작가 귀속이 하나도 안 나온다(5-3절 실측). 스코프를 정할 때 "규모"가
아니라 "작가 태깅률"로 골라야 한다.

C는 **EU sui generis 데이터베이스권(96/9/EC)의 "상당한 부분의 추출·재이용"** 논란 소지도
있다(약관에 금지 조항이 없는 것과 별개 문제 — 2절 말미 참고). **A를 기본으로 두고,
B를 사용자 승인 시 진행하는 것을 권한다. C는 권하지 않는다.**

### 주간 자동갱신(로드맵 7) 연결 방법

```powershell
python crawlers/auctionet.py --limit 1200 --pages 40 --currencies SEK
python crawlers/auctionet.py --limit 200  --pages 40 --currencies EUR
python crawlers/auctionet.py --limit 60   --pages 40 --currencies GBP
python crawlers/auctionet.py --limit 60   --pages 40 --currencies DKK
python pipeline/_scratch/load_auctionet_20260923.py --apply
```

`already_fetched()` + `sources.raw_path` 유니크로 양쪽 다 idempotent고, `min_age_days=3`
격리 덕분에 주간 주기와 잘 맞는다(지난주 보류분이 이번 주에 확정 상태로 들어온다).
**이번 세션에서는 `refresh_weekly.ps1`을 건드리지 않았다** — 다른 세션이 같은 파일을
편집 중일 수 있고, 전량 백필 방침이 정해진 뒤에 붙이는 게 맞다.

---

## 8. 남은 과제

1. **`refresh_weekly.ps1` 연결** — 위 명령을 붙이면 끝. 방침 결정 후 진행.
2. **작가 귀속 확대 여부** — 작가 인덱스 3,390명을 **통제 어휘**로 삼아 "로트 제목이 그
   이름으로 시작할 때만" 귀속시키는 안을 검토할 수 있다. 다만 이건 소스가 준 엔티티 링크가
   아니라 문자열 매칭이라 프로젝트 규칙(추측성 분리 금지)과 충돌한다 — **사용자 판단 항목**.
3. **`auction_houses.country`가 일부 NULL** — 슬래그옥션 로트의 상세 페이지에는 `Address`
   행이 없다(`House` + `Catalogue no`만). 같은 경매사의 온라인 로트가 하나라도 먼저
   들어오면 채워지고, 아니면 `crawlers/raw/auctionet_houses/_houses.json`의 국가 정보로
   나중에 백필할 수 있다(이번엔 손대지 않음).
4. **작가 생몰년 미활용** — 작가 링크 라벨에 `(1921–2005)` / `(Born 1941)`이 들어 있지만
   **일부러 적재하지 않았다**. 생몰년 백필은 Wikidata/ULAN authority 매칭으로만 한다는
   규칙을 따랐다. Auctionet 내부 작가 ID도 authority ID가 아니라 저장하지 않았다.
5. **미술 외 카테고리** — 종료 로트 394만 건 중 미술이 74만 건이고 나머지(가구·도자·보석·
   시계 등)는 스코프 밖이라 아예 수집하지 않았다.
6. **`order=end_asc_archive`로 2011년 초기 데이터에 접근 가능** — 반대쪽 끝에서도 1만 건을
   뽑을 수 있다. 전량 백필을 하게 되면 양끝 + company_id 슬라이스를 조합하면 된다.

---

## 9. Option B 실행 기록 — 스웨덴 미술 전문 경매사 선별 백필 (2026-09-23, 사용자 승인 후 착수)

### 9-1. 대상 경매사 (7절이 예시로 든 4곳 그대로 — 추가 후보는 태깅률 근거가 없어 보류)

| 경매사 | company_id | 종료 미술 로트(공시치) | 209페이지 상한 | 슬라이스 |
|---|---|---|---|---|
| Stockholms Auktionsverk Fine Art | 238 | 약 10,000 | 안 넘음 | 단일(카테고리 기본값 `25-art`) |
| Uppsala Auktionskammare | 567 | 약 5,900 | 안 넘음 | 단일 |
| Göteborgs Auktionsverk | 10 | 51,978 | 넘음 | 카테고리 6분할 |
| Stockholms Auktionsverk Magasin 5 | 239 | 43,620 | 넘음 | 카테고리 6분할 |

추가 후보(예: 다른 "Auktionsverk/Auktionskammare" 지방사)는 넣지 않았다 — §5-3 실측이 보여주듯
이름만으로는 작가 태깅률을 알 수 없고(Auktionskammaren Sydost Kalmar는 태깅 7%), 이번 4곳 외에는
실측 근거가 없어서 스코프를 원문이 이미 검증한 4곳으로 한정했다.

### 9-2. 카테고리 슬러그 확인

크롤러가 아직 카테고리 슬라이스를 지원하지 않아 `crawlers/auctionet.py`에 `--category` 옵션을
추가했다(`list_page`/`crawl`에 파라미터 스레딩, 기본값은 기존과 동일한 `25-art`라 기존 호출은 영향
없음). 실제 슬러그는 추측하지 않고 오늘 파일럿 raw 캐시(667건)의 `categories` 필드를 스캔해 확정:
`28-paintings`, `119-drawings`, `26-photography`, `27-engravings-prints`,
`29-sculptures-bronzes`, `30-other` (합이 `25-art`와 같아야 하고 실제로 6종 전부 나왔다).

### 9-3. 실행 명령 — 14개 크롤 프로세스 + 로더 루프 1개, 전부 백그라운드

```powershell
# 단일 슬라이스 2개
python crawlers/auctionet.py --company-id 238 --currencies SEK --pages 209 --limit 10500   # SAV Fine Art
python crawlers/auctionet.py --company-id 567 --currencies SEK --pages 209 --limit 10500   # Uppsala

# Göteborgs Auktionsverk(10) — 카테고리 6분할, Magasin 5(239) — 카테고리 6분할
python crawlers/auctionet.py --company-id 10  --currencies SEK --pages 209 --limit 10500 --category 28-paintings
python crawlers/auctionet.py --company-id 10  --currencies SEK --pages 209 --limit 10500 --category 119-drawings
python crawlers/auctionet.py --company-id 10  --currencies SEK --pages 209 --limit 10500 --category 26-photography
python crawlers/auctionet.py --company-id 10  --currencies SEK --pages 209 --limit 10500 --category 27-engravings-prints
python crawlers/auctionet.py --company-id 10  --currencies SEK --pages 209 --limit 10500 --category 29-sculptures-bronzes
python crawlers/auctionet.py --company-id 10  --currencies SEK --pages 209 --limit 10500 --category 30-other
python crawlers/auctionet.py --company-id 239 --currencies SEK --pages 209 --limit 10500 --category 28-paintings
python crawlers/auctionet.py --company-id 239 --currencies SEK --pages 209 --limit 10500 --category 119-drawings
python crawlers/auctionet.py --company-id 239 --currencies SEK --pages 209 --limit 10500 --category 26-photography
python crawlers/auctionet.py --company-id 239 --currencies SEK --pages 209 --limit 10500 --category 27-engravings-prints
python crawlers/auctionet.py --company-id 239 --currencies SEK --pages 209 --limit 10500 --category 29-sculptures-bronzes
python crawlers/auctionet.py --company-id 239 --currencies SEK --pages 209 --limit 10500 --category 30-other
```

로그는 `docs/logs/auctionet_optionB_<house>_<category>_20260923_std{out,err}.log`(경매사별)로
분리 저장. `Start-Process -WindowStyle Hidden -RedirectStandardOutput/-RedirectStandardError`로
셸 세션과 독립적으로 기동했다(PowerShell 세션 종료와 무관하게 계속 돈다).

**적재 루프**(크롤과 분리된 별도 프로세스, `pipeline/_scratch/load_auctionet_20260923.py --apply`를
10분 간격으로 반복 — `DATABASE_URL`을 루프 스크립트 안에서 인라인 export, pgportable이 죽어 있으면
자동 재기동 후 재시도):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File <scratchpad>/auctionet_load_loop.ps1
```

`pipeline/run.py`, `docs/작업분담_20260915.md` 등 공유 문서는 손대지 않았다(§6 원문 지침 그대로).

### 9-4. 기동 확인 — pgportable 재기동 1회 포함, 정상 동작 확인

- 착수 시점에 `postgres.exe` 프로세스가 떠 있었지만 **실제로는 5432 포트**(이 프로젝트가 쓰지
  않는 다른 인스턴스)였고 5433(우리 DB)은 죽어 있었다 — 로더 루프 첫 사이클이 `Connection
  refused`로 즉시 드러냈다. `C:\pgportable\pgsql\bin\postgres.exe -D C:\pgportable\data -p 5433`로
  재기동(stdout/stderr → `pipeline/_pg_server_out.log`/`_pg_server.log`), 비정상 종료 후 자동
  redo 복구가 붙었지만 수 초 내 정상 기동 확인(`pipeline/_pg_server.log` 타임스탬프
  13:50:18~13:50:23).
- 재기동 직후 로더 루프가 재시도 끝에 접속 성공, **첫 사이클 적재 225건**(`[load_auctionet]
  적재 완료: 225건`) — 크롤 결과가 DB까지 실제로 들어가는 것을 확인했다.
- raw 파일 수 추이(`crawlers/raw/auctionet/*.json`, `.meta.json` 제외):
  착수 직전 667(파일럿분) → 14개 프로세스 기동 후 980 → +60초 1,836 → +45초 2,259.
  **꾸준히 증가 확인** — 14개 프로세스가 전부 정상적으로 로트를 저장 중.
- 14개 크롤 프로세스의 stderr 로그 전부 **0바이트**(에러 없음), `Get-CimInstance`로 PID 14개
  전부 생존 확인. 로더 루프 프로세스(PID 9252)도 생존 확인(사이클 사이 10분 대기 상태).

### 9-5. 예상 규모·소요

대상 4곳 raw 공시 합계 약 **111,500건**(10,000+5,900+51,978+43,620). 상세 1건당 1.2초 자체
크롤 지연 기준 순차로는 약 37시간이지만 14개 프로세스로 나눠 돌리므로 **체감 완료는 수 시간대**로
예상된다(7절의 "2~4일"은 단일 프로세스 순차 실행 가정 — 이번엔 병렬 슬라이스라 더 빠르다). 다만
작가 링크 없는 로트는 로더가 스킵하므로 **적재 건수는 111,500보다 크게 작을 것**(파일럿 기준
작가 귀속률 SAV Fine Art 65%/Uppsala 40%대, GAV·Magasin 5는 미실측). 완료 확인·최종 통계(경매사별
로트 수, 작가 귀속 건수, distinct artist 수, 신규 생성/기존 매칭 비율)는 이후 별도 점검에서 낸다 —
이번 기록은 "정상 기동 확인"까지다.

### 9-6. 코드 변경

`crawlers/auctionet.py`에 `--category` CLI 옵션과 `ART_SUBCATEGORIES` 상수 추가(하위 카테고리
슬러그 6종, docstring 사용법에도 반영 안 함 — 기존 6개 사용 예시는 그대로 두고 옵션만 추가).
`list_page()`/`crawl()` 시그니처에 `category` 파라미터 추가, 기본값이 기존 `ART_CATEGORY`라
이 옵션을 안 쓰는 기존 호출(오늘 다른 세션이 이미 돌리고 있을 수 있는 것 포함)은 동작 변화 없음.
