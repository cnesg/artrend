"""vault_embeddings 테이블에서 질의 텍스트와 가장 유사한 문서를 찾는다.

pgvector 없이 float4[] 컬럼 전체를 한 번에 읽어 numpy로 코사인 유사도 계산.
이 프로젝트 규모(수십만 건)에서도 브루트포스로 충분히 빠르다 — DB에서 embedding을
한 번에 fetch(수 초~수십 초, 컬럼 크기에 비례)한 뒤 계산 자체는 밀리초 단위.

embed_vault.py와 동일한 로컬 모델(intfloat/multilingual-e5-small) 사용 — API 호출 없음.

사용법:
    python query_vault.py "이우환의 대표작은?"
    python query_vault.py "청자 소장품" --top 10 --types artist,museum
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path

import numpy as np
import psycopg2
import requests
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

load_dotenv(Path(__file__).resolve().parent / ".env")

MODEL_NAME = "intfloat/multilingual-e5-small"
VAULT_ROOT = Path(__file__).resolve().parent.parent / "vault"

# 답변 생성용 — 임베딩(로컬 모델)과는 별개, Gemini generateContent REST 호출.
# 특정 버전에 고정하지 않고 latest 별칭 사용(모델 세대 바뀌어도 코드 안 건드리게).
# gemini-flash-latest는 스모크 테스트 중 "high demand" 503이 반복 발생(2026-09-04,
# 최소 재현 스크립트로도 확인) — gemini-flash-lite-latest는 같은 시점에 정상 응답.
GEMINI_ANSWER_MODEL = "gemini-flash-lite-latest"
GEMINI_ANSWER_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_ANSWER_MODEL}:generateContent"
)

ANSWER_SYSTEM_PROMPT = """당신은 아트그래프(미술품·경매·미술관·갤러리 통합 위키)의 질의응답
어시스턴트입니다. 아래 제공된 문서들(vault 마크다운, DB에서 추출)만 근거로 답하세요.

규칙:
- 문서에 없는 내용은 추측하지 말고 "제공된 문서에서 확인 안 됨"이라고 밝히세요.
- 답변 문장마다 어느 문서에서 가져온 정보인지 [문서 N] 형식으로 인용하세요.
- 여러 문서에 걸친 내용을 종합할 때도 각 사실마다 출처를 붙이세요.
- 한국어로 답하세요.
"""


def generate_answer(query: str, docs: list[tuple[str, str, str]]) -> str:
    """docs: [(doc_path, doc_type, content), ...] — 순서대로 [문서 1], [문서 2]...로 인용."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return "[답변 생성 실패] GEMINI_API_KEY가 설정되지 않았습니다 (pipeline/.env 확인)."

    context_blocks = []
    for i, (doc_path, doc_type, content) in enumerate(docs, 1):
        context_blocks.append(f"[문서 {i}] (type={doc_type}, path={doc_path})\n{content}")
    context = "\n\n---\n\n".join(context_blocks)

    prompt = f"{ANSWER_SYSTEM_PROMPT}\n\n### 문서\n\n{context}\n\n### 질문\n{query}\n\n### 답변"

    last_error: Exception | None = None
    for attempt in range(3):
        try:
            resp = requests.post(
                GEMINI_ANSWER_URL,
                params={"key": api_key},
                json={"contents": [{"parts": [{"text": prompt}]}]},
                timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as e:
            last_error = e
            if attempt < 2:
                time.sleep(2 ** attempt)  # 503(과부하)/타임아웃 대비 지수 백오프
    return f"[답변 생성 실패, 3회 재시도 후] {last_error}"


def embed_query(model: SentenceTransformer, text: str) -> np.ndarray:
    vec = model.encode([f"query: {text}"], normalize_embeddings=False)[0]
    return np.array(vec, dtype=np.float32)


def load_corpus(conn, only_types: set[str] | None) -> tuple[list[str], list[str], np.ndarray]:
    cur = conn.cursor()
    if only_types:
        cur.execute(
            "select doc_path, doc_type, embedding from vault_embeddings where doc_type = any(%s)",
            (list(only_types),),
        )
    else:
        cur.execute("select doc_path, doc_type, embedding from vault_embeddings")
    rows = cur.fetchall()
    cur.close()
    if not rows:
        return [], [], np.empty((0, 0), dtype=np.float32)
    paths = [r[0] for r in rows]
    types = [r[1] for r in rows]
    matrix = np.array([r[2] for r in rows], dtype=np.float32)
    return paths, types, matrix


def cosine_top_k(query_vec: np.ndarray, matrix: np.ndarray, k: int) -> list[tuple[int, float]]:
    q_norm = query_vec / (np.linalg.norm(query_vec) + 1e-9)
    m_norm = matrix / (np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-9)
    sims = m_norm @ q_norm
    top_idx = np.argsort(-sims)[:k]
    return [(int(i), float(sims[i])) for i in top_idx]


_COUNT_RE = re.compile(r"\((\d+)건\)")
RICHNESS_WEIGHT = 0.004
CANDIDATE_POOL_MULT = 6  # 재정렬 전 후보군을 --top의 이만큼 넉넉히 뽑음


def richness_score(doc_path: Path) -> int:
    """소장작/경매기록 등 '(N건)' 표기를 합산 — 384차원 소형 임베딩 모델은
    'Rembrandt van Rijn' vs 'Rembrandt van Rhijn' 같은 극도로 비슷한 표기를
    의미적으로 구분 못 해 코사인 유사도가 사실상 동률로 나온다(실측 확인,
    2026-09-04) — 데이터가 풍부한(=연결이 많이 된) 문서를 동률 구간에서
    우선하도록 재정렬 가중치를 얹는다. 재임베딩 불필요, 쿼리 시점 보정."""
    if not doc_path.exists():
        return 0
    text = doc_path.read_text(encoding="utf-8")
    return sum(int(m) for m in _COUNT_RE.findall(text))


def rerank_by_richness(
    candidates: list[tuple[int, float]], paths: list[str], k: int
) -> list[tuple[int, float, float]]:
    """(idx, cosine_score) 후보 목록을 richness 가중 재정렬 — (idx, adjusted_score, cosine_score) 반환."""
    adjusted = []
    for idx, score in candidates:
        boost = RICHNESS_WEIGHT * np.log1p(richness_score(VAULT_ROOT / paths[idx]))
        adjusted.append((idx, score + boost, score))
    adjusted.sort(key=lambda t: -t[1])
    return adjusted[:k]


def main() -> None:
    parser = argparse.ArgumentParser(description="vault_embeddings 유사도 검색")
    parser.add_argument("query", type=str, help="질의 텍스트")
    parser.add_argument("--top", type=int, default=5)
    parser.add_argument("--types", type=str, default=None, help="artist,museum,gallery 중 쉼표구분")
    parser.add_argument("--show", action="store_true", help="상위 결과 문서 본문 일부도 출력")
    parser.add_argument("--answer", action="store_true", help="검색 결과를 근거로 Gemini가 실제 답변 생성(인용 포함)")
    args = parser.parse_args()

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL 환경변수가 필요합니다")

    only_types = set(args.types.split(",")) if args.types else None

    conn = psycopg2.connect(dsn)
    paths, types, matrix = load_corpus(conn, only_types)
    conn.close()

    if matrix.size == 0:
        print("[query] vault_embeddings에 데이터가 없습니다 — embed_vault.py를 먼저 실행하세요")
        return

    print(f"[query] 코퍼스 {len(paths)}건 로드 완료, 질의 임베딩 중...")
    model = SentenceTransformer(MODEL_NAME)
    query_vec = embed_query(model, args.query)

    candidates = cosine_top_k(query_vec, matrix, args.top * CANDIDATE_POOL_MULT)
    reranked = rerank_by_richness(candidates, paths, args.top)
    results = [(idx, adj_score) for idx, adj_score, _cos in reranked]
    print(f"\n[query] \"{args.query}\" 상위 {args.top}건 (richness 재정렬 적용):\n")
    for rank, (idx, adj_score, cos_score) in enumerate(reranked, 1):
        print(f"{rank}. (조정 {adj_score:.4f}, 코사인 {cos_score:.4f}) [{types[idx]}] {paths[idx]}")
        if args.show:
            doc_path = VAULT_ROOT / paths[idx]
            if doc_path.exists():
                snippet = doc_path.read_text(encoding="utf-8")[:300].replace("\n", " ")
                print(f"    {snippet}...")

    if args.answer:
        docs = []
        for idx, _score in results:
            doc_path = VAULT_ROOT / paths[idx]
            if doc_path.exists():
                content = doc_path.read_text(encoding="utf-8")
                docs.append((paths[idx], types[idx], content))
        print("\n[answer] Gemini에 답변 생성 요청 중...\n")
        answer = generate_answer(args.query, docs)
        print(answer)


if __name__ == "__main__":
    main()
