-- 2026-09-15 (작업분담 §M1): LLM(Gemini)이 생성한 작가 약력을 원본 약력과 분리 보관.
-- enrich_artist_bios.py(09-15)가 핵심 작가 2,499명의 artists.bio에 생성문을 출처 표시 없이
-- 덮어썼음 — "근거를 인용해 답한다"는 프로젝트 원칙과 충돌하므로 별도 테이블로 격리한다.
-- artists.bio 에는 원본(수집 소스가 제공한 텍스트)만 남긴다.

create table if not exists artist_bio_generated (
  artist_id          uuid primary key references artists(id) on delete cascade,
  bio                text not null,        -- 한국어 개요(2~3문장)
  movement           text,                 -- "주요 사조" 줄
  nationality_period text,                 -- "국적 및 활동시기" 줄
  model              text not null,        -- 예: gemini-flash-lite-latest (정확한 모델명은 로그 부재로 계열명만 기록)
  generated_at       date not null,        -- 생성일(추정 포함)
  source_script      text not null,        -- 생성 스크립트 경로
  verified           boolean not null default false,  -- 사람이 사실 검증했는지
  note               text,
  created_at         timestamptz not null default now()
);
