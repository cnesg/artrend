# 아트그래프 v2 — 현대미술 활동 신호 DB

v1(이 저장소의 `crawlers/`·`pipeline/`·`db/`, Postgres `artrend` DB)은 소장품·경매·프로버넌스 중심의
"이미 성공한 작가 아카이브"다. v2는 **현역 작가가 언제 어디에 나왔는지**를 시점과 함께 쌓는 별도
데이터층이다 — 신진작가 발굴·성장성 판단(2026-10-12 C레벨 요청)의 재료.

v1과는 코드·DB·원본 저장소를 공유하지 않는다. v1 데이터는 읽기 전용 참조만 하고(작가 매칭 시
`artists.v1_artist_id`에 소프트 링크), v1 테이블에 쓰지 않는다.

## 1차 범위 (2026-10-12 결정)

| 축 | 대상 | 기간 | 단위 |
|---|---|---|---|
| 비엔날레 | 한국 3(광주·부산·서울미디어시티) + 해외 11(베니스·도큐멘타·휘트니·상파울루·시드니·이스탄불·베를린·리옹·상하이·샤르자·마니페스타) | 2016–2026 | 본전시 참가작가 (베니스 국가관·병행전 제외) |
| 아트페어 | Kiaf, Frieze(런던·뉴욕·LA·서울, 마스터스는 별도 시리즈) | 2016–2026 | 갤러리 부스 + 부스별 출품작가, 특별 섹션은 section으로 구분 |

## 구조

```
v2/
  db/*.sql             스키마 (DB: artgraph_v2, 같은 로컬 Postgres 5433) — python v2/common.py --init-db
  common.py            경로·DB 접속·원본 저장(save_raw)·HTTP 공통
  registry.py          시리즈 정의 + editions_*.py(그룹별 회차 메타·원본 URL·파서 지정)를 합침
  parsers/             비엔날레 회차별 파서(bi_*.py) + 페어 표기 정리(fair_kiaf.py)
  research/{kiaf,frieze}/  페어 조립 코드 사본 — 여러 원본(목록·카탈로그 PDF·웨이백)을 엮어 회차 JSON을
                       만든다. 실행은 캐시와 같은 폴더인 ~/artgraph_v2_data/research/<fair>/ 에서
  collect.py           registry의 URL을 받아 원본 그대로 저장 (재실행 시 이미 받은 건 건너뜀)
  load.py              원본 -> 파서 -> DB (리포트 기본, --apply로 반영, idempotent)
  link_v1.py           v1(artrend) 작가와 소프트 링크 (v1은 읽기 전용)
  enrich_birth.py      출생·사망연도 보강 (명단 > Wikidata QID > Wikidata 이름검색 > v1, 출처 기록)
  export.py            v2/exports/에 CSV·요약 MD 생성 (git 미추적 — 프리즈 내부 연구용 데이터 포함)
```

원본은 git 밖 `~/artgraph_v2_data/raw/`(환경변수 `ARTGRAPH_V2_DATA`로 변경)에 `<id>.<ext>` +
`<id>.meta.json`(URL·수집시각·출처등급·라이선스) 쌍으로 저장한다. 페어 원본은
`~/artgraph_v2_data/research/<fair>/`. 모든 참가 기록은 `sources` 행을 가리키고, 원 명단 표기
(`name_as_listed`)를 그대로 남긴다. 세션 임시 폴더(Temp)는 중간에 지워질 수 있으니 원본·조사
산출물을 거기에만 두지 말 것.

## 재현 순서

```
python v2/common.py --init-db
python v2/collect.py                 # 비엔날레 원본 (페어는 research/<fair>/build*.py)
python v2/load.py --apply
python v2/link_v1.py --apply
python v2/enrich_birth.py --apply
python v2/link_v1.py --apply         # 출생연도가 바뀌면 동명이인 판정이 달라져 한 번 더
python v2/export.py
```

## 프리즈 데이터 — 내부 연구용

frieze.com 이용약관이 서면 허가 없는 수집을 금지한다. 2026-10-13 사용자 결정으로 웨이백 사본·공식
보도자료 PDF에서 갤러리 목록과 2016–2020 큐레이션 섹션·프로그램 작가만 내부 연구용으로 적재했다.
외부 공개·상업 이용 시 프리즈 분(series `frieze_*`)을 빼거나 허가를 먼저 받을 것.

## 원칙

- **시점 고정**: 참가 기록은 회차(시작일)에 묶인다 — 나중에 "그 시점에 알 수 있었던 신호"만으로
  백테스트할 수 있게.
- **출처 등급**: official > official_pdf > archive(웨이백) > wikipedia > press. 회차별 확보율
  (`editions.coverage`)을 숨기지 않는다.
- **작가 동일성은 정확일치만**: 표기(이름·한글명·영문명)를 casefold한 별칭 키가 같을 때만 같은
  작가. 유사도 병합은 하지 않는다(v1에서 체이닝 사고 경험).
