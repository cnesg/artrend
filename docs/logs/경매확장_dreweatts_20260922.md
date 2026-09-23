# Dreweatts(dreweatts.com) 재조사 — 2026-09-22

## 최종 판정: **불가 (착수 안 함)**

`docs/경매소스확장_20260922.md` B-5절의 "판단 보류" 상태를 해소하기 위해 재확인했다.
robots.txt는 통과하지만, 이용약관(Terms of Use, `/terms-and-conditions/` 페이지 내 "INTELLECTUAL
PROPERTY" 섹션)에 **일반적이지만 명확한 사용 제한 조항**이 있어 착수하지 않았다.

작업 지시서(4단계)에 따라 "약관에 금지 조항이 없으면 진행, 있으면 즉시 중단·기록"이라는 조건에
해당한다고 판단했다.

---

## 1. robots.txt (2026-09-22 재확인)

```
User-agent: *
Disallow:
Sitemap: https://www.websitedomain.co.uk/sitemap-xml
```

- 전면 허용(`Disallow:`이 비어 있음) — B-5절 초기 기록과 동일하게 재확인됨.
- `Sitemap` 값이 실제 도메인이 아니라 템플릿 플레이스홀더(`websitedomain.co.uk`) 그대로 방치돼
  있음 — sitemap은 쓸 수 없고, 페이지 목록은 사이트 내비게이션으로 직접 찾아야 함(단, 이번엔
  이 단계까지 가지 않았음).

## 2. 이용약관(Terms of Use) — 전문 확인 결과

URL: `https://www.dreweatts.com/terms-and-conditions/` (SSR, 281,994 바이트, 텍스트만 약 181,000자)

이 페이지는 경매 매수/매도 조건(Conditions of Sale/Purchase)과 웹사이트 이용약관(Terms of Use)이
하나로 합쳐진 문서다.

**키워드 전수 검색 결과** (`scrap`, `crawl`, `spider`, `data min`, `harvest`, `robot`, `automat`,
`systematic`, `reproduc`, `extract`, `copying`, `downloading`, `commercial use` 등):
- `scraping`/`crawling`/`spider`/`data mining`/`harvest`/`robot` 계열 키워드는 **단 하나도 검출되지
  않음** (지시서에서 확인하라고 한 정확한 문구들은 없음).

**그러나 "INTELLECTUAL PROPERTY" 섹션(조항 7~9)에 다음 조항이 있다** (원문):

> 7. All materials on the Website and all intellectual property rights in the Website are owned,
> licensed to and/or controlled by Dreweatts and its licensors. All material on the Website is
> protected by copyright. **Permission is granted only to electronically copy and/or print in hard
> copy portions of the Website for personal, non-commercial purposes. Any other use of the
> materials on the Website (including but not limited to making such material available on any
> other website, online service, social networking site or networked computer environment) is
> strictly prohibited unless otherwise expressly agreed by us.**

> 9. If you print off, copy or download any part of the Website in breach of these Terms of Use,
> your right to use the Website will cease immediately and you must, at our option, return or
> destroy any copies of the materials you have made.

추가로 조항 11(링킹 금지)도 있으나 이건 직접 해당사항 아님(딥링크/프레이밍 금지 — 우리는 프레이밍
안 함).

### 판단 근거

- 이 조항은 K옥션 푸터 고지("크롤링/스크래핑 엄격히 금지")처럼 **크롤링을 콕 집어 부르는 문구는
  아니다** — 그런 의미에서 지시서가 요구한 "정확한 금지 키워드"는 검출되지 않은 게 사실이다.
- 다만 **"personal, non-commercial purposes 외의 모든 사용은 금지"**라는 포괄 조항이고, 명시적으로
  금지되는 예시로 **"making such material available on any other... networked computer environment"**를
  들고 있다. 이 프로젝트의 실제 용도(정규화 DB → `vault_curated/` → 임베딩 → `artgraph_chat.py`
  LLM Q&A로 원본 사실관계를 재서빙)는 이 예시와 정확히 겹친다 — 개인적·비상업적 열람이 아니라
  구조화된 데이터베이스로 재구성해 별도 서비스로 제공하는 것이기 때문이다.
- B-4절의 the-saleroom.com("systematically and/or regularly downloading … by spidering or
  otherwise" 명시 금지)만큼 크롤링을 직접 겨냥한 문구는 아니지만, **효과 면에서는 같은 결론에
  도달한다** — "그 외 용도는 사전 서면 동의 없이 금지"라는 조항이 있고 우리는 그 동의를 받지
  않았다.
- 비교: 이번에 실제 착수한 Villa Grisebach·칸옥션·Lempertz(미착수지만 확인됨)의 약관에는 이런
  "personal, non-commercial use only, 그 외 금지" 조항 자체가 없었다 — 저작권 고지는 있어도
  사용 범위를 이렇게 좁게 못박지 않았다. Dreweatts는 이번 조사 대상 중 **이 조항이 명시적으로
  존재하는 첫 사례**다.

**결론: 명백한 "가능" 판정을 내리기엔 근거가 부족하고, 오히려 실사용 목적과 정면으로 충돌하는
조항이 발견됐다. 지시서의 "없으면 진행, 있으면 즉시 중단" 기준에 따라 여기서 중단한다.**

## 3. 하지 않은 것

- 과거 낙찰 결과 페이지(`/whats-on/past-auctions` 등) 구조 확인 — ToS 단계에서 중단 조건에
  해당해 진행하지 않았다(지시서 3단계는 "약관 통과 후"를 전제).
- `crawlers/dreweatts.py` / `pipeline/dreweatts.py` 작성 — 미작성.
- DB 적재 — 없음.

## 4. `docs/경매소스확장_20260922.md` B-5절에 반영할 문구 (오케스트레이터용, 이 파일은 직접 수정 안 함)

B-5 "판단 보류" 표의 Dreweatts 행을 B-4 "불가 확정" 표로 옮기고 사유를 다음과 같이 정리 제안:

> **Dreweatts**(영국) — robots.txt는 전면 허용(`Disallow:` 없음, sitemap은 플레이스홀더라 무용)이나,
> 이용약관 "INTELLECTUAL PROPERTY" 조항(7번)이 "personal, non-commercial purposes" 외의 모든 이용을
> 금지하고 그 예시로 "다른 온라인 서비스·networked computer environment에 자료를 이용 가능하게 하는
> 것"을 명시 — 크롤링이라는 단어는 없지만 이 프로젝트의 실제 용도(정규화 DB + Q&A 재서빙)와 정면
> 충돌해 불가로 판정 (2026-09-22 재조사).

## 5. 결론 요약 (오케스트레이터 보고용)

- 최종 판정: **불가(보류 아님, 명확히 중단)** — robots.txt는 통과하나 ToS의 "personal/non-commercial
  use only, 그 외 금지" 조항이 이 프로젝트 용도와 충돌.
- `pipeline/run.py`에 추가할 항목 없음.
- 크롤러/로더 파일 생성 없음, DB 적재 없음.
