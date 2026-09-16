-- 0010: 작품 단위 귀속 한정어 (2026-09-15 작업분담 M6-b)
-- Getty Provenance Index sales_contents의 attrib_mod_auth_N("copy after", "manner of; style of", "attributed to",
-- "school of", "circle of", "workshop of", "follower of", "formerly attributed to", "possibly by", "or", "and" …)을
-- 작품 행에 보존한다. Getty 관행대로 artist_id는 본체 작가(ULAN)를 가리키되, 이 컬럼이 비어 있지 않으면
-- "그 작가의 진작"이 아니라는 뜻이다. Q&A·큐레이션은 attribution_qualifier is null 조건으로 진작만 셀 것.
alter table artworks add column if not exists attribution_qualifier text;
create index if not exists idx_artworks_attribution_qualifier on artworks(artist_id) where attribution_qualifier is not null;
