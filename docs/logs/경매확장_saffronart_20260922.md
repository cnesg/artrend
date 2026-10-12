# Saffronart(인도) 경매 소스 조사 — 2026-09-22

## 결론: 불가 확정 (ToS 명시 금지) — 크롤러 착수하지 않음

`docs/경매소스확장_20260922.md`의 판정 기준(robots.txt 통과 **+** ToS 명시 허용 둘 다 확인된
소스만 수집)에 따라 조사했고, **ToS 단계에서 명시적 금지 조항을 발견해 중단**했다. B-4절의
the-saleroom.com(3.2(c) "systematically and/or regularly downloading … by spidering or
otherwise" 금지), SBI/Est-Ouest("제3자 정보개시 금지")와 동일한 패턴의 "robots는 통과하지만
ToS가 막는" 사례다.

## 1. robots.txt (`https://www.saffronart.com/robots.txt`, 직접 확인)

```
User-agent: *
Disallow: /Xml/
Disallow: /auction/auctions02/
Disallow: /auctions/*-3680
Disallow: /customauctions/*-3680
Disallow: /auctions/*eid=3680*
Disallow: /customauctions/*eid=3680*
Disallow: /auctions/*-3681
Disallow: /customauctions/*-3681
Disallow: /auctions/*eid=3681*
Disallow: /customauctions/*eid=3681*
Disallow: /membership/*
Disallow: /slideshow/AuctionSlideShowDisplay.aspx*

Sitemap: http://www.saffronart.com/sitemap.aspx
```

특정 경매 회차(eid 3680/3681)와 `/Xml/`, `/membership/` 등 일부만 차단 — 일반 경매결과·
작품 페이지 경로는 robots 기준으로는 **통과**로 보인다. (이 프로젝트가 "가능"으로 판단하려면
robots만으로는 부족하고 ToS까지 통과해야 한다는 게 오늘 확정한 원칙.)

## 2. ToS 원문 확인 — 여기서 금지 조항 발견, 중단 결정

`https://www.saffronart.com/sitepages/terms.aspx`("TERMS AND CONDITIONS FOR SALE")는
구매 절차 관련 조항뿐이고, 마지막에 "Please refer to the Disclaimer and the terms of our
Privacy Policy, which together with these terms and conditions govern your use of the
website"라고 안내해 실제 사이트 이용약관은 별도 페이지에 있었다.

`https://www.saffronart.com/sitepages/disclaimer.aspx`("DISCLAIMER & TERMS AND CONDITIONS
OF USE", `www.saffronart.com`·`www.storyltd.com` 등 전 사이트 공통 적용) 전문 확인 결과,
**"PERSONAL AND NON-COMMERCIAL USE LIMITATION"** 절에 다음 조항이 있다:

> "You shall use the Sites in good faith and for the essential purposes for which the
> Sites are intended. Unless otherwise specified, the Sites are for your personal and
> non-commercial use. **You may not modify, copy, distribute, transmit, display, perform,
> reproduce, publish, license, create derivative works from, transfer, or sell any
> information, software, products or services obtained from the Sites.**"

이 프로젝트의 수집·적재 행위(작가명·작품명·낙찰가 등 정보를 가져와 DB에 복제·저장하고
`vault_curated`/챗봇 응답으로 재가공·재게시하는 것)는 이 조항이 금지하는 "copy … reproduce …
transfer"에 정확히 해당한다. 또한 "personal and non-commercial use"로 용도를 한정하는데
이 프로젝트(회사 소유 서비스 개발)는 그 범위를 벗어난다.

추가로 확인한 관련 조항:
- **NO UNLAWFUL OR PROHIBITED USE**: "You may not obtain or attempt to obtain any materials
  or information through any means not intentionally made available or provided for through
  the Sites." — 자동화 수집이 "의도적으로 제공된 수단"이 아니라는 해석 여지도 있음(보조 근거).
- **COPYRIGHT AND TRADEMARK NOTICES**: "All contents of the Sites are copyright protected in
  favour of Saffronart and/or its suppliers."
- 크롤링/스크래핑/robot/spider/data mining 같은 단어 자체는 없지만(K-Auction·the-saleroom
  처럼 "크롤링"을 문자 그대로 쓰지는 않음), "copy/reproduce/transmit/distribute any
  information … obtained from the Sites"라는 표현이 **범위상 더 넓어서** 사실상 동일하거나
  더 강한 금지로 판단했다.

## 3. 과거 경매결과(Price Database) 페이지 구조 — 확인은 했으나 ToS 때문에 무의미

ToS 위반이 확정된 시점에서 4번(크롤러 작성) 이후 단계는 진행하지 않았다. 참고로 구조만
가볍게 확인한 결과(적재 목적 아님, 순수 판정 보조):
- `saffronart.com`이 "Price Database"를 표방하는 별도 공개 검색 페이지가 있다는 세간의
  설명과 달리, 위 robots.txt·ToS는 `www.saffronart.com` 전체(경매결과 포함)에 적용된다.
  별도 서브도메인 여부는 확인하지 않았다 — ToS가 이미 막았으므로 불필요.

## 4. 판단 근거 요약 (`docs/경매소스확장_20260922.md` 대조)

| 항목 | Saffronart | 대조 사례 |
|---|---|---|
| robots.txt | 대부분 허용(특정 eid만 차단) | Dorotheum(robots는 허용이나 실질 차단)과 유사하게 "robots만으로 판단 불가" 사례 |
| ToS 금지 문구 | "copy, distribute, transmit, reproduce … any information … obtained from the Sites" (개인/비상업 목적 한정) | the-saleroom.com 3.2(c)와 동일 패턴 — **robots 통과 ≠ ToS 통과**의 또 다른 사례 |
| 용도 제한 | "personal and non-commercial use"만 허용 | 이 프로젝트는 회사 서비스 개발이라 애초에 허용 범위 밖 |

**최종 판정: 불가.** `crawlers/saffronart.py`, `pipeline/saffronart.py` 작성하지 않았고
DB 적재도 하지 않았다. `pipeline/run.py`에 추가할 항목 없음.
