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
pipeline/        raw/ → DB 정규화 스크립트. met/aic/cleveland/nga 실제 Supabase 적재 완료. 아래 "파이프라인 상태" 참고
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
- `nga.py` — National Gallery of Art CSV 덤프. `objects.csv`는 provenance 필드에 줄바꿈 포함이라 `wc -l`로는 28만 행처럼 보이지만 실제 레코드는 **145,658건** — DB 적재 완료 (아래 파이프라인 상태 참고)
- `smithsonian.py` — Smithsonian Open Access API. `SMITHSONIAN_API_KEY`는 `crawlers/.env`에 저장(git 추적 안 됨). 유물/과학표본 제외하고 미술 소장 부서만(`ART_UNITS`: SAAM/HMSG/NPG/CHNDM/FSG/NMAfA) 필터링 — **83,386건 전체 수집 완료** (2026-09-02)
- `mmca.py` — 국립현대미술관. 공식 API가 없어 소장품 검색 페이지가 쓰는 내부 JSON 엔드포인트(`/collections/AjaxCollectionsList.do`)를 그대로 이용. robots.txt(2026-09-02 확인)는 `/pr/collectionsGuideList.do` 등 일부만 막고 이 엔드포인트는 허용 — **11,749건 전체 수집 완료** (2026-09-02). 이미지 저작권은 레코드별 `copyrightAllowYn` 필드로 개별 확인 필요
- `common.py` — 공통 저장 유틸. `save_raw`가 `raw/<site>/<id>.json` + `<id>.meta.json` 쌍으로 저장, `with_retry`가 지수 백오프 재시도 담당 (대량 수집 중 타임아웃 한 번에 프로세스 전체가 죽는 문제 겪고 추가함)

**스켈레톤만 존재, 미완성**:
- `emuseum.py` — 방치. 아래 "제외 결정" 참고.

**제외 결정** (2026-09-02, robots.txt 재확인/스코프 재검토 후 확정):
- **e뮤지엄 / 공공데이터포털 "20개 기관 통합 유물정보" API** — **완전 중단**. 이름 그대로 유물(문화재) 전반(도자기·불상·공예품·고문서 등) 데이터라 프로젝트 스코프(미술품)와 어긋남. 지금까지 확보한 6개 소스(Met/AIC/Cleveland/NGA/Smithsonian/MMCA)만으로도 약 45만 건 규모라 안 채워도 무방. `crawlers/.env`의 `SMITHSONIAN_API_KEY`는 유지, e뮤지엄 키는 발급 신청 자체를 하지 않기로 함.
- **Gagosian** — robots.txt에 `Content-Signal: ai-train=no` + `ClaudeBot`/`GPTBot`/`CCBot`/`Bytespider` 등 AI 봇을 이름으로 명시 차단. 명확한 거부 시그널이라 제외.
- **Hauser & Wirth** — robots.txt 요청 자체가 Vercel 봇 차단(Security Checkpoint)에 막혀 429 응답. 우회는 ToS 위반 소지가 커서 제외.

## 파이프라인 상태 (`pipeline/`)

raw JSON/CSV → `db/migrations/0001_init_schema.sql` 스키마로 정규화하는 스크립트. `store.py`에 `PgStore`(실제 적재)/`DryRunStore`(DB 없이 집계만) 두 구현을 두고 사이트별 로더는 이 인터페이스만 보고 작성했다.

- `python pipeline/run.py --site all` — `DATABASE_URL` 환경변수(`pipeline/.env`, git 추적 안 됨) 있으면 실제 적재, 없으면 자동 dry-run
- **Supabase 연결은 반드시 "Transaction pooler"(포트 6543) 사용** — "Direct connection"(포트 5432) 호스트는 IPv6 전용으로만 응답해서 IPv6 미지원 네트워크에서 연결 자체가 실패함 (겪은 이슈, 2026-09-02)
- `PgStore`는 개별 INSERT가 아니라 `execute_values`로 500건 단위 배치 + 배치마다 커밋한다 — 처음엔 행 단위 INSERT로 짰다가 NGA 규모(14만+)에서 네트워크 왕복이 누적돼 감당 안 되고, 하나의 트랜잭션으로 묶으면 pooler가 끊었을 때 전부 롤백되는 문제가 있어 재작업함
- **met(6)/aic(5)/cleveland(5)/nga(145,658) 전부 실제 Supabase DB 적재 완료** (2026-09-02) — `sources` 17건, `artists` 13,230명, `artworks`/`museum_holdings` 145,674건
- NGA `provenancetext`는 구조화된 `provenance_records` 매칭 없이 `artworks.description`에 원문 보존만 함 — 소유자(컬렉터/미술관 등) 개체 인식·매칭은 별도 작업으로 남겨둠

## 사용자 개입이 필요한 항목 (막혀서 못 넘어간 것들)

- **다른 사유 갤러리(Pace, David Zwirner, White Cube, 국내 국제갤러리·PKM·갤러리현대 등) robots.txt/ToS 개별 확인** — Gagosian/Hauser & Wirth는 판정 완료(둘 다 제외), 나머지는 미조사

## 작업 스타일 메모

- 크롤러는 원본만 저장한다 (정규화는 `pipeline/` 몫, 아직 미착수). `save_raw()`를 재사용해서 새 크롤러를 추가할 것.
- Windows 콘솔은 기본 cp949라 한글/특수문자(em dash 등) print 시 `UnicodeEncodeError`가 남 — 새 크롤러 스크립트 상단에 `sys.stdout.reconfigure(encoding="utf-8")`를 넣을 것 (기존 크롤러들 참고).
- 크롤러가 이미 저장한 레코드는 `already_fetched()`로 건너뛴다 — 재실행해도 중복 요청 안 함.
- 이 프로젝트는 아직 git 저장소가 아님 (로드맵 체크리스트의 "GitHub 저장소 생성" 항목 미완료).
