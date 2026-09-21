-- 0013: artists.bio_source — 약력 출처 URL/근거 (2026-09-17 깊이 보강)
-- 원본 소스 약력(로더가 넣은 것)은 bio_source NULL로 남고, 외부 인용 약력(위키백과/Wikidata
-- 설명)은 이 컬럼에 출처 URL을 남겨 artgraph_chat이 근거를 인용할 수 있게 한다.
-- AI 생성 약력은 여전히 artist_bio_generated로 격리(이 컬럼과 무관).
ALTER TABLE artists ADD COLUMN IF NOT EXISTS bio_source text;
