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


RICHNESS_WEIGHT = 0.004
_DOC_ID_RE = re.compile(r"\(([0-9a-f]{8})\)\.md$")

# 2026-09-04 실패 사례: 좁은 후보군(top×6)만 코사인으로 먼저 추려서 재정렬했더니
# 진짜 canonical 문서가 그 후보군에도 못 들어 실패함(23만+건 전체 코퍼스 중
# 무관한 문서가 우연히 높은 코사인을 받는 경우가 많음). 이번엔 richness를
# **전체 코퍼스에** 벡터 연산으로 얹은 뒤 top-k를 뽑는다 — 후보군을 먼저
# 좁히지 않음. 파일을 읽지 않고 DB 집계 쿼리로 한 번에 계산(속도).


def load_richness_by_id8(conn) -> dict[str, int]:
    """artist_id[:8] -> (museum_holdings + auction_lots) 합계.

    vault 파일명이 'Name (xxxxxxxx).md' 형태로 artist_id 앞 8자리를 담고 있어
    doc_path만으로 매칭 가능 — 임베딩 텍스트 파일을 다시 읽을 필요 없음."""
    cur = conn.cursor()
    cur.execute(
        """
        select substring(aw.artist_id::text, 1, 8) as id8,
               count(distinct mh.id) + count(distinct al.id) as richness
        from artworks aw
        left join museum_holdings mh on mh.artwork_id = aw.id
        left join auction_lots al on al.artwork_id = aw.id
        where aw.artist_id is not null
        group by aw.artist_id
        """
    )
    result = {row[0]: row[1] for row in cur.fetchall()}
    cur.close()
    return result


def richness_vector(paths: list[str], richness_by_id8: dict[str, int]) -> np.ndarray:
    out = np.zeros(len(paths), dtype=np.float32)
    for i, p in enumerate(paths):
        m = _DOC_ID_RE.search(p)
        if m:
            out[i] = richness_by_id8.get(m.group(1), 0)
    return out


# 2026-09-04~05: 임베딩 재정렬(richness 부스트)로 3번 시도했으나 전부 실패 —
# 384차원 소형 모델이 "Rembrandt van Rijn" 같은 고유명사 질의의 의미 유사도를
# 신뢰할 만큼 못 잡음(실측: canonical 문서가 23만+건 중 4,344등까지 밀림).
# 순수 semantic search로는 이 클래스의 질의를 못 푼다고 판단 — 고유명사가
# 질의에 있으면 DB 정확/부분 매칭을 먼저 시도하고, 못 찾을 때만 semantic
# search로 폴백하는 하이브리드 구조로 전환(사용자 승인, 2026-09-05).
_NAME_TOKEN_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ.'-]*")


def extract_name_candidate(query: str) -> str | None:
    """질의에서 라틴 문자 토큰(고유명사로 추정)의 최장 연속 구간을 추출.
    한국어 조사/설명문("의 미술관 소장작과 경매 기록")과 섞인 질의에서
    'Rembrandt van Rijn' 부분만 뽑아내기 위함."""
    tokens = query.split()
    best: list[str] = []
    current: list[str] = []
    for tok in tokens:
        if _NAME_TOKEN_RE.fullmatch(tok.strip(",.")):
            current.append(tok.strip(",."))
        else:
            if len(current) > len(best):
                best = current
            current = []
    if len(current) > len(best):
        best = current
    if len(best) < 2:  # 한 단어짜리는 흔한 오탐 위험 커서 제외(예: "the", "art")
        return None
    return " ".join(best)


def resolve_entity(conn, name_candidate: str) -> tuple[str, str] | None:
    """artists.name과 정확/부분 일치하는 행을 찾아 (artist_id, name) 반환.
    정확 일치(대소문자 무시) 우선, 없으면 부분 일치 중 가장 짧은(가장 구체적인) 것."""
    cur = conn.cursor()
    cur.execute(
        "select id, name from artists where lower(name) = lower(%s) limit 1",
        (name_candidate,),
    )
    row = cur.fetchone()
    if row:
        cur.close()
        return str(row[0]), row[1]
    cur.execute(
        "select id, name from artists where name ilike %s order by length(name) asc limit 1",
        (f"%{name_candidate}%",),
    )
    row = cur.fetchone()
    cur.close()
    return (str(row[0]), row[1]) if row else None


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

    name_candidate = extract_name_candidate(args.query)
    resolved = resolve_entity(conn, name_candidate) if name_candidate else None
    if resolved:
        artist_id, artist_name = resolved
        id8 = artist_id.replace("-", "")[:8]
        matches = list(VAULT_ROOT.glob(f"artists/*({id8}).md"))
        if matches:
            conn.close()
            print(f"[query] 고유명사 매칭: \"{name_candidate}\" -> \"{artist_name}\" (정확/부분 일치, semantic search 생략)")
            doc_path = matches[0]
            rel_path = str(doc_path.relative_to(VAULT_ROOT)).replace("\\", "/")
            print(f"\n1. [artist] {rel_path}\n")
            if args.show or args.answer:
                content = doc_path.read_text(encoding="utf-8")
                if args.show:
                    print(f"    {content[:300].replace(chr(10), ' ')}...")
                if args.answer:
                    print("\n[answer] Gemini에 답변 생성 요청 중...\n")
                    print(generate_answer(args.query, [(rel_path, "artist", content)]))
            return

    paths, types, matrix = load_corpus(conn, only_types)
    richness_by_id8 = load_richness_by_id8(conn)
    conn.close()

    if matrix.size == 0:
        print("[query] vault_embeddings에 데이터가 없습니다 — embed_vault.py를 먼저 실행하세요")
        return

    print(f"[query] 코퍼스 {len(paths)}건 로드 완료, 질의 임베딩 중...")
    model = SentenceTransformer(MODEL_NAME)
    query_vec = embed_query(model, args.query)

    q_norm = query_vec / (np.linalg.norm(query_vec) + 1e-9)
    m_norm = matrix / (np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-9)
    cos_scores = m_norm @ q_norm  # 전체 코퍼스 코사인 유사도 (후보군 좁히지 않음)

    richness = richness_vector(paths, richness_by_id8)
    adj_scores = cos_scores + RICHNESS_WEIGHT * np.log1p(richness)

    top_idx = np.argsort(-adj_scores)[: args.top]
    results = [(int(i), float(adj_scores[i])) for i in top_idx]
    print(f"\n[query] \"{args.query}\" 상위 {args.top}건 (richness 재정렬, 전체 {len(paths)}건 대상):\n")
    for rank, i in enumerate(top_idx, 1):
        i = int(i)
        print(f"{rank}. (조정 {adj_scores[i]:.4f}, 코사인 {cos_scores[i]:.4f}, richness {int(richness[i])}) [{types[i]}] {paths[i]}")
        if args.show:
            doc_path = VAULT_ROOT / paths[i]
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
