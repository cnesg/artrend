-- 아트그래프 v2 — 비엔날레·아트페어 참가 신호 (2026-10-12)
-- DB: artgraph_v2 (v1 artrend DB와 분리). 적용: python v2/common.py --init-db
create extension if not exists pgcrypto;

create table if not exists sources (
  id uuid primary key default gen_random_uuid(),
  url text,
  fetched_at timestamptz not null,
  raw_path text not null unique,          -- 데이터 루트 기준 상대경로
  source_tier text not null check (source_tier in ('official','official_pdf','archive','wikipedia','press')),
  license_note text,
  created_at timestamptz not null default now()
);

create table if not exists series (
  id text primary key,                    -- gwangju_biennale, frieze_london, kiaf
  kind text not null check (kind in ('biennale','fair')),
  name text not null,
  name_ko text,
  city text,
  country text                            -- 한국어 국가명 (v1 exhibitions.country 관례)
);

create table if not exists editions (
  id text primary key,                    -- gwangju_2024, frieze_london_2023
  series_id text not null references series(id),
  year int not null,
  label text not null,                    -- 15th Gwangju Biennale
  title text,                             -- 전시 주제
  start_date date,
  end_date date,
  city text,                              -- 회차별로 다를 수 있음(마니페스타·도큐멘타14 아테네)
  announced_count int,                    -- 공표 참가 인원(비엔날레) / 갤러리 수(페어)
  coverage text check (coverage in ('complete','partial','none')),
  coverage_note text,
  created_at timestamptz not null default now()
);

create table if not exists artists (
  id uuid primary key default gen_random_uuid(),
  name text not null,                     -- 대표 표기(처음 들어온 명단 표기)
  name_ko text,
  name_en text,
  kind text not null default 'person' check (kind in ('person','collective')),
  birth_year int,
  wikidata_qid text,
  v1_artist_id uuid,                      -- artrend v1 artists.id 소프트 참조(FK 없음)
  created_at timestamptz not null default now()
);

-- 작가 동일성: 정규화 표기 1개 = 작가 1명. 이름·한글명·영문명 각각 별칭으로 등록.
create table if not exists artist_aliases (
  alias_key text primary key,             -- NFC + 공백정리 + casefold
  artist_id uuid not null references artists(id) on delete cascade
);
create index if not exists idx_artist_aliases_artist on artist_aliases (artist_id);

create table if not exists galleries (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  name_ko text,
  name_en text,
  city text,
  v1_gallery_id uuid,
  created_at timestamptz not null default now()
);

create table if not exists gallery_aliases (
  alias_key text primary key,
  gallery_id uuid not null references galleries(id) on delete cascade
);
create index if not exists idx_gallery_aliases_gallery on gallery_aliases (gallery_id);

create table if not exists fair_booths (
  id uuid primary key default gen_random_uuid(),
  edition_id text not null references editions(id) on delete cascade,
  gallery_id uuid not null references galleries(id),
  section text not null default 'main',
  booth text,
  gallery_name_as_listed text not null,
  source_id uuid references sources(id),
  unique (edition_id, gallery_id, section)
);

create table if not exists participations (
  id uuid primary key default gen_random_uuid(),
  edition_id text not null references editions(id) on delete cascade,
  artist_id uuid not null references artists(id),
  section text not null default 'main',
  booth_id uuid references fair_booths(id) on delete cascade,  -- 페어: 어느 갤러리 부스로 나왔나
  name_as_listed text not null,           -- 원 명단 표기 그대로(근거)
  country_as_listed text,
  source_id uuid references sources(id),
  created_at timestamptz not null default now()
);
create unique index if not exists idx_participations_dedup
  on participations (edition_id, artist_id, section, coalesce(booth_id, '00000000-0000-0000-0000-000000000000'::uuid));
create index if not exists idx_participations_artist on participations (artist_id);
