# pipeline/ 스크립트 색인 (2026-09-17, P3-16 논리적 분리)

물리적으로 `loaders/`·`maintenance/`로 나누지 않고 이 색인으로 구분한다. 이유: `run.py`가 로더 28개를 모듈 이름으로 직접 import하고, 유지보수 스크립트 70여 개가 `db`·`artist_merge_util`·`common`(crawlers/)을 같은 폴더 기준으로 import하며, `docs/`·`CLAUDE.md`의 `pipeline/<이름>.py` 경로 참조가 수십 곳이라 이동 비용 대비 이득이 작다. 물리 이동은 워커 유휴 시점에 커밋 단위로만 한다.

새 스크립트는 아래 접두어 관례를 따른다: `backfill_`(결손 채움) · `link_`(외부 ID 연결) · `merge_`(행 병합) · `fix_`/`clean_`(오염 정정) · `dedup_`(중복 제거) · `audit_`(읽기 전용 감사). DB를 바꾸는 것은 기본 리포트, `--apply`로만 반영, idempotent.

## 1. 실행기·공용 유틸

| 파일 | 역할 |
|---|---|
| `run.py` | raw → DB 적재 실행기. `--site all|<site>`, `--dry-run`, `--limit`(nga) |
| `store.py` | `PgStore`(execute_values 500건 배치·배치 커밋) / `DryRunStore`. 로더는 이 인터페이스만 본다 |
| `db.py` | **DB 접속 단일 진입점** `get_connection()`/`get_dsn()` (환경변수 → `.env`, UTF8) |
| `artist_merge_util.py` | artists 병합 공용: `relink_and_delete`, `fill_missing_meta`, `norm_exact/loose`, `get_conn`(db 위임) |
| `raw_iter.py` | `crawlers/raw/<site>/` 의 `<id>.json`+`<id>.meta.json` 쌍 순회 |
| `freetext_metadata.py` | 자유텍스트(작가 표기 문자열)에서 국적·생몰 추출 규칙(백필 스크립트가 import) |
| `apply_migration.py` | `db/migrations/<file>.sql` 적용 |

## 2. 로더 — `run.py` 등록 (사이트당 하나, `def load(store)`)

소장품: `met` `aic` `cleveland` `nga` `smithsonian` `mmca` `smk` `moma` `tate` `louvre` `rijksmuseum` `wikidata_museums` `japan_museums` `getty` `barnes` `walters` `mia` `vam` `europeana` `sema` `busan_art_museum` `gmoma` `leeum` `pinault`
경매: `auctions`(Wikidata P793) `getty_provenance_sales`(1675~1944 판매 카탈로그) `bonhams`
관계: `galleries`(갤러리 작가 로스터 → gallery_representations)

재적재는 `sources.raw_path` 유니크로 막힌다. 새 raw 파일만 들어간다.

## 3. 로더 — `run.py` 미등록, 독립 실행 (사건·통계·후처리)

| 파일 | 대상 테이블 | 비고 |
|---|---|---|
| `wikidata_artist_events.py` | artist_events / exhibitions / exhibition_artists | R4, `--apply` |
| `institution_exhibitions_load.py` | exhibitions / exhibition_artists | MMCA·부산·경기도 전시 raw, `--apply` |
| `gallery_exhibitions_from_raw.py` | exhibitions / exhibition_artists | 갤러리 작가 페이지 HTML 파싱, `--apply` |
| `kams_stats_load.py` | market_stats_kr | K-ARTMARKET 연간 통계, `--apply` |
| `provenance_extract.py` | collectors / provenance_records | artworks.description 크레딧라인 역파싱. **신규 museum/gallery/auction_house 생성 금지 규칙 적용됨** |

## 4. 정본화·백필 (authority ID 기반, 재실행 가능)

| 파일 | 요약 |
|---|---|
| `backfill_artist_authority.py` | Getty raw ULAN + Wikidata QID → artists.ulan_id/wikidata_qid |
| `link_korean_artists_wikidata.py` | 한글 이름 작가 ↔ Wikidata(유일 후보·미술가 직업·한국 국적). 다중 토큰 한글 이름 제외 |
| `merge_mixed_korean_names.py` | 'Park Seo-Bo 박서보' 혼합 표기 행을 한글 행과 QID로 묶어 병합 |
| `merge_by_authority.py` | **같은 ULAN/QID만 병합**(문자열 유사도 없음). 정본 = 생년 → 작품 수 → bio 길이 → 긴 이름 |
| `backfill_artist_meta_wikidata.py` | authority 있는 작가의 생몰·국적·영문명 결손을 Wikidata로 |
| `backfill_artist_metadata.py` / `backfill_bio_metadata.py` / `backfill_freetext_metadata.py` | raw·bio·자유텍스트에서 규칙 기반 메타 백필(LLM 아님) |
| `backfill_institutions_wikidata.py` / `backfill_institutions_manual_qid.py` | museums·auction_houses QID·국가·도시·웹사이트. 수동 QID는 Wikidata 라벨/설명 검증 후 |
| `merge_museums_by_qid.py` | 같은 QID museums 병합(정본 = 소장 최다) |
| `link_exhibitions_museum_qid.py` | Wikidata 전시 P276 → museums.wikidata_qid 연결 |
| `classify_artist_entity_kind.py` | artists.entity_kind(person/anonymous/culture/organization/attribution) |
| `mark_getty_attribution.py` | Getty 귀속 한정어 → artworks.attribution_qualifier |
| `isolate_generated_bios.py` | LLM 생성 약력을 artist_bio_generated로 격리, 원본 bio 복원 |
| `normalize_nationality_danish.py` | SMK 덴마크어 국적 → 영문 demonym |
| `backfill_source_license.py` | sources.license_note 사이트별 백필 |

## 5. 정제·정정 (오염 유형별, `--apply`)

`fix_bonhams_artist_titles.py`(메인 전용) · `clean_bonhams_title_dimensions.py` · `fix_auction_lot_anomalies.py` · `fix_auctions_wikidata_dup_qid.py`((QID, statement GUID) 기준) · `nullify_historical_price_usd.py` · `delete_mia_duplicate_artworks.py` · `demote_ghost_entities.py` · `fix_foundation_museum_misclass.py` · `fix_institute_academy_museum_misclass.py` · `merge_met_multiartist_dup_artists.py` · `fix_moma_multiartist_dup_artists.py` · `fix_barnes_multiartist_dup_artists.py` · `fix_mia_after_artist_names.py` · `merge_role_prefix_artists.py` · `dedup_holdings.py` · `dedup_gallery_representations.py` · `merge_dup_museums.py` / `merge_dup_galleries.py` / `merge_dup_collectors.py`(순수 표기 차이만) · `merge_auction_house_variants.py`(워커) · 전시: `fix_institution_title_prefix.py` `fix_exhibition_titles_wikidata.py` `match_exhibition_venue_names.py` `clean_gallery_exhibitions_press_noise.py`

## 6. 감사·리포트 (읽기 전용)

`audit_health.py`(**상시 건강지표**, `--json`) · `audit_collectors.py`(`--apply` 있음, 정정 겸용) · `audit_gallery_artist_matches.py` · `audit_attribution_variants.py` · `audit_auction_artwork_matches.py` · `audit_provenance_auction_match.py` · `find_exhibition_cross_duplicates.py` · `detailed_noise_check.py` · `analyze_curated_stats.py`

## 7. Q&A·vault

| 파일 | 역할 |
|---|---|
| `build_curated_vault.py` | DB → `vault_curated/` 5,100문서(V4 스코어: reps·lots·holdings·전시·축 수·authority) |
| `embed_vault.py` | vault_curated → `vault_embeddings`(로컬 multilingual-e5-small, 샤드 옵션). **query_vault와 동시 실행 금지** |
| `query_vault.py` | 고유명사 정확매칭(artists/museums/galleries/auction_houses) 우선 → 시맨틱 폴백. `--answer`로 Gemini 답변 |
| `artgraph_chat.py` | Text-to-SQL(Gemini, read-only 세션) 주 경로. 회귀 세트 `docs/logs/chat_회귀_*.json` |
| `enrich_artwork_images.py` | artworks.image_url 보강(raw 기반) |

## 8. 이력 스크립트 — 재실행하지 않음 (선례·감사 추적용으로만 보존)

- **문자열 유사도 병합기(2026-09-04~08)**: `dedup_artists.py` `merge_case_dup_artists.py` `merge_cross_lang_artists.py` `merge_gallery_punct_dup_artists.py` `merge_unicode_form_dup_artists.py` `merge_accent_variant_dup_artists.py` `merge_name_order_dup_artists.py` `merge_spelling_variant_artists.py` `merge_review_low_richness.py` `merge_research_verdicts.py` `merge_large_cluster_verdicts.py` `resplit_oversized_clusters.py` `rollback_bad_merges.py` `filter_review_by_metadata.py` `analyze_large_clusters_metadata.py` — 2026-09-15 이후 병합 규칙은 authority ID 동일뿐. 단일연결 체이닝 오탐 이력 있음.
- **1세대 vault/ 전용(현재 vault/ 없음)**: `export_vault.py` `build_browse_vault.py` `enrich_vault_frontmatter.py` `cleanup_vault_orphans.py` `setup_obsidian_settings.py` `audit_vault_artwork_gap.py`
- **되돌린 09-15 보강**: `enrich_artist_bios.py`(LLM 약력 생성 — 금지, 산출물은 artist_bio_generated로 격리됨) `enrich_auction_db.py`(현대 ISO 통화만 남김, 역사 통화 환산 제거)
- 초기 정리: `clean_noise.py` `create_fk_indexes.py`
- `_scratch/`: 일회성 inspect/test/check. 재실행 보장 없음.
