# CLAUDE.md

이 파일은 Claude Code가 artrend 프로젝트에서 작업할 때 참고하는 진행상황 요약이다.

## 프로젝트가 뭔지

**아트그래프** — 미술품·경매·미술관 소장품·갤러리·컬렉터 정보를 하나로 잇는 종합 포털.
목표는 검색 UI가 아니라 **자연어로 물으면 근거를 인용해 답하는 LLM 위키**.
전체 배경·아키텍처·예산·로드맵은 [`docs/착수리포트.md`](docs/착수리포트.md)에 정리돼 있다 — 새 세션은 이 문서부터 읽을 것.

**세션 구조(2026-09-17 현재)**: 메인(Fable, 지시·판단·검수 전담) + 워커1(Sonnet, 실행)의 2세션 병렬. 워커 관리감독은 메인에 위임돼 있고, 양쪽 모두 `/loop` 15분 웨이크업으로 사용자 부재 중에도 진행한다. 자율 운영 기준(원칙·승인 필요 항목)은 [`docs/자율운영기준.md`](docs/자율운영기준.md), 현재 세션별 큐·규칙·진행 로그는 [`docs/작업분담_20260915.md`](docs/작업분담_20260915.md)(끝부분이 최신). 새 세션은 시작 시 이 두 문서를 읽고 `/loop`가 켜져 있는지 확인할 것. 세션 간 통신은 `ListAgents`/`SendMessage`(세션 이름은 시작마다 바뀌므로 매번 `ListAgents`로 확인).

## 아키텍처 3줄 요약

원본 수집(`crawlers/` → `crawlers/raw/`) → 정규화 DB(`pipeline/run.py` → 로컬 Postgres, 스키마 `db/migrations/`) → 큐레이션 마크다운(`vault_curated/`, 생성물) + 임베딩(`vault_embeddings`) → LLM 질의응답(`artgraph_chat.py` Text-to-SQL 주 경로, `query_vault.py` 시맨틱 보조).
자동 갱신(로드맵 7)과 GitHub Actions는 아직 없음. `vault/`·`rag/`는 1세대 잔재로 비어 있다.

## 자주 쓰는 명령

모두 저장소 루트에서 실행. Windows 콘솔이 cp949라 `$env:PYTHONIOENCODING='utf-8'`을 먼저 두는 게 안전하다. 테스트 스위트·린터는 없다 — 검증은 각 스크립트의 리포트 모드와 `audit_health.py`로 한다.

```powershell
# 로컬 Postgres(pgportable) — 재부팅 후 수동 기동 필요. 실패 시 pipeline/_pg_server.log 확인
Start-Process C:\pgportable\pgsql\bin\postgres.exe -ArgumentList "-D","C:\pgportable\data","-p","5433"

python pipeline/run.py --site all              # raw → DB 적재(DATABASE_URL 없으면 자동 dry-run)
python pipeline/run.py --site met --dry-run    # DB 없이 파싱만 검증
python pipeline/run.py --site nga --limit 1000 # nga 전용 행 수 제한
python pipeline/apply_migration.py 0012_vault_embeddings_curated.sql   # db/migrations/ 파일 하나 적용(idempotent SQL만)

python pipeline/audit_health.py --json docs/logs/audit_health_YYYYMMDD.json   # 읽기 전용 건강지표(매 작업 후 재실행)
python pipeline/merge_by_authority.py            # 리포트만
python pipeline/merge_by_authority.py --apply    # 반영 — 모든 DB 변경 스크립트가 이 패턴

python pipeline/build_curated_vault.py           # vault_curated/ 재생성(5,100문서)
python pipeline/embed_vault.py --batch-size 64   # vault_curated → vault_embeddings (로컬 e5 모델)
python pipeline/query_vault.py "국립현대미술관" --show   # 고유명사 정확매칭 우선, 시맨틱 폴백
python pipeline/artgraph_chat.py -q "이우환 소장 미술관과 경매 기록" -v   # Text-to-SQL(Gemini, read-only 세션)
python pipeline/artgraph_chat.py -i              # 대화형
```

크롤러는 `python crawlers/<site>.py`로 개별 실행(`already_fetched()`로 재실행 시 중복 요청 없음). `embed_vault.py` 대량 실행 중에는 `query_vault.py`를 같이 돌리지 말 것(같은 로컬 모델을 두 번 올려 메모리 고갈).

## 코드 관례 (새 스크립트는 이대로)

- **DB 접속은 `from db import get_connection` 하나로**(2026-09-17 일원화). 환경변수 `DATABASE_URL` → `pipeline/.env` 순으로 읽고 UTF8을 건다. 접속 문자열 하드코딩 금지. `artist_merge_util.get_conn`은 같은 함수로의 위임이라 기존 import도 유효하다. `pipeline/` 스크립트는 상단에 `sys.path.insert(0, str(Path(__file__).resolve().parent))` 없이도 같은 폴더에서 실행되면 import되지만, 다른 경로에서 부를 때를 위해 넣어 두는 게 관례.
- **DB를 바꾸는 스크립트는 기본이 리포트, `--apply`로만 반영, 재실행해도 결과가 같아야(idempotent) 한다.** 표본을 찍어 사람이 검수한 뒤 apply. 대량 삭제·스키마 변경은 사용자 승인 항목(`docs/자율운영기준.md` §2, 명백한 가비지 예외 포함).
- **병합은 authority ID(ULAN/Wikidata QID) 동일할 때만**(`merge_by_authority.py`, `merge_museums_by_qid.py`). 문자열 유사도·단일연결 체이닝 병합은 과거 오탐 이력이 있어 금지. 동명이인 위험이 있으면 보류가 기본.
- **결손 메타(생년·국적·약력)를 LLM으로 채우지 않는다.** Wikidata/ULAN 매칭으로만 백필. AI 생성 약력은 `artist_bio_generated`에 격리돼 있고 원본 `artists.bio`와 섞지 않는다.
- **신규 소스·크롤러 추가는 사용자 결정 항목**(2026-09-15 재진단 이후). 이미 검증된 소스의 증분·보강만 자율 진행. robots.txt 통과 ≠ ToS 통과 — 새 사이트는 둘 다 확인 후 사용자에게 올린다.
- **테이블 소유권(세션 충돌 방지)**: 메인 = artists·museums·galleries·collectors·provenance_records·gallery_representations. 워커 = auction_lots·auctions·auction_houses·sources·vault_embeddings·exhibitions·exhibition_artists·artist_events·market_stats_kr. 워커는 artists 행을 만들거나 고치지 않는다(로더의 QID 정확일치 연결만 허용).
- `pipeline/.env`에는 `DATABASE_URL`과 `GEMINI_API_KEY`가 있다. 키 값을 출력·로그·문서에 남기지 말 것.
- 스키마 변경은 반드시 `db/migrations/NNNN_*.sql`로 남기고 `apply_migration.py`로 적용한다(0003이 라이브 DB와 마이그레이션이 어긋났던 것을 역기입한 선례).

## 폴더 구조

```
crawlers/          사이트별 크롤러 + common.py(save_raw/already_fetched/with_retry). raw/는 git 미추적(용량)
db/migrations/     0001~0012. 0003은 라이브 스키마 역기입, 0007 entity_kind, 0008 authority ID, 0009 사건, 0011 기관 QID, 0012 curated 임베딩
pipeline/          run.py(적재 실행기) + store.py(PgStore/DryRunStore) + 사이트별 로더 + merge_/backfill_/link_/audit_ 유지보수 스크립트 + Q&A(artgraph_chat/query_vault/embed_vault/build_curated_vault). 분류 색인은 pipeline/README.md(물리 분리 대신 논리 분리, 재실행 금지 이력 스크립트 목록 포함)
pipeline/_scratch/ 일회성 inspect/test/check 스크립트(재실행 보장 없음, DB URL 하드코딩 남아 있어도 손대지 않음)
vault_curated/     build_curated_vault.py 생성물(gitignore). 1세대 vault/·vault_obsidian/은 폐기됨
docs/              설계·진행 문서. docs/logs/에 JSON 로그
rag/, .github/     비어 있음
```

## 로드맵 진행 상황 (8단계 중)

- [x] 1. 대상 사이트 선정 → [`docs/1차크롤링대상.md`](docs/1차크롤링대상.md)
- [x] 2. DB 스키마 설계 → [`docs/db-schema.md`](docs/db-schema.md) + [`db/migrations/0001_init_schema.sql`](db/migrations/0001_init_schema.sql)
- [~] 3. 크롤러 개발 + 초기 적재 — **진행 중**, 아래 "크롤러 상태" 참고
- [~] 4. 마크다운 문서화 + 옵시디언 연동 — 1세대 전체 vault(`vault/`)는 폐기됨. 2세대 `vault_curated/`는 정본화(M6) 이후 V4로 재생성(2026-09-16, `build_curated_vault.py`: entity_kind·authority·전시/수상 반영, 5,100문서). 경위는 [`docs/QA아키텍처.md`](docs/QA아키텍처.md)
- [~] 5. 임베딩·벡터 검색 구축 — 1세대 임베딩은 `vault_embeddings_legacy_20260915`로 보존만. V4 vault_curated 5,100건이 새 `vault_embeddings`(0012)에 임베딩 완료(2026-09-16). `query_vault.py`는 고유명사(작가·미술관·갤러리·경매사) 정확매칭 우선, 시맨틱 폴백
- [~] 6. LLM 질의응답 연결 — `pipeline/artgraph_chat.py`(Text-to-SQL, Gemini)가 주 경로로 확정(2026-09-15). 회귀 10문항 통과(2026-09-16, `docs/logs/chat_회귀_20260916.json`)
- [~] 7. 자동 갱신 파이프라인 — `pipeline/refresh_weekly.ps1`(Bonhams·Wikidata 경매·K-ARTMARKET·Wikidata 사건·갤러리 5곳 전시 + 건강지표 스냅샷, 전부 idempotent, 약 3.5분)를 Windows 작업 스케줄러 `artrend_refresh_weekly`로 **매주 월 08:30** 실행(2026-09-17 등록, PC 꺼져 있었으면 다음 부팅 시 실행, pgportable 미기동 시 자동 기동). 로그 `docs/logs/refresh_YYYYMMDD.log`. 실측·설계 근거는 `docs/갱신잡_20260917.md`. 해제: `schtasks /Delete /TN artrend_refresh_weekly /F`
- [~] 8. QA·상시 운영 — `audit_health.py`가 주간 잡 끝에 자동 실행. chat 회귀 세트 20문항 확대 진행 중(2026-09-17)

## 2026-09-15 재진단 — 신규 소스 추가 중단, 정리 우선

원점 재진단(`C:\Users\CNCITY\.claude\plans\jiggly-mixing-summit.md`) 결과 "5자 관계망"이 아직 성립하지 않음(소장∧경매 작가 교집합 5,186명, 작품 레벨 0건)과 대량 가비지(mia 이중적재 96K, Bonhams 작가 NULL 90K, 익명/국가/기업 작가 ~110K 작품, 임의 환율 시장지표, LLM 생성 약력 혼입)를 확인. **P0 되돌리기 → P1 걷어내기 → P2 정본화(ULAN/QID)** 순으로 진행 중이며 그 전까지 새 소스·크롤러 추가 금지. 세션별 큐·규칙은 [`docs/작업분담_20260915.md`](docs/작업분담_20260915.md), Q&A 구조는 [`docs/QA아키텍처.md`](docs/QA아키텍처.md).

## 크롤러 상태 (자세한 표는 [`docs/크롤러현황.md`](docs/크롤러현황.md))

**동작 확인 완료** (`crawlers/`):
- `met.py` — The Met Open Access API, 테스트 완료
- `aic.py` — Art Institute of Chicago API, 테스트 완료
- `cleveland.py` — Cleveland Museum of Art API, 테스트 완료
- `nga.py` — National Gallery of Art CSV 덤프. `objects.csv`는 provenance 필드에 줄바꿈 포함이라 `wc -l`로는 28만 행처럼 보이지만 실제 레코드는 **145,658건** — DB 적재 완료 (아래 파이프라인 상태 참고)
- `smithsonian.py` — Smithsonian Open Access API. `SMITHSONIAN_API_KEY`는 `crawlers/.env`에 저장(git 추적 안 됨). 유물/과학표본 제외하고 미술 소장 부서만(`ART_UNITS`: SAAM/HMSG/NPG/CHNDM/FSG/NMAfA) 필터링 — **83,386건 전체 수집 완료** (2026-09-02)
- `mmca.py` — 국립현대미술관. 공식 API가 없어 소장품 검색 페이지가 쓰는 내부 JSON 엔드포인트(`/collections/AjaxCollectionsList.do`)를 그대로 이용. robots.txt(2026-09-02 확인)는 `/pr/collectionsGuideList.do` 등 일부만 막고 이 엔드포인트는 허용 — **11,749건 전체 수집 완료** (2026-09-02). 이미지 저작권은 레코드별 `copyrightAllowYn` 필드로 개별 확인 필요
- `common.py` — 공통 저장 유틸. `save_raw`가 `raw/<site>/<id>.json` + `<id>.meta.json` 쌍으로 저장, `with_retry`가 지수 백오프 재시도 담당 (대량 수집 중 타임아웃 한 번에 프로세스 전체가 죽는 문제 겪고 추가함)
- `smk.py` — SMK(덴마크 국립미술관) Open API, 키 불필요. 202,097건 목표
- `moma.py` — MoMA GitHub CC0 데이터셋(Git LFS, `media.githubusercontent.com`에서 받아야 함 — `raw.githubusercontent.com`은 LFS 포인터 파일만 줌). 완료
- `tate.py` — Tate GitHub CC0 데이터셋(`artwork_data.csv` + `artist_data.csv`). 완료, 69,201건
- `galleries.py` — 국내외 갤러리 작가 로스터(작품 아님, 관계 데이터). 11개 갤러리 완료 — 자세한 표는 `docs/크롤러현황.md`. 리만머핀·페로탕은 SPA라 Claude-in-Chrome 브라우저 자동화로 별도 수집(정규 크롤러 경로 아님)

**스켈레톤만 존재, 미완성**:
- `emuseum.py` — 방치. 아래 "제외 결정" 참고.

**제외 결정** (2026-09-02, robots.txt 재확인/스코프 재검토 후 확정):
- **e뮤지엄 / 공공데이터포털 "20개 기관 통합 유물정보" API** — **완전 중단**. 이름 그대로 유물(문화재) 전반(도자기·불상·공예품·고문서 등) 데이터라 프로젝트 스코프(미술품)와 어긋남. 지금까지 확보한 소스만으로도 상당한 규모라 안 채워도 무방. `crawlers/.env`의 `SMITHSONIAN_API_KEY`는 유지, e뮤지엄 키는 발급 신청 자체를 하지 않기로 함.
- **Gagosian** — robots.txt에 `Content-Signal: ai-train=no` + `ClaudeBot`/`GPTBot`/`CCBot`/`Bytespider` 등 AI 봇을 이름으로 명시 차단. 명확한 거부 시그널이라 제외.
- **Hauser & Wirth** — robots.txt 요청 자체가 Vercel 봇 차단(Security Checkpoint)에 막혀 429 응답. 우회는 ToS 위반 소지가 커서 제외.
- **원앤제이갤러리** — 사이트 자체가 HTTP 410(Gone), 서비스 종료/개편 추정.

## 파이프라인 상태 (`pipeline/`)

raw JSON/CSV → `db/migrations/0001_init_schema.sql` 스키마로 정규화하는 스크립트. `store.py`에 `PgStore`(실제 적재)/`DryRunStore`(DB 없이 집계만) 두 구현을 두고 사이트별 로더는 이 인터페이스만 보고 작성했다. 로더는 met/aic/cleveland/nga/smithsonian/mmca/smk/moma/tate/galleries 전부 작성 완료, dry-run 파싱 검증 통과.

- `python pipeline/run.py --site all` — `DATABASE_URL` 환경변수(`pipeline/.env`, git 추적 안 됨) 있으면 실제 적재, 없으면 자동 dry-run. 로더는 `sources.raw_path` 유니크 인덱스로 같은 raw 파일 재적재를 막는다(mia 이중적재 사고 이후)
- (과거 Supabase 시절 메모) "Transaction pooler"(포트 6543)만 IPv4로 응답함 — 현재는 로컬 DB라 해당 없음, `.env` 주석의 Supabase URL을 되살릴 때만 참고
- `PgStore`는 개별 INSERT가 아니라 `execute_values`로 500건 단위 배치 + 배치마다 커밋한다 — 처음엔 행 단위 INSERT로 짰다가 NGA 규모(14만+)에서 네트워크 왕복이 누적돼 감당 안 되고, 하나의 트랜잭션으로 묶으면 pooler가 끊었을 때 전부 롤백되는 문제가 있어 재작업함
- **met/aic/cleveland/nga/smithsonian/mmca/smk/moma/tate/galleries 전부 실제 DB 적재 완료** (2026-09-08 재확인) — `nga` 145,658 / `smithsonian` 83,391 / `mmca` 11,764 / `smk` 201,759 / `moma` 120,803 / `tate` 69,201 / `galleries`(gallery_representations) 4,833. 이 절이 한동안 "적재 전"으로 stale하게 남아있었음 — 실제로는 다른 세션들이 이미 적재 완료한 뒤였음, 재적재 전에는 반드시 DB를 먼저 확인할 것.
- **DB 연결은 로컬 pgportable로 전환됨** — `pipeline/.env`의 `DATABASE_URL`이 `postgresql://postgres@127.0.0.1:5433/artrend`(Supabase URL은 주석 처리돼 백업으로만 남음). 연결 실패 시 `pipeline/_pg_server.log` 먼저 확인.
- NGA `provenancetext`는 구조화된 `provenance_records` 매칭 없이 `artworks.description`에 원문 보존만 함 — 이후 `pipeline/provenance_extract.py`가 이 자유텍스트를 후처리로 역파싱해 `provenance_records`/`collectors`를 채움 (자세한 내용 `docs/정합성작업.md`)
- Getty Provenance Index Sales/Bonhams/Wikidata 경매 데이터, Europeana/V&A/일본 국립미술관 등 대규모 확장 진행 — 최신 현황은 `docs/크롤러현황.md` 참고(이 문서보다 최신)

## 사용자 개입이 필요한 항목 (막혀서 못 넘어간 것들)

- **Rijksmuseum·Europeana** — 정식 API 키 없이 우회 수집 성공(각각 OAI-PMH 엔드포인트 / 시간당 100만 요청 데모키)로 해소됨. Rijksmuseum는 이후 `ConnectTimeout`으로 크롤러가 죽어 재시작 필요할 수 있음(자세한 내용 `docs/크롤러현황.md`).
- **리안갤러리·학고재·일본 국립미술관** — 전부 재확인/판정 완료(리안갤러리는 HTTP로 수집 완료, 학고재는 SPA로 판정해 보류 확정, 일본 국립미술관은 robots.txt 없음/404를 MMCA 초기 사례와 동일하게 판단해 수집 진행 중) — 더 이상 사용자 개입 대기 항목 아님, 자세한 내용 `docs/크롤러현황.md`

## 작업 스타일 메모

- 크롤러는 원본만 저장한다 (정규화는 `pipeline/` 몫). `save_raw()`를 재사용해서 새 크롤러를 추가할 것.
- Windows 콘솔은 기본 cp949라 한글/특수문자(em dash 등) print 시 `UnicodeEncodeError`가 남 — 새 크롤러 스크립트 상단에 `sys.stdout.reconfigure(encoding="utf-8")`를 넣을 것 (기존 크롤러들 참고).
- 크롤러가 이미 저장한 레코드는 `already_fetched()`로 건너뛴다 — 재실행해도 중복 요청 안 함.
- git 저장소 설정 완료, GitHub(`cnesg/artrend`)에 push됨.
