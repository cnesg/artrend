# Deutscher and Hackett(호주) 조사 — 2026-09-22

## 최종 판정: 불가 (착수 중단)

## 조사 순서 및 근거

### 1. robots.txt — 우호적
`https://www.deutscherandhackett.com/robots.txt` (직접 확인):
```
User-Agent: *
Allow: /
Disallow: /api/
Disallow: /forgot-password
Disallow: /reset-password
Disallow: /search

Host: https://www.deutscherandhackett.com
Sitemap: https://www.deutscherandhackett.com/sitemap_index.xml
```
전면 허용, AI 봇 개별 차단 없음. `lot-sitemap.xml` ×14개가 로트 URL을 그대로 제공
(`sitemap_index.xml` 확인, 로트 URL이 전체 사이트맵의 대부분을 차지).

### 2. 이용약관 — **명시적 금지 확인, 여기서 중단**

정적 페이지 사이트맵(`page-sitemap.xml`)에서 약관 페이지 2개를 찾음:
- `https://www.deutscherandhackett.com/buying-and-selling-art-guide-terms-and-conditions/`
  (경매 이용약관 본문, "Conditions of Business" 성격)
- `https://www.deutscherandhackett.com/terms-and-conditions-online-section/`
  (D+H Online 타임드 경매 안내 — 약관 전문은 별도 페이지 링크만 있고 이 페이지 자체엔 본문 없음)

첫 번째 페이지 **제7조(Copyright)**에 명시적 금지 조항이 있음(직접 확인, 원문 인용):

> "The copyright in the images and illustrations contained in this website may be owned by
> third parties and used under licence by deutscher and hackett."
>
> "As between deutscher and hackett and the users of this website, deutscher and hackett
> retains all rights in the images and illustrations."
>
> **"deutscher and hackett retains copyright in the text contained in this website."**
>
> **"All users of this website must not reproduce or otherwise use the images,
> illustrations or text without prior written consent."**

"크롤링/스크래핑"이라는 단어는 없지만, **"text"에 대한 저작권을 명시적으로 주장하고
"reproduce or otherwise use ... text ... without prior written consent"로 이미지뿐 아니라
텍스트까지 무단 복제·이용을 포괄적으로 금지**한다. 로트 텍스트(작가·작품명·낙찰가 등)를
DB에 저장하는 행위는 "text의 reproduce/use"에 해당하므로 이 조항에 정면으로 걸린다.

`docs/경매소스확장_20260922.md` B-4절의 기존 불가 확정 사례와 동일 패턴:
- **Est-Ouest Auctions**(일본): "이미지·텍스트의 무단 다운로드 및 사용" 명시 금지 — 이번 건과
  거의 동일한 문구 구조.
- **SBI Art Auction**(일본): "콘텐츠를 복제·보존·가공" 금지 — 같은 취지.

robots.txt 통과만으로 진행하면 이 프로젝트가 이미 여러 번 확인한 "robots 통과 ≠ ToS 통과"
원칙(the-saleroom.com 사례)을 어기게 됨. **크롤러/로더 작성하지 않고 여기서 중단.**

### 3. 구조 확인 — 진행 안 함
ToS에서 이미 불가 판정이 나서 3단계(과거 낙찰결과 페이지 SSR 여부 확인)는 진행하지 않았다.
참고로 sitemap에 `lot-sitemap.xml` ×14, `auction-sitemap.xml`이 있어 구조적으로는
SSR·정적 텍스트일 가능성이 높아 보이나(사이트맵에 개별 로트 URL이 그대로 나열됨), 확인은
의미가 없어 생략.

## 적재 건수
0건 (착수하지 않음).

## pipeline/run.py에 추가할 내용
없음 (크롤러/로더 미작성).

## 결론
Deutscher and Hackett — **불가, 영구 제외 권장**. robots.txt는 열려 있지만 이용약관
제7조가 이미지뿐 아니라 텍스트까지 "무단 복제·이용 금지, 사전 서면 동의 필요"를 명시해
Est-Ouest Auctions·SBI Art Auction과 동급의 명시적 거부 사례로 분류한다.
