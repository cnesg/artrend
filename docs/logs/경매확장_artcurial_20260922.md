# Artcurial(artcurial.com) 조사 — 2026-09-22

`docs/경매소스확장_20260922.md` B-5절 "판단 보류" 항목 재조사. 결론: **불가 — 즉시 중단**.
크롤러/로더 코드는 작성하지 않았다(작성 전에 ToS에서 명시적 금지 조항을 발견해 3번 단계에서
멈춤).

## 0. 사전 확인 — B-3절 sitemap 실측(10만+, 30시간)은 Artcurial 얘기가 아니다

`docs/경매소스확장_20260922.md` B-3절의 "sitemapindex.xml → 로트 URL 10만+건, 목록 페이지
없어 로트당 1회 필요, 30시간 예상"은 **Lempertz(쾰른)** 얘기다(B-3 제목이 명시적으로
"Lempertz(쾰른)"). Artcurial의 sitemap 규모는 이번 조사에서 별도로 확인하지 않았다 — 1번
단계(ToS)에서 이미 중단 사유가 나와서 규모 실측까지 갈 필요가 없었다.

## 1. robots.txt (2026-09-22 직접 확인)

```
User-agent: *
Disallow: /motorcars ...(자동차 부문만)
Disallow: /?slider=on, /pixel-suivi ...(트래킹/UI 파라미터)

User-agent: meta-externalagent / Bytespider / PetalBot / SemrushBot / Amzn-SearchBot /
            meta-webindexer / AhrefsBot / Amazonbot
Disallow: /

Sitemap: https://www.artcurial.com/sitemap.xml, /sitemap_index.xml
```

- `ClaudeBot`/`anthropic-ai` **미언급** — Grisebach처럼 명시 허용도 아니고, Van Ham처럼
  경쟁 AI 봇만 콕 집어 차단하지도 않는다(중립).
- 미술품 결과 경로(`/results-auctions-sales` 등)는 차단 목록에 없음. 자동차 부문(`/motorcars`)만
  막혀 있는데 이건 프로젝트 스코프(미술품) 밖이라 애초에 관심 대상이 아니다.
- **결론: robots.txt는 통과.** (B-5절 기록과 일치)

## 2. 이용약관(Terms & Conditions, `/en/legal-notice/terms-and-conditions`) — 여기서 중단 확정

원문 전체를 읽었다(영문판, 9개 조항 + 앞단 법적고지 5개 조항). 크롤링/스크래핑/robot/spider
같은 단어는 안 쓰지만, **"5. INTELLECTUAL PROPERTY – COPYING"** 조항에 사실상 동일한 효력의
포괄적 복제 금지가 명시돼 있다:

> "**Any copying, in full or in part, of the catalogue presented by Artcurial on the
> Artcurial.com website is strictly forbidden** and represents an infringement for which
> offenders may be prosecuted under the provisions of Book III of the Intellectual Property
> French Code."

> "...the overall layout and all the elements such as texts, images (animated or not)
> comprising the Artcurial.com website are the property of Artcurial. **It is strictly
> forbidden to copy this website, in full or in part, in any format whatsoever, without the
> written authorization of Artcurial.** Any representation or copy of this website by any
> means whatsoever shall be deemed a punishable infringement under articles L.335-2 et seq.
> of the Intellectual Property French Code."

핵심 문제: "catalogue"가 정확히 우리가 수집하려는 대상이다 — 작가/작품명/로트번호/추정가/
**낙찰가**가 실리는 그 "카탈로그"를, 텍스트 전체든 부분이든 복제하는 것을 조항 자체가
"strictly forbidden"이라고 적시한다. `robots.txt` 통과와 무관하게 **계약(ToS)상 명시적
금지**이고, 근거 법률(프랑스 지식재산법전 Book III, L.335-2조 이하)까지 못박아 뒀다 —
사용자가 우려했던 "프랑스 데이터베이스권(`Code de la propriété intellectuelle`)" 유형의
조항이 실제로 있었다.

이는 이미 이번 조사에서 불가로 확정한 두 사례와 같은 급이다:
- **K-Auction**: "크롤링/스크래핑은 엄격히 금지됩니다" (단어 자체가 명시)
- **the-saleroom.com**: 3.2(c) "systematically and/or regularly downloading … by spidering
  or otherwise" 금지

Artcurial은 "크롤링"이라는 단어 대신 "복제(copying)"라는 더 넓은 표현을 썼지만, 범위와
강도는 동일하거나 그 이상이다("in full **or in part**", "in any format whatsoever" 등
포괄적 문구를 반복). **robots.txt 통과 ≠ ToS 통과**의 또 다른 사례.

→ **작업지시 2번 단계 지침대로 여기서 즉시 중단.**

## 3. SSR 여부 (참고용, 결론에 영향 없음)

절차상 3번 단계도 형식적으로 확인은 했다(ToS가 나중에 완화될 경우를 대비한 참고 기록).
`GET /en/results-auctions-sales` → HTTP 200, 227KB. Nuxt 특유의 `__NUXT_DATA__`/페이로드
JSON이 원본 HTML 안에 그대로 박혀 있고(`"descriptionWithHtml"`, `"Lots 1 to 106 will be sold
at 11:00 am"` 등 실제 콘텐츠 텍스트가 원문에 존재), 헤드리스 브라우저 없이도 읽힌다 —
**SPA 우려는 기술적으로는 해소됨(SSR/하이드레이션 방식)**. 다만 ToS가 막고 있어 이 사실은
현재로선 무의미하다.

## 최종 판정

**불가.** ToS "5. INTELLECTUAL PROPERTY – COPYING" 조항이 카탈로그(작가·작품·낙찰가 등
로트 정보) 전체 또는 일부의 복제를 명시적으로 금지하고 프랑스 지식재산법전 위반 소지까지
적시한다. robots.txt는 통과했지만 계약상 금지가 우선이라는 이 프로젝트의 기존 원칙
(the-saleroom.com·K-Auction 판례와 동일)에 따라 착수하지 않는다. 코드(크롤러/로더)는
작성하지 않았고, DB에도 아무것도 적재하지 않았다.

`docs/경매소스확장_20260922.md` B-5절의 Artcurial 항목은 "**불가 확정**"으로 옮겨야 한다
(이 파일은 오케스트레이터가 직접 반영 — 내가 편집 금지 대상이라 여기 기록만 남긴다).
