-- 0005_rename_vault_embeddings.sql
-- 2026-09-15 작업분담 §W4: dead 임베딩 정리.
--
-- vault_embeddings 1,242,868건(2026-09-15, W1의 mia 고아 37,624건 삭제 이후 기준)은
-- 전부 이미 삭제된 1세대 `vault/` 폴더를 가리키는 doc_path라 죽은 참조다.
-- 삭제하지 않고 legacy로 rename만 해서 보존한다 — 최종 처분(완전 삭제 vs
-- vault_curated/ 기준 재임베딩)은 메인(artrend-ca)이 Q&A 아키텍처 방향
-- 확정 후 결정한다. embed_vault.py / query_vault.py는 건드리지 않음(메인 몫) —
-- 이 두 스크립트가 참조하는 테이블명이 바뀌었으므로 재실행 전 반드시 확인 필요.

alter table if exists vault_embeddings rename to vault_embeddings_legacy_20260915;

-- 인덱스/제약은 rename에 자동으로 따라간다(이름은 원래 이름 그대로 유지됨 —
-- 예: vault_embeddings_pkey, vault_embeddings_doc_path_key, idx_vault_embeddings_doc_type).
-- 필요 시 나중에 명시적으로 재명명 가능하나 지금은 손대지 않는다.
