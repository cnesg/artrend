---
name: artrend-pipeline
description: >-
  artrend(아트그래프) 프로젝트에서 DB 쿼리를 짜거나, pipeline/·crawlers/ 스크립트를 만들거나 고치거나,
  백그라운드로 대량 작업(크롤링·백필·임베딩)을 돌리거나, "왜 안 되지/왜 멈췄지" 류의 디버깅을 할 때
  반드시 먼저 읽어라. 이 프로젝트에서 이미 여러 번 반복된 함정(느린 쿼리, pgportable 불안정, 조용한
  dry-run, 인코딩 에러, 가짜 "완료" 로그)을 다시 밟지 않기 위한 실전 체크리스트다. "artrend", "아트그래프",
  "pipeline/run.py", "pgportable", "crawlers/raw" 같은 키워드가 나오면 이 스킬을 켜라.
---

# artrend 파이프라인 작업 스킬

이 프로젝트는 미술품·경매·소장·갤러리 데이터를 크롤링(`crawlers/`) → 정규화 DB(`db/`, Postgres) →
마크다운 위키/임베딩(`vault_curated/`, `rag/`) → LLM Q&A(`pipeline/artgraph_chat.py`)로 잇는
개인 프로젝트다. 전체 배경은 `docs/착수리포트.md`, 최신 상태는 프로젝트 루트 `CLAUDE.md`를 먼저 봐라 —
이 스킬은 그 위에 얹히는 "운영 중 반복해서 밟은 함정" 모음이다.

## 1. DB 연결 — 매번 틀리기 쉬운 것부터

- 로컬 Postgres(pgportable)가 기본 연결 대상이다: `postgresql://postgres@127.0.0.1:5433/artrend`
  (`pipeline/.env`의 `DATABASE_URL`). Supabase URL은 주석 처리된 백업일 뿐 — 지금은 안 씀.
- **`pipeline/run.py` 등은 `os.environ["DATABASE_URL"]`만 보고 `.env` 폴백이 없다.** 그냥
  `python pipeline/run.py ...`로 실행하면 환경변수가 없어서 **조용히 dry-run으로 빠진다** — 에러도
  경고도 없이 그냥 아무것도 안 적재된다. 이게 "왜 실행했는데 DB에 안 들어갔지"의 1순위 원인이다.
- Bash 도구는 호출마다 셸 상태가 리셋된다. **백그라운드로 잡을 띄울 때는 같은 커맨드 안에서
  `DATABASE_URL=... nohup python3 ... &`처럼 인라인으로 export해라.** 미리 export해두고 다음 호출에서
  실행하면 그 export는 이미 사라진 뒤다.
- (과거 Supabase를 쓰던 시절 메모, 다시 쓸 일 있으면) Supabase는 "Transaction pooler"(6543번 포트)만
  써야 한다 — "Direct connection"(5432)은 IPv6 전용 호스트라 IPv6 안 되는 네트워크에서 연결 자체가 실패함.

## 2. 스키마 — 코드 짜기 전에 확인할 3가지 관례

정확한 컬럼은 `db/migrations/*.sql`이 진짜 소스이니 최신 파일을 grep해서 확인해라(이 문서는 요약일 뿐,
마이그레이션이 계속 추가되는 중이라 금방 stale해진다). 그래도 자주 쓰는 관례:

- **모든 레코드는 출처를 인용한다.** `sources` 테이블(원본 URL·수집시각·원본 파일 경로)을 가리키는 게
  원칙 — 새 필드를 채울 때 "이 값 어디서 왔는지"를 항상 같이 생각해라. `crawlers/common.py`의
  `save_raw()`가 원본 저장 + `.meta.json`을, `already_fetched()`가 중복 요청 방지를 담당한다. 새 크롤러는
  이 둘을 재사용해라(직접 파일 저장 로직 새로 짜지 말 것).
- **`artists.entity_kind`**(`person`/`institution`/... , 0007), **`artists.wikidata_qid`**(authority ID,
  0008), **`artists.bio` + `artists.bio_source`**(0013, 출처 URL을 남겨 Q&A가 근거 인용하게 함) —
  이 세 축이 "정본화(P2)" 작업의 핵심 구조다. 약력/메타를 채울 땐 **authority(QID) 매칭으로만** 채워라
  — 문자열 추측이나 LLM 생성 텍스트를 `bio`에 직접 넣지 말 것(생성 텍스트가 필요하면 별도 컬럼/플래그로
  분리해 인용 가능한 값과 섞이지 않게 한다 — 0006 `artist_bio_generated`가 그 선례).
  `[[project_rediagnosis_20260915]]`
- **`provenance_records`**가 이 프로젝트의 핵심 관계망(작품 하나를 축으로 collector/museum/gallery/
  auction_house를 시간순으로 잇는 소유 이력)이다 — `owner_type`으로 분기, `owner_*_id`는 전부
  nullable(매칭 실패를 정상 상태로 취급).

## 3. 쿼리 짤 때 — 오늘 실제로 5시간짜리 백그라운드 잡을 잡아먹을 뻔한 패턴

**SELECT 절에 "이 행에 연결된 개수"를 상관 서브쿼리(correlated subquery)로 넣지 마라.**

```sql
-- 하지 마라: artists 21,620행 각각에 대해 artworks JOIN museum_holdings를 매번 새로 스캔한다
select a.id, (select count(*) from artworks aw join museum_holdings mh
              on mh.artwork_id=aw.id where aw.artist_id=a.id) h
from artists a where ...
```
인덱스가 있어도(`idx_artworks_artist`, `idx_museum_holdings_artwork` 둘 다 이미 존재) 이 패턴은 행 수만큼
디스크 I/O를 반복시킨다 — 실측으로 500초 넘게 걸리고 계속 늘어났다(`pg_stat_activity`에서
`wait_event_type='IO', wait_event='DataFileRead'`로 확인 가능). 대신 **한 번만 집계하고 LEFT JOIN**해라:

```sql
select a.id, coalesce(h.cnt, 0) as h
from artists a
left join (select aw.artist_id, count(*) cnt from artworks aw
           join museum_holdings mh on mh.artwork_id=aw.id group by aw.artist_id) h
  on h.artist_id = a.id
where ...
```
같은 결과, **152초**(2026-09-21 실측, `pipeline/backfill_artist_bio_wikipedia.py`). "artist/artwork 하나당
연결 개수"를 세는 코드를 짤 때마다 이 패턴부터 의심해라 — `museum_holdings`, `auction_lots`,
`gallery_representations`처럼 N:1로 붙는 테이블이 꽤 있다.

**대량 INSERT/UPDATE는 500건 배치 + 배치마다 커밋**해라(`pipeline/store.py`의 `PgStore`가 이 패턴 —
`execute_values` 500건 + per-batch commit). 행 단위 INSERT는 네트워크 왕복이 누적돼 대량(10만+)에서
감당이 안 되고, 반대로 전체를 하나의 트랜잭션으로 묶으면 pgportable이 중간에 끊겼을 때 전부 롤백된다.

## 4. 백그라운드 잡 — "로그에 떴다"는 "됐다"가 아니다

- **런처 커맨드가 exit 0으로 끝나는 건 셸이 프로세스를 백그라운드로 떼어냈다는 뜻일 뿐, 잡 자체가 잘
  돌아간다는 보장이 아니다.** 실제로 살아있는지는 별도로 확인해라(`Get-CimInstance Win32_Process
  -Filter "Name='python3.exe'"`로 PID·커맨드라인 확인, 또는 결과물이 실제로 늘어나는지 — raw 파일 개수,
  DB row count).
- **stdout이 파일로 리다이렉트되면 파이썬은 버퍼링한다** — `print()`가 곧바로 로그 파일에 안 보일 수
  있다. 오래 걸리는 스크립트는 `python3 -u`(unbuffered)로 띄우거나, 로그가 비어있다고 바로 "멈췄다"고
  판단하지 마라. 대신 실제 산출물(raw 캐시 파일 개수 등)이 시간이 지나며 느는지로 판단해라.
- **"멈춘 것처럼 보이는" 걸 확인하려면 클라이언트 프로세스를 죽이기 전에 서버 쪽(`pg_stat_activity`)부터
  봐라**: `wait_event_type`이 `IO`/`DataFileRead`면 느린 쿼리가 실제로 진행 중인 것(위 3번 패턴을
  의심), `Lock`이면 다른 트랜잭션과 충돌 중인 것, `IPC`/`BufferIo`면 다른 백엔드와 버퍼 경합 중인 것 —
  각각 대응이 다르다.
- **`timeout N cmd` 같은 클라이언트 측 타임아웃 kill이 서버 쪽 쿼리 실행까지 즉시 멈추지는 않는다.**
  postgres는 소켓이 끊겼는지 디스크 I/O 대기 중엔 바로 확인하지 않을 수 있어서, 클라이언트를 여러 번
  죽이며 재시도하면 **같은 무거운 쿼리를 실행하는 postgres 백엔드가 여러 개 동시에 쌓일 수 있다**(실제로
  겪음 — 진단 쿼리 재시도 몇 번 만에 백엔드 10개가 동시에 같은 쿼리를 돌리고 있었음). 재시도 전에
  `select pg_terminate_backend(pid)`로 이전 백엔드부터 정리해라, 그냥 클라이언트만 다시 실행하지 말고.
- 오래 도는 잡은 진행 상황을 폴링으로 확인하지 말고 Monitor 같은 도구로 주기적 체크 루프를 걸어라
  (예: N초마다 raw 파일 개수/로그 tail을 출력하고, 완료 마커가 로그에 뜨면 종료).

## 5. 그 외 알려진 불안정 요소

- **pgportable(로컬 Postgres)이 가끔 죽는다** — 회사 DLP 에이전트(PISupervisor.exe)의 크래시루프와
  상관관계가 확인된 적 있다(`[[project_pgportable_instability]]`). 재기동이 필요하면
  `pipeline/_pg_server.log` 먼저 확인. **설계로 대응해라(재시도/추측 대신)**: 크롤러는 `already_fetched()`
  캐시로 언제든 재시작 가능하게, 백필류 스크립트는 idempotent(이미 값 있는 행은 건드리지 않음)하게 짜라
  — 실제로 이번 세션의 백필 스크립트도 이 원칙 덕에 중간에 죽여도 안전했다.
- **Windows 콘솔은 기본 cp949다.** 한글/이모지/em dash를 `print()`하면 `UnicodeEncodeError`가 난다 —
  새 스크립트 상단에 `sys.stdout.reconfigure(encoding="utf-8")`를 넣어라(기존 크롤러들이 이미 이렇게
  하고 있으니 그대로 따라 하면 됨).
- **작가/기관 이름 유사도 병합(dedup)은 union-find(전이적 연결)로 짜지 마라.** A~B 유사, B~C 유사라고
  A~C가 같은 엔티티라는 보장이 없다 — 체이닝으로 무관한 레코드가 묶인 사고가 있었다. 고정된 canonical
  하나에 대해서만 word-aligned 비교해라(`[[feedback_single_linkage_chaining_bug]]`).
- **경매 lot 매칭은 `house+lot_number+year` 세 개를 다 봐야 한다.** lot 번호는 경매사·연도가 바뀌면
  재사용되므로 lot 번호만으로 매칭하면 ~91%가 오탐이었다(`[[project_provenance_lot_number_reuse]]`).

## 6. 작업 원칙(이 시점 기준)

- **새 소스·새 크롤러 추가는 지금 금지다** — 2026-09-15 재진단 이후 "가비지 확정 → 정본화" 순서로
  진행 중(`docs/작업분담_20260915.md`). 새 사이트 크롤링을 제안하기 전에 이 문서와 CLAUDE.md의
  "2026-09-15 재진단" 절을 먼저 확인해라.
- **커밋은 사용자가 명시적으로 지시할 때만.** 이 프로젝트는 미커밋 변경이 세션 사이에 계속 쌓이는 게
  정상적인 작업 방식이다 — 알아서 커밋하지 말 것.
- **불명확하게 검증된 가비지(garbage) 삭제는 예외적으로 사전승인 없이 처리 가능**하다 — 단, 전수 확인
  + 화이트리스트 + idempotent 세 조건을 다 충족할 때만(`[[feedback_garbage_deletion_no_preapproval]]`).
  그 외 삭제성 작업은 먼저 확인받아라.
- 이 프로젝트는 메인/워커1/워커2 세 세션이 병렬로 도는 걸 전제로 한다(`docs/자율운영기준.md`) — 다른
  세션이 이미 처리했을 수 있는 작업(재적재, 리포트 등)은 시작 전에 실제 DB/파일 상태부터 확인해라,
  낡은 문서 내용만 믿지 말고.

## 참고 문서 지도

| 필요할 때 | 문서 |
|---|---|
| 프로젝트 전체 배경·아키텍처 | `docs/착수리포트.md` |
| 현재 로드맵 진행 상황 | 프로젝트 루트 `CLAUDE.md` |
| DB 테이블 관계(단, stale할 수 있음 — 실제 컬럼은 migrations가 진실) | `docs/db-schema.md`, `db/migrations/*.sql` |
| 크롤러별 상태·robots.txt/ToS 판정 | `docs/크롤러현황.md` |
| 지금 뭘 하면 안 되는지(신규 소스 금지 등) | `docs/작업분담_20260915.md` |
| Q&A 아키텍처(Text-to-SQL vs 임베딩) | `docs/QA아키텍처.md` |
| 정합성 작업(중복 병합 등) 이력 | `docs/정합성작업.md` |
| 자율 운영 기준(무인 작업 시 원칙) | `docs/자율운영기준.md` |
