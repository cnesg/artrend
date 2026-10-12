-- 0011: 기관(museums, auction_houses) Wikidata QID + 소재지 백필 준비 (2026-09-15 계획 P2-13 후반, R4 후속)
-- museums.country/city/website, auction_houses.country는 전부 NULL이었다. Wikidata 라벨 정확 일치(유일 매칭)로
-- QID를 붙이고 P17/P131/P856을 채운다. exhibitions(0009)의 Wikidata 전시를 museums에 QID로 매칭하는 데도 쓴다.
-- 백필: pipeline/backfill_institutions_wikidata.py
alter table museums add column if not exists wikidata_qid text;
alter table auction_houses add column if not exists wikidata_qid text;
alter table auction_houses add column if not exists website text;
create index if not exists idx_museums_wikidata_qid on museums(wikidata_qid) where wikidata_qid is not null;
create index if not exists idx_auction_houses_wikidata_qid on auction_houses(wikidata_qid) where wikidata_qid is not null;
