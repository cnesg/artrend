-- 0003_live_schema_sync_20260915.sql
-- 2026-09-15 작업분담 §W3: 라이브 스키마 역기입.
--
-- 배경: 라이브 DB(로컬 pgportable)에 마이그레이션 파일로 기록되지 않은 채
-- ad-hoc 스크립트(enrich_auction_db.py, dedup_holdings.py, 여러 fix_*.py)로
-- 컬럼·인덱스가 추가돼 있었다. information_schema.columns / pg_indexes
-- 실측(2026-09-15) 기준으로 0001/0002에 없던 것 전부를 이 파일에 기록한다.
--
-- 범위 제외: artist_bio_generated 테이블, artists.entity_kind/attribution_of/
-- attribution_qualifier/entity_kind_note 컬럼과 그 인덱스 2개(idx_artists_attribution_of,
-- idx_artists_entity_kind)는 메인(artrend-ca)이 이미 0006/0007로 기록함 — 여기서 다루지 않음.
--
-- artist_market_metrics: 오늘 enrich_auction_db.py가 만들었던 테이블이나,
-- 역사 통화 임의 환율 기반 가짜 지표라 §W2에서 DROP됨(0004_drop_artist_market_metrics.sql).
-- 그래서 "생성됐다가 0004에서 삭제"만 기록하고 여기서 재생성하지 않는다.
--
-- 전부 IF NOT EXISTS로 작성해 재실행해도 안전(idempotent).

-- ============================================================
-- artworks: 이미지 URL 컬럼 + 인덱스
-- ============================================================
alter table artworks add column if not exists image_url text;

create index if not exists idx_artworks_source_id on artworks(source_id);
create index if not exists idx_artworks_image_url on artworks(image_url) where image_url is not null;

-- ============================================================
-- auction_lots: USD 환산 컬럼 + 인덱스
-- (환산 정책은 §W2 — nullify_historical_price_usd.py 참고)
-- ============================================================
alter table auction_lots
  add column if not exists price_usd numeric,
  add column if not exists estimate_low_usd numeric,
  add column if not exists estimate_high_usd numeric;

create index if not exists idx_auction_lots_price_usd
  on auction_lots(price_usd desc nulls last);
create index if not exists idx_auction_lots_artwork_price
  on auction_lots(artwork_id, price_usd desc nulls last);

-- ============================================================
-- 유니크 인덱스 (dedup_holdings.py 등에서 ad-hoc 생성됐던 것들)
-- ============================================================
create unique index if not exists idx_artists_name_unique on artists(name);
create unique index if not exists idx_museums_name_unique on museums(name);
create unique index if not exists idx_galleries_name_unique on galleries(name);
create unique index if not exists idx_sources_raw_path_unique on sources(raw_path);
create unique index if not exists idx_museum_holdings_museum_accession_unique
  on museum_holdings(museum_id, accession_number)
  where accession_number is not null;

-- ============================================================
-- 일반 조회 인덱스
-- ============================================================
create index if not exists idx_sources_raw_path on sources(raw_path);
create index if not exists idx_sources_site_name on sources(site_name);

create index if not exists idx_provenance_collector
  on provenance_records(owner_collector_id) where owner_collector_id is not null;
create index if not exists idx_provenance_museum
  on provenance_records(owner_museum_id) where owner_museum_id is not null;
create index if not exists idx_provenance_gallery
  on provenance_records(owner_gallery_id) where owner_gallery_id is not null;
create index if not exists idx_provenance_auction_house
  on provenance_records(owner_auction_house_id) where owner_auction_house_id is not null;

-- artist_market_metrics: enrich_auction_db.py가 생성했던 테이블 — 역사 통화
-- 임의 환율 기반 가짜 지표라 판단돼 같은 날 DROP됨. 0004_drop_artist_market_metrics.sql 참고.
-- (여기서는 재생성하지 않음 — 라이브에 이미 없는 상태와 일치)
