-- 0002: 출생·사망연도 출처 (2026-10-13 출생연도 보강)
-- birth_year_source: 'list'(참가 명단 원문) | 'wikidata:Q..'(QID 직접) | 'wikidata_name:Q..'(이름 정확일치 + 작가 직업 + 후보 1명)
--                    | 'v1:<artrend artists.id>'(v1 소프트 링크 작가의 출생연도)
alter table artists add column if not exists birth_year_source text;
alter table artists add column if not exists death_year int;
update artists set birth_year_source = 'list' where birth_year is not null and birth_year_source is null;
