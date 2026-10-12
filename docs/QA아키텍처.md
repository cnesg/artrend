# Q&A 아키텍처 현황 — 2026-09-15 기준 (로드맵 4~6단계의 실제 상태)

`CLAUDE.md` 로드맵에는 4(마크다운 문서화)·5(임베딩)·6(LLM 질의응답)이 미착수로 적혀 있지만,
실제로는 **한 번 만들었다가(09-03~09-09) 버리고(09-15) 다른 구조로 대체 중**이다.
이 문서는 그 경위와 현재 상태를 기록한다. 세 세션이 서로 다른 그림을 갖고 일하지 않도록
Q&A 관련 변경은 여기에만 기록한다.

## 1. 1세대 (2026-09-03 ~ 09-09): 전체 vault + 로컬 임베딩 RAG — **폐기됨**

- `pipeline/export_vault.py`가 DB 전체를 `vault/`(작가 20만·작품 250만 마크다운)로 내보내고,
  `pipeline/embed_vault.py`가 `intfloat/multilingual-e5-small`(384차원, 로컬)로 임베딩해
  `vault_embeddings`(float4[] 컬럼, pgvector 없음)에 저장, `pipeline/query_vault.py`가
  코사인 top-k → Gemini 답변 생성.
- 발견된 결함: (a) export가 경매 기록을 아예 안 내보내던 것(09-04 수정), (b) 소형 모델이
  "Rembrandt van Rijn" vs "Rembrandt van Rhijn" 같은 고유명사 변형을 구분 못 해 랭킹 실패 →
  하이브리드(이름 정확매칭 우선, 시맨틱 폴백)로 우회(09-05, 커밋 49c0803).
- **09-15 현재**: `vault/`·`vault_obsidian/` 폴더는 디스크에 없다(삭제 경위 미기록).
  `vault_embeddings` 1,280,492건은 존재하지 않는 파일 경로를 가리키는 dead weight.
  `query_vault.py`의 `VAULT_ROOT`도 `vault/`라 현재 동작 불가.
- 처분(작업분담 §W4): 테이블을 `vault_embeddings_legacy_20260915`로 rename만 하고 보존.
  2세대 방향이 확정되면 삭제.

## 2. 2세대 (2026-09-14 ~ 15): 큐레이티드 vault + Text-to-SQL — **현재 진행형, 검증 전**

- `pipeline/build_curated_vault.py` → `vault_curated/`: 작가 2,500 / 작품 1,200 / 미술관 400 /
  갤러리 250 / 경매사 250 / 컬렉터 500 = 5,100 문서. 선별은 **카운트 기반 스코어**
  (`reps*100 + lots*3 + holdings*1`)라 소스 편향을 그대로 승격시킨다(대시보드 TOP20에
  "China"·"Italian"·"Carven"·담배회사가 올라온 원인). 재설계 필요.
- `pipeline/artgraph_chat.py`: 질문 → (엔티티 힌트 추출) → Gemini Text-to-SQL(SELECT만) →
  실행 → Gemini 답변 합성. 정형 질문(소장 수, 경매 기록, 전속 갤러리)에는 RAG보다 정확한
  방향이 맞다. 단 `sources.url`을 인용하라고 프롬프트에 적혀 있으나 `sources.url`은 100%
  NULL이라 실제 인용은 `site_name`뿐.
- 같은 날 붙은 부속물 중 **되돌려야 하는 것**(진단 §3-2):
  - `enrich_artist_bios.py`: Gemini 생성 한국어 약력 2,499건을 `artists.bio`에 원본과 구분
    없이 저장 → `artist_bio_generated`로 격리(마이그레이션 0006, `isolate_generated_bios.py`).
  - `enrich_auction_db.py`: 임의 환율(livres×0.5 등)로 `price_usd` + `artist_market_metrics`
    → 역사 통화·1970년 이전은 NULL, metrics 테이블 삭제(작업분담 §W2).
  - `enrich_artwork_images.py`: `artworks.image_url` 125,265건 — 유지(Open Access URL, 문제 없음).
- 스키마 변경이 전부 라이브 DB에만 있었음 → `db/migrations/0003~0006`으로 역기입 중.

## 3. 확정 방향 (2026-09-15, 메인 세션 결정 — 사용자 위임)

1. **Text-to-SQL(정형)이 주 경로.** 근거 인용은 `sources.site_name` + 소장관/경매사 이름으로
   하고, 답변 프롬프트에 "데이터 범위: 미술관 소장(주로 구미 대형관), 경매는 1675~1944 유럽
   판매 아카이브(Getty)+Bonhams(2003~), 한국 경매 없음"을 고정 문구로 넣는다.
2. **서술형 질문은 `vault_curated` 임베딩으로 보조.** 전체 260만 문서 재임베딩은 하지 않는다.
3. **생성 약력은 답변에 쓰되 반드시 `[AI 생성, 미검증]` 표기.** `artists.bio`(원본)와
   `artist_bio_generated`를 구분해 프롬프트에 넘긴다.
4. 큐레이션 선별은 카운트가 아니라 **연결성 기준**(소장∧경매∧갤러리 중 2개 이상 + authority ID
   보유)으로 재설계 — 정본화(작업분담 §M6) 이후.
5. 자동 갱신(로드맵 7)은 P0~P1 정리 전 착수 금지.

## 4. 변경 로그
- 2026-09-15: 문서 신설(메인). 1세대 폐기 상태·2세대 현황·되돌릴 항목 기록.
