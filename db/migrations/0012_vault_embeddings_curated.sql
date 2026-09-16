-- 0012_vault_embeddings_curated.sql
-- 2026-09-15 워커 큐: W-vault 준비 (0005에서 legacy로 옮긴 뒤 비어 있던 vault_embeddings 재생성).
--
-- vault_curated/ 기준으로 새로 임베딩할 테이블. 스키마는 0002의 원본
-- vault_embeddings와 동일 — legacy와 나란히 비교/이관하기 쉽게 유지한다.
-- 실제 임베딩 실행은 main이 build_curated_vault.py 재생성 후 별도 지시.

create table if not exists vault_embeddings (
    id uuid primary key default gen_random_uuid(),
    doc_path text not null unique,       -- vault_curated/ 기준 상대경로
    doc_type text not null,               -- artist / artwork / auction_house / collector / gallery / museum
    content_hash text not null,
    model text not null,
    embedding float4[] not null,
    embedded_at timestamptz not null default now()
);

create index if not exists idx_vault_embeddings_doc_type on vault_embeddings(doc_type);
