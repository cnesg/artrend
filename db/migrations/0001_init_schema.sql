-- 아트그래프 초기 스키마
-- 작가 · 작품 · 경매 · 미술관 · 갤러리 · 컬렉터 + 관계 + 출처(인용 근거)

create extension if not exists pgcrypto;

-- ============================================================
-- 출처 (모든 레코드가 인용할 원본 근거)
-- ============================================================
create table sources (
  id            uuid primary key default gen_random_uuid(),
  url           text,
  site_name     text not null,
  fetched_at    timestamptz not null default now(),
  raw_path      text,                 -- crawlers/raw/ 하위 원본 파일 상대경로
  license_note  text,                 -- 수집 근거(공공데이터/무료열람 등)
  created_at    timestamptz not null default now()
);

-- ============================================================
-- 작가
-- ============================================================
create table artists (
  id          uuid primary key default gen_random_uuid(),
  name        text not null,
  name_en     text,
  birth_year  int,
  death_year  int,
  nationality text,
  bio         text,
  source_id   uuid references sources(id),
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

-- ============================================================
-- 작품
-- ============================================================
create table artworks (
  id            uuid primary key default gen_random_uuid(),
  artist_id     uuid references artists(id),   -- 작가 미상 가능 -> null 허용
  title         text not null,
  title_en      text,
  year_created  text,                           -- "1997" / "c.1900" / "20세기 초" 등 비정형 허용
  medium        text,                           -- 재료/기법
  dimensions    text,
  description   text,
  source_id     uuid references sources(id),
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);
create index idx_artworks_artist on artworks(artist_id);

-- ============================================================
-- 경매
-- ============================================================
create table auction_houses (
  id         uuid primary key default gen_random_uuid(),
  name       text not null,
  country    text,
  created_at timestamptz not null default now()
);

create table auctions (
  id                uuid primary key default gen_random_uuid(),
  auction_house_id  uuid not null references auction_houses(id),
  name              text,
  auction_date      date,
  location          text,
  source_id         uuid references sources(id),
  created_at        timestamptz not null default now()
);
create index idx_auctions_house on auctions(auction_house_id);

create table auction_lots (
  id            uuid primary key default gen_random_uuid(),
  auction_id    uuid not null references auctions(id),
  artwork_id    uuid references artworks(id),   -- 매칭 안 된 경우 null 허용
  lot_number    text,
  estimate_low  numeric,
  estimate_high numeric,
  currency      text,
  hammer_price  numeric,
  sold          boolean,
  source_id     uuid references sources(id),
  created_at    timestamptz not null default now()
);
create index idx_auction_lots_auction on auction_lots(auction_id);
create index idx_auction_lots_artwork on auction_lots(artwork_id);

-- ============================================================
-- 미술관 · 소장품
-- ============================================================
create table museums (
  id         uuid primary key default gen_random_uuid(),
  name       text not null,
  name_en    text,
  country    text,
  city       text,
  type       text,          -- 공립/사립/대학 등
  website    text,
  source_id  uuid references sources(id),
  created_at timestamptz not null default now()
);

create table museum_holdings (
  id                 uuid primary key default gen_random_uuid(),
  museum_id          uuid not null references museums(id),
  artwork_id         uuid not null references artworks(id),
  accession_number   text,
  acquisition_date   date,
  acquisition_method text,   -- 구입/기증/유증 등
  donor_name         text,
  source_id          uuid references sources(id),
  created_at         timestamptz not null default now()
);
create index idx_museum_holdings_museum on museum_holdings(museum_id);
create index idx_museum_holdings_artwork on museum_holdings(artwork_id);

-- ============================================================
-- 갤러리
-- ============================================================
create table galleries (
  id         uuid primary key default gen_random_uuid(),
  name       text not null,
  city       text,
  country    text,
  website    text,
  source_id  uuid references sources(id),
  created_at timestamptz not null default now()
);

create table gallery_representations (
  id          uuid primary key default gen_random_uuid(),
  gallery_id  uuid not null references galleries(id),
  artist_id   uuid not null references artists(id),
  start_date  date,
  end_date    date,          -- null = 현재 대표 중
  source_id   uuid references sources(id),
  created_at  timestamptz not null default now()
);
create index idx_gallery_rep_gallery on gallery_representations(gallery_id);
create index idx_gallery_rep_artist on gallery_representations(artist_id);

-- ============================================================
-- 컬렉터
-- ============================================================
create table collectors (
  id             uuid primary key default gen_random_uuid(),
  name           text not null,
  is_institution boolean not null default false,
  bio            text,
  source_id      uuid references sources(id),
  created_at     timestamptz not null default now()
);

-- ============================================================
-- 프로버넌스 (작품 소유 이력 체인 - 작가/경매/미술관/갤러리/컬렉터를 잇는 관계망 핵심)
-- ============================================================
create table provenance_records (
  id                  uuid primary key default gen_random_uuid(),
  artwork_id          uuid not null references artworks(id),
  owner_type          text not null check (owner_type in ('collector', 'museum', 'gallery', 'auction_house', 'unknown')),
  owner_collector_id  uuid references collectors(id),
  owner_museum_id     uuid references museums(id),
  owner_gallery_id    uuid references galleries(id),
  owner_auction_house_id uuid references auction_houses(id),
  acquired_date       date,
  acquired_method     text,   -- 구입/상속/기증/경매낙찰 등
  disposed_date       date,
  note                text,
  source_id           uuid references sources(id),
  created_at          timestamptz not null default now(),
  constraint owner_ref_matches_type check (
    (owner_type = 'collector'     and owner_collector_id     is not null) or
    (owner_type = 'museum'        and owner_museum_id        is not null) or
    (owner_type = 'gallery'       and owner_gallery_id       is not null) or
    (owner_type = 'auction_house' and owner_auction_house_id is not null) or
    (owner_type = 'unknown')
  )
);
create index idx_provenance_artwork on provenance_records(artwork_id);
