-- vault/ 마크다운 문서 임베딩 저장 테이블.
-- 로컬 Postgres(포터블 바이너리)엔 pgvector 확장이 없어(2026-09-03 확인),
-- float4[] 컬럼에 벡터를 저장하고 코사인 유사도는 조회 시 Python(numpy)에서 계산한다.
-- 이 프로젝트 규모(수십만 문서)에서는 pgvector 없이도 충분히 빠르다.

create table if not exists vault_embeddings (
    id uuid primary key default gen_random_uuid(),
    doc_path text not null unique,       -- vault/ 기준 상대경로, 예: artists/이우환 (a1b2c3d4).md
    doc_type text not null,               -- artist / museum / gallery / artwork ...
    content_hash text not null,           -- 임베딩한 텍스트의 sha256 — 변경분만 재임베딩할 때 비교
    model text not null,                  -- 예: gemini-embedding-001
    embedding float4[] not null,
    embedded_at timestamptz not null default now()
);

create index if not exists idx_vault_embeddings_doc_type on vault_embeddings(doc_type);
