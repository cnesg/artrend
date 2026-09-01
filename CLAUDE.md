# CLAUDE.md

이 파일은 Claude Code가 artrend 프로젝트에서 작업할 때 참고하는 진행상황 요약이다.

## 프로젝트가 뭔지

**아트그래프** — 미술품·경매·미술관 소장품·갤러리·컬렉터 정보를 하나로 잇는 종합 포털.
목표는 검색 UI가 아니라 **자연어로 물으면 근거를 인용해 답하는 LLM 위키**.
전체 배경·아키텍처·예산·로드맵은 [`docs/착수리포트.md`](docs/착수리포트.md)에 정리돼 있다 — 새 세션은 이 문서부터 읽을 것.

## 아키텍처 3줄 요약

원본 수집(`crawlers/`) → 정규화 DB(`db/`, Supabase Postgres) → 마크다운 위키(`vault/`, 옵시디언용) + 임베딩/RAG(`rag/`) → LLM 질의응답.
매일 GitHub Actions(`.github/workflows/`)로 변경분만 재반영. 옵시디언은 사람이 검수하는 창구일 뿐 자동화 엔진이 아님.

## 폴더 구조

```
crawlers/raw/    원본 JSON/CSV 보존 (크롤러가 여기 저장, git 추적 대상 아님 — 용량 큼)
db/migrations/   Supabase 스키마 SQL
pipeline/        raw/ → DB 정규화 스크립트. met/aic/cleveland/nga 로더 작성 완료, dry-run 검증 끝. 아래 "파이프라인 상태" 참고
vault/           (아직 비어있음) 옵시디언 볼트 — 작가/작품/경매/미술관/갤러리/컬렉터별 폴더만 만들어둠
rag/             (아직 비어있음) 임베딩 + 검색 + 질의응답
.github/workflows/  (아직 비어있음)
docs/            설계 문서 — 아래 "읽어야 할 문서" 참고
```

## 로드맵 진행 상황 (8단계 중)

- [x] 1. 대상 사이트 선정 → [`docs/1차크롤링대상.md`](docs/1차크롤링대상.md)
- [x] 2. DB 스키마 설계 → [`docs/db-schema.md`](docs/db-schema.md) + [`db/migrations/0001_init_schema.sql`](db/migrations/0001_init_schema.sql)
- [~] 3. 크롤러 개발 + 초기 적재 — **진행 중**, 아래 "크롤러 상태" 참고
- [ ] 4. 마크다운 문서화 + 옵시디언 연동
- [ ] 5. 임베딩·벡터 검색 구축
- [ ] 6. LLM 질의응답 연결
- [ ] 7. 자동 갱신 파이프라인
- [ ] 8. QA·상시 운영

## 크롤러 상태 (자세한 표는 [`docs/크롤러현황.md`](docs/크롤러현황.md))

**동작 확인 완료** (`crawlers/`):
- `met.py` — The Met Open Access API, 테스트 완료
- `aic.py` — Art Institute of Chicago API, 테스트 완료
- `cleveland.py` — Cleveland Museum of Art API, 테스트 완료
- `nga.py` — National Gallery of Art CSV 덤프, 핵심 4개 파일(126MB) 다운로드 완료. `objects.csv`에 `provenancetext` 필드가 이미 포함돼 있어 프로버넌스 체인 구축에 최우선으로 쓸 소스
- `common.py` — 공통 저장 유틸 (`save_raw`가 `raw/<site>/<id>.json` + `<id>.meta.json` 쌍으로 저장, 출처 메타데이터 자동 기록)

**스켈레톤만 존재, 미완성**:
- `emuseum.py` — 국립중앙박물관 e뮤지엄 API. **API 키가 있어야 정확한 엔드포인트를 알 수 있음** (data.go.kr 로그인 후 활용신청). 키 발급되면 TODO 2곳(엔드포인트, 응답 파싱 경로)만 채우면 됨.

**미착수**:
- Smithsonian — API 키(api.data.gov) 필요
- 사유 갤러리 — robots.txt는 조사 완료(대부분 허용), 실제 크롤링은 ToS 판단 후

## 파이프라인 상태 (`pipeline/`)

raw JSON/CSV → `db/migrations/0001_init_schema.sql` 스키마로 정규화하는 스크립트. DB 미연결 상태에서도 파싱 로직을 검증할 수 있도록 `store.py`에 `PgStore`(실제 적재)/`DryRunStore`(집계만) 두 구현을 두고 사이트별 로더(`met.py`/`aic.py`/`cleveland.py`/`nga.py`)는 이 인터페이스만 보고 작성했다.

- `python pipeline/run.py --site all` — `DATABASE_URL` 환경변수 있으면 실제 적재, 없으면 자동 dry-run
- `python pipeline/run.py --site nga --limit 1000` — NGA는 `objects.csv` 28만 행이라 `--limit`으로 검증 가능
- met/aic/cleveland/nga 전부 dry-run 파싱 테스트 완료 (2026-09-02)
- **Supabase 프로젝트가 아직 없어 실제 DB 적재는 못 함** — 아래 "사용자 개입 필요" 참고
- NGA `provenancetext`는 구조화된 `provenance_records` 매칭 없이 `artworks.description`에 원문 보존만 함 — 소유자(컬렉터/미술관 등) 개체 인식·매칭은 별도 작업으로 남겨둠

## 사용자 개입이 필요한 항목 (막혀서 못 넘어간 것들)

- **Supabase 무료 프로젝트 생성 + `DATABASE_URL` 발급** — 이게 있어야 `pipeline/run.py`가 dry-run이 아니라 실제로 적재함
- **e뮤지엄 API 키 발급** — data.go.kr 계정 필요
- **Smithsonian API 키 발급** — api.data.gov 계정 필요
- **MMCA(국립현대미술관) 크롤링 여부** — robots.txt가 아예 없어(HTTP 400) 정책 불명, 기관 직접 문의 권장
- **Gagosian 제외 여부** — robots.txt에 `Content-Signal: ai-train=no` 명시, AI 학습 목적 사용 금지 시그널이라 기본적으로 제외 권장하나 최종 판단 필요
- **Hauser & Wirth** — robots.txt 요청이 429로 막힘, 재시도 정책/ToS 확인 필요
- **갤러리 이용약관(ToS) 본문 검토** — robots.txt 확인은 끝났지만 이건 기술적 허용일 뿐 법적 허가가 아님

## 작업 스타일 메모

- 크롤러는 원본만 저장한다 (정규화는 `pipeline/` 몫, 아직 미착수). `save_raw()`를 재사용해서 새 크롤러를 추가할 것.
- Windows 콘솔은 기본 cp949라 한글/특수문자(em dash 등) print 시 `UnicodeEncodeError`가 남 — 새 크롤러 스크립트 상단에 `sys.stdout.reconfigure(encoding="utf-8")`를 넣을 것 (기존 크롤러들 참고).
- 크롤러가 이미 저장한 레코드는 `already_fetched()`로 건너뛴다 — 재실행해도 중복 요청 안 함.
- 이 프로젝트는 아직 git 저장소가 아님 (로드맵 체크리스트의 "GitHub 저장소 생성" 항목 미완료).
