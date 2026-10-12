-- 0009: 사건(시간축) 스키마 — 전시·작가 이벤트 (2026-09-15 docs/최신성보강안_20260915.md R1)
-- 현재 DB는 작품·소장·로트 같은 "정적 사실"뿐이라 최근 활동/흐름을 담을 자리가 없었다.
-- 채우는 쪽: R2(갤러리 전시 페이지), R4(Wikidata 전시·수상), R5(한국 공공 API·기관 전시 페이지).
create table if not exists exhibitions (
  id uuid primary key default gen_random_uuid(),
  title text not null,
  venue_kind text not null check (venue_kind in ('museum','gallery','fair','other')),
  museum_id uuid references museums(id) on delete set null,
  gallery_id uuid references galleries(id) on delete set null,
  venue_name text,           -- 기관 매칭 실패 시 원문
  city text,
  country text,
  start_date date,
  end_date date,
  url text,
  source_id uuid references sources(id),
  created_at timestamptz not null default now()
);
create unique index if not exists idx_exhibitions_dedup on exhibitions (coalesce(url,''), title, coalesce(start_date, date '0001-01-01'));
create index if not exists idx_exhibitions_dates on exhibitions (start_date, end_date);

create table if not exists exhibition_artists (
  exhibition_id uuid not null references exhibitions(id) on delete cascade,
  artist_id uuid not null references artists(id) on delete cascade,
  role text,                 -- solo | group | curator | null
  primary key (exhibition_id, artist_id)
);
create index if not exists idx_exhibition_artists_artist on exhibition_artists (artist_id);

create table if not exists artist_events (
  id uuid primary key default gen_random_uuid(),
  artist_id uuid not null references artists(id) on delete cascade,
  event_kind text not null check (event_kind in ('award','residency','acquisition','representation_start','representation_end','death','other')),
  event_date date,
  detail text,
  url text,
  source_id uuid references sources(id),
  created_at timestamptz not null default now()
);
create unique index if not exists idx_artist_events_dedup on artist_events (artist_id, event_kind, coalesce(event_date, date '0001-01-01'), coalesce(detail,''));
create index if not exists idx_artist_events_date on artist_events (event_date);

-- 한국 시장 연간 집계(예술경영지원센터 실태조사 등 공개 통계) — 로트 단위가 아닌 연도별 지표
create table if not exists market_stats_kr (
  id uuid primary key default gen_random_uuid(),
  year int not null,
  metric text not null,      -- 예: auction_total_krw, auction_sell_through_rate, gallery_sales_krw
  value numeric,
  unit text,
  source_url text,
  note text,
  created_at timestamptz not null default now()
);
create unique index if not exists idx_market_stats_kr_dedup on market_stats_kr (year, metric, coalesce(source_url,''));
