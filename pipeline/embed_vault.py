"""vault_curated/ 마크다운 문서 -> 로컬 다국어 임베딩 모델 -> vault_embeddings 테이블 적재.

2026-09-15: 1세대 vault/는 폐기(docs/QA아키텍처.md), vault_embeddings는 dead 참조라
vault_embeddings_legacy_20260915로 rename됨(0005). 이 스크립트는 2세대
vault_curated/ 기준으로 새 vault_embeddings 테이블(0012)에 적재하도록 갱신됨.
vault_curated는 M6(정본화) 이전 산출물이라 재생성 전까지는 실제 임베딩 실행 보류.

Gemini API(무료 티어 일일 1,000건 쿼터)로 시작했으나 vault 규모(약 18만 건)에 비해
턱없이 부족해(전체 완주까지 약 186일) 로컬 모델로 전환함(2026-09-03).
과금 계정을 쓸 수 없는 제약과 무관하게 API 자체를 안 쓰므로 쿼터 문제가 없다.

모델: intfloat/multilingual-e5-small (384차원, 다국어 지원, CPU에서도 충분히 빠름).
e5 계열 관례대로 문서는 "passage: ", 질의는 "query: " 접두어를 붙여야 검색 품질이 나온다
(query_vault.py에서 질의 쪽 접두어 처리).

pgvector 없이 float4[] 컬럼 + Python(numpy) 코사인 유사도로 검색한다(0002 마이그레이션 참고).

문서 내용이 바뀌지 않았으면(content_hash 동일) 재임베딩을 건너뛴다 — 중단 후 재실행 가능.

사용법:
    python embed_vault.py --limit 20        # 테스트용
    python embed_vault.py                    # 전체(오래 걸림 — 백그라운드 실행 권장)
    python embed_vault.py --batch-size 64    # 인코딩 배치 크기 조절
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
import time
from pathlib import Path

import psycopg2
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(line_buffering=True)

load_dotenv(Path(__file__).resolve().parent / ".env")

VAULT_ROOT = Path(__file__).resolve().parent.parent / "vault_curated"
MODEL_NAME = "intfloat/multilingual-e5-small"
MAX_CHARS = 6000

# 폴더명(복수형) -> doc_type(단수형). "galleries".rstrip("s") == "gallerie"가
# 되는 등 단순 rstrip으로는 안 깨지는 것도 있고 깨지는 것도 있어(2026-09-15
# vault_curated 폴더 확인 시 발견) 명시 매핑을 우선 쓰고, 매핑에 없는 폴더만
# rstrip("s")로 폴백한다.
DOC_TYPE_MAP = {
    "artists": "artist",
    "artworks": "artwork",
    "auction_houses": "auction_house",
    "collectors": "collector",
    "galleries": "gallery",
    "museums": "museum",
}


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


_TABLE_ROW_RE = re.compile(r"^\s*\|")
MAX_TABLE_ROWS_PER_TABLE = 5  # 헤더+구분선+샘플 몇 줄만 임베딩에 포함, 나머지는 잘라냄


def compact_for_embedding(text: str) -> str:
    """소장작/경매기록처럼 표가 수천 행에 달하는 문서는 표 본문이 임베딩 벡터를
    지배해버려서, 정작 이름/약력 같은 정체성 신호가 희석되고 검색에서 밀려난다
    (실제 사례: 소장 2,935건인 진짜 'Rembrandt van Rijn'이 소장 1건짜리 철자
    변형 'Rembrandt van Rhijn'에게 검색 순위를 뺏김, 2026-09-04 스모크 테스트로
    확인). 표는 헤더+샘플 몇 줄만 남기고 나머지 행은 잘라 정체성/요약 텍스트가
    MAX_CHARS 안에 반드시 들어가게 한다. 인용용 원문(citation)은 이 함수를
    거치지 않고 query_vault.py가 파일을 그대로 다시 읽으므로 손실 없음."""
    out: list[str] = []
    table_row_count = 0
    for line in text.split("\n"):
        if _TABLE_ROW_RE.match(line):
            table_row_count += 1
            if table_row_count <= MAX_TABLE_ROWS_PER_TABLE:
                out.append(line)
            elif table_row_count == MAX_TABLE_ROWS_PER_TABLE + 1:
                out.append("| ... (이하 생략) |")
        else:
            table_row_count = 0
            out.append(line)
    return "\n".join(out)


def doc_type_of(path: Path) -> str:
    folder = path.relative_to(VAULT_ROOT).parts[0]
    return DOC_TYPE_MAP.get(folder, folder.rstrip("s"))


def iter_vault_docs(only_types: set[str] | None) -> list[Path]:
    docs: list[Path] = []
    for sub in sorted(VAULT_ROOT.iterdir()):
        if not sub.is_dir():
            continue
        if only_types and sub.name not in only_types:
            continue
        docs.extend(sorted(sub.glob("*.md")))
    return docs


def main() -> None:
    parser = argparse.ArgumentParser(description="vault/ -> 로컬 임베딩 -> DB")
    parser.add_argument("--limit", type=int, default=None, help="테스트용 — 처리할 최대 문서 수")
    parser.add_argument("--batch-size", type=int, default=32, help="인코딩 배치 크기")
    parser.add_argument("--types", type=str, default=None, help="artists,museums,galleries 중 쉼표구분 (기본 전체)")
    parser.add_argument("--shard-index", type=int, default=0, help="병렬 실행 시 이 프로세스가 맡을 샤드 번호(0-based)")
    parser.add_argument("--shard-count", type=int, default=1, help="병렬 실행 시 전체 샤드 수 — 문서를 shard-count개로 나눠 shard-index만 처리")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="모델 로딩/DB 접속 없이 대상 문서 수·doc_type 분포만 출력하고 종료",
    )
    args = parser.parse_args()

    only_types = set(args.types.split(",")) if args.types else None
    docs = iter_vault_docs(only_types)

    if args.dry_run:
        from collections import Counter

        counts = Counter(doc_type_of(p) for p in docs)
        print(f"[embed] --dry-run: VAULT_ROOT={VAULT_ROOT}")
        print(f"[embed] 대상 문서 {len(docs)}건")
        for doc_type, n in sorted(counts.items()):
            print(f"  {doc_type}: {n}")
        return

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL 환경변수가 필요합니다")
    if args.shard_count > 1:
        docs = [d for i, d in enumerate(docs) if i % args.shard_count == args.shard_index]
        print(f"[embed] 샤드 {args.shard_index}/{args.shard_count} — 이 프로세스 담당 {len(docs)}건")
    if args.limit:
        docs = docs[: args.limit]
    print(f"[embed] 대상 문서 {len(docs)}건")

    conn = psycopg2.connect(dsn)
    cur = conn.cursor()

    print(f"[embed] 모델 로딩 중: {MODEL_NAME}")
    t0 = time.time()
    model = SentenceTransformer(MODEL_NAME)
    print(f"[embed] 모델 로딩 완료 ({time.time() - t0:.1f}초)")

    # 이미 임베딩된 doc_path -> content_hash 전체를 한 번에 메모리로 로드해 매 문서마다 DB 왕복하지 않음
    cur.execute("select doc_path, content_hash from vault_embeddings")
    existing = dict(cur.fetchall())

    processed = skipped = 0
    batch_paths: list[Path] = []
    batch_texts: list[str] = []
    batch_rel: list[str] = []
    batch_hash: list[str] = []

    def flush_batch():
        nonlocal processed
        if not batch_texts:
            return
        vectors = model.encode(
            [f"passage: {t}" for t in batch_texts],
            batch_size=args.batch_size,
            show_progress_bar=False,
            normalize_embeddings=False,
        )
        for path, rel_path, h, vector in zip(batch_paths, batch_rel, batch_hash, vectors):
            cur.execute(
                """
                insert into vault_embeddings (doc_path, doc_type, content_hash, model, embedding)
                values (%s, %s, %s, %s, %s)
                on conflict (doc_path) do update set
                    content_hash = excluded.content_hash,
                    model = excluded.model,
                    embedding = excluded.embedding,
                    embedded_at = now()
                """,
                (rel_path, doc_type_of(path), h, MODEL_NAME, vector.tolist()),
            )
            processed += 1
        conn.commit()
        batch_paths.clear()
        batch_texts.clear()
        batch_rel.clear()
        batch_hash.clear()

    for i, path in enumerate(docs):
        rel_path = str(path.relative_to(VAULT_ROOT)).replace("\\", "/")
        text = compact_for_embedding(path.read_text(encoding="utf-8"))[:MAX_CHARS]
        if not text.strip():
            continue
        h = content_hash(text)

        if existing.get(rel_path) == h:
            skipped += 1
            continue

        batch_paths.append(path)
        batch_texts.append(text)
        batch_rel.append(rel_path)
        batch_hash.append(h)

        if len(batch_texts) >= args.batch_size:
            flush_batch()
            if processed % 2000 < args.batch_size:
                print(f"[embed] {processed}건 임베딩 완료 (스킵 {skipped}, 총 {i + 1}/{len(docs)})")

    flush_batch()

    cur.close()
    conn.close()
    print(f"[embed] 완료 — 임베딩 {processed}건, 스킵(변경없음) {skipped}건")


if __name__ == "__main__":
    main()
