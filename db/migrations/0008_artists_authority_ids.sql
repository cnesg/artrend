-- 0008: 작가 authority ID(Getty ULAN, Wikidata QID) 컬럼 (2026-09-15 재진단 P2-12 / 작업분담 M6)
-- 문자열 휴리스틱 병합 대신 같은 authority ID면 같은 작가로 보고 병합하기 위한 정본 키.
-- 백필: pipeline/backfill_artist_authority.py (Met CSV "Artist ULAN URL"/"Artist Wikidata URL",
--       Getty sales_contents artist_ulan_N, auctions_wikidata creator QID, wikidata_creators/*).
-- 병합: pipeline/merge_by_authority.py. 병합 전까지는 같은 ID가 여러 행에 있을 수 있으므로 unique 아님.
alter table artists add column if not exists ulan_id text;
alter table artists add column if not exists wikidata_qid text;
alter table artists add column if not exists authority_source text;  -- 'met' | 'getty_sales' | 'auctions_wikidata' | 'wikidata_creators' (첫 부여 출처)
create index if not exists idx_artists_ulan_id on artists(ulan_id) where ulan_id is not null;
create index if not exists idx_artists_wikidata_qid on artists(wikidata_qid) where wikidata_qid is not null;
