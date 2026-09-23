# 경매 소스 확장 — Pandolfini Casa d'Aste(피렌체, pandolfini.it) 조사 (2026-09-22)

**최종 판정: 보류(사실상 불가) — 법적 장벽은 없으나 낙찰가가 전 경로에서 로그인 게이트 뒤에 있어 수집할 데이터가 없다.**
라이즈아트(금지 조항 없음 + 낙찰가 미공개 → 보류)와 같은 유형. 크롤러·로더는 만들지 않았다.

이탈리아 첫 착수 대상이었다. `docs/경매소스확장_20260922.md`의 판정 기준(robots 통과 + ToS 통과 + 정적 HTML에 낙찰가)으로
순서대로 확인했고, 마지막 조건에서 걸렸다.

---

## 1. robots.txt — 통과

`https://www.pandolfini.it/robots.txt` (Last updated 2026-03-13, 직접 확인):

```
User-agent: *
Disallow: /admin/  /myasg/  /include/asta-tempo/  /include/comuni
Disallow: /it/controller.asp  /uk/controller.asp  /it/controller-v2.asp  /uk/controller-v2.asp
Disallow: /it/my-panel/  /uk/my-panel/
Disallow: /it/contatti/richiedi-informazioni.asp  /uk/contacts/request-information.asp
Disallow: /*?*campoRicerca=      ← 사이트 검색
Disallow: /*?*mlview=
Disallow: /thumb/  /cdn-cgi/
(ia_archiver / AhrefsBot / MJ12bot / DataForSeoBot / serpstatbot / SemrushBot / DotBot / MegaIndex.ru / PetalBot / Barkrowler / SEOkicks / RainBot → Disallow: /)
Sitemap: https://www.pandolfini.it/sitemaps/sitemap_index.xml
```

- ClaudeBot / anthropic-ai / GPTBot 등 **AI 봇 언급 전무**. 이름으로 차단한 것은 SEO 크롤러·아카이버뿐.
- 과거경매 목록(`/it/calendario-aste/calendario-aste.asp?astePass=true`), 경매 카탈로그(`/it/asta-NNNN/<slug>.asp`),
  로트 상세(`/it/asta-NNNN/<slug>-<id>`)는 **모두 허용 경로**. 검색 쿼리(`campoRicerca=`)와 회원 패널(`/it/my-panel/`)만 금지.
- Cloudflare 앞단(`server: cloudflare`)이지만 `Mozilla/5.0 (artgraph-research-bot)` UA로 robots·홈·목록·카탈로그·로트 상세
  전부 **HTTP 200 + 정상 본문**(챌린지 페이지 아님). Dorotheum류 봇 챌린지는 아니다.
- 사이트맵: `sitemap_it.xml`(612 URL) + `sitemap_artisti_it.xml` + 로트 사이트맵 `/it/sitemap-lotti.asp?id=N` **1,406개 샤드**
  (id=1 샤드가 177 URL, 경매번호 0001-1 = 2015년 4월부터) — 규모는 수만 로트 수준으로 추정.

## 2. 이용약관 — 금지 조항 없음(오히려 출처 표기 조건부 재이용 허용)

**웹사이트 전용 이용약관(Termini e Condizioni / Note Legali) 페이지가 존재하지 않는다.** 푸터 링크는 Mappa del sito / Privacy /
Cookie Policy(iubenda 외부) / Cookies뿐이고, `/it/content/note-legali.asp`, `/it/content/termini-e-condizioni.asp`,
`/it/content/condizioni-di-utilizzo.asp`, `/uk/content/terms-and-conditions.asp`, `/uk/content/legal-notice.asp` 모두 404.
`sitemap_it.xml` 612 URL과 사이트맵 페이지(`/it/content/mappa-del-sito.asp`) 전체 링크에도 법적 고지 페이지 없음.

확인한 문서 전부:

| 문서 | 결과 |
|---|---|
| **푸터 법적 고지(전 페이지 공통)** | "© 2026 Pandolfini Casa d'Aste \| All rights reserved **I testi e le immagini presenti nel sito sono riproducibili citandone la fonte.**" (영문판: "Text and images on this website are reproduced by citing the source.") → **출처를 밝히면 텍스트·이미지 재이용 가능**이라는 허용 문구. 크롤링/스크래핑/데이터마이닝/개인적·비상업적 용도 한정/**데이터베이스권(sui generis, 96/9/EC) 유보** 문구 전부 없음 |
| `/it/vendere/condizioni-generali.asp` (Condizioni generali di vendita, 제1~21조) | 경매 참가·수수료·IVA·문화재 선매권·추급권(diritto di seguito)·관할(피렌체) 조항뿐. 웹사이트 콘텐츠·카탈로그 복제·자동수집·DB 재이용 관련 조항 **없음**. 키워드(scrap/crawl/spider/robot/harvest/data mining/estrazione/banca dati/riutilizzo/uso personale/non commerciale/automat/riproduz) 전수 검색 — 무관한 매치만 |
| `/it/acquistare/corrispettivo-dasta-e-iva.asp` | 구매수수료(26%/22%) 안내만 |
| `/it/la-casa-daste/faq.asp` (37KB) | 경매 절차 FAQ. 관련 조항 없음 |
| `/it/content/privacy.asp` | 본문이 iubenda 외부 정책으로 위임(GDPR 고지) — 크롤링 조항 없음 |

즉 **프랑스식 DB권 조항(Artcurial)·재이용 금지(Hampel/Deutscher and Hackett)·personal-non-commercial(the-saleroom)에 해당하는 문구가
하나도 없고**, 유일한 저작권 고지는 출처 표기 조건부 허용이다. 법적으로는 Grisebach/Lyon & Turnbull과 같은 "통과" 등급.

## 3. 낙찰결과 페이지 구조 — **낙찰가 로그인 게이트(여기서 중단)**

- 과거경매 목록 `calendario-aste.asp?astePass=true&pag=N` (9페이지, `anno=2000~2026` 연도 필터 있음)은 완전 SSR.
  회차번호·제목·일자·경매 유형(Live/online/Premium)이 텍스트로 있고, 각 회차의 "Risultati" 버튼이
  `/it/asta-NNNN/<slug>.asp?action=reset#catalogue`(카탈로그 페이지)로 간다.
- 카탈로그 페이지(예: `asta-1429/dipinti-del-secolo-xix.asp`, 2026-06-09 DIPINTI DEL SECOLO XIX, 83로트)도 SSR이고 `?pag=N`
  페이지네이션(30건/페이지, 폼으로 60건 선택 가능). 로트번호·작가(생몰·출생지)·작품명·재질·규격·**추정가**는 텍스트로 있다.
- **그러나 낙찰가는 없다.** 낙찰된 로트는 `<b class="venduto">` 아래 라벨 "Aggiudicazione"만 있고 값 자리에
  `<a href="https://www.pandolfini.it/it/my-panel/index.asp" title="Per visualizzare la cifra di vendita é necessario eseguire il login">Entra o registrati</a>`
  (판매 금액을 보려면 로그인이 필요합니다 — 로그인 또는 가입) 버튼이 들어 있다. 원본 HTML에도 숨겨진 금액·data 속성 없음(직접 확인).
- 로트 상세 페이지(`asta-1429/consalvo-carelli-12026001426`, 낙찰 로트)도 동일: 추정가 + "Aggiudicazione / Entra o registrati". 유찰 로트
  (`andreas-markograve-12026004366`)는 Aggiudicazione 블록 자체가 없다.
- 목록의 "Risultati in PDF" 버튼 역시 전부 `/it/my-panel/index.asp`(회원 패널 = robots.txt Disallow 경로).
- 사이트맵의 별도 결과 페이지 `/it/risultati/risultati.asp`는 위 과거경매 목록과 같은 내용.

**공개적으로 얻을 수 있는 것은 "낙찰/유찰 여부"(`class="venduto"` 유무, 표본 페이지 30로트 중 18 낙찰)와 추정가뿐**이다.
낙찰가가 없으면 auction_lots.hammer_price를 채울 수 없어 프로젝트 목적상 가치가 없다(라이즈아트와 동일 판단).

로그인 게이트를 계정 가입으로 넘는 것은 ① 이 프로젝트 원칙(웹 공개 정보만, 봇 탐지·접근통제 우회 금지) 밖이고
② 회원 패널은 robots.txt가 명시 차단한 경로이며 ③ 계정 생성은 에이전트가 하지 않는 행위라 **시도하지 않았다**.

## 4. 재검토 조건

- Pandolfini가 낙찰가를 비회원에게도 공개하도록 바꾸면 즉시 착수 가능하다. 그때는 위 구조 그대로 (목록 → 카탈로그 `?pag=N`)
  2단계 크롤러가 되고, 법적 요건은 이미 충족(robots·약관 통과, 이미지 미수집·출처 표기).
- 사용자가 회원 가입 후 로그인 세션을 직접 제공하는 경우는 별개 판단 항목(회원 약관을 그때 다시 읽어야 함) — 이 조사 범위 밖.

## 5. 이번에 만든 것 / 손댄 것

없음. `crawlers/`·`pipeline/`·`run.py`·raw 캐시 모두 변경 없음. 조사용 임시 파일은 세션 스크래치패드에만 있음.

요청 이력: robots.txt 1회, 홈(it/uk) 2회, 법적·안내 페이지 5회, 사이트맵 3회, 과거경매 목록 2회, 카탈로그 2회, 로트 상세 3회,
404 탐색 6회 — 모두 1.5~2초 간격, 총 24회 내외.
