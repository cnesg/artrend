"""ArtGraph Text-to-SQL + Hybrid QA Engine

사용자의 자연어 질문을 입력받아 PostgreSQL(ArtGraph) 데이터베이스에서
정형 정보(소장 미술관, 경매 기록, 전속 갤러리, 프로버넌스 등)를 조회하고,
Gemini LLM을 통해 정확한 출처와 함께 마크다운 답변을 생성합니다.

사용법:
    # 단일 질문 실행
    python pipeline/artgraph_chat.py --question "이우환 작가의 미술관 소장 현황과 경매 기록 요약해줘"
    python pipeline/artgraph_chat.py --question "국립현대미술관(MMCA)에 소장된 김환기 작품 목록 알려줘"

    # 인터랙티브 대화 모드
    python pipeline/artgraph_chat.py --interactive
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

import psycopg2
import psycopg2.extras
import requests
from dotenv import load_dotenv

# 콘솔 UTF-8 출력 보장
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# .env 로드
ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(ENV_PATH)

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres@127.0.0.1:5433/artrend")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

# Gemini 모델 설정
GEMINI_MODELS = [
    "gemini-flash-lite-latest",
    "gemini-2.5-flash",
    "gemini-flash-latest",
]

SCHEMA_DESCRIPTION = """
[PostgreSQL DB 스키마: ArtGraph (artrend)]

1. artists (작가):
   - id (uuid, PK), name (text), name_en (text), birth_year (int), death_year (int), nationality (text), bio (text, 원본 소스 약력만), source_id (uuid)
   - entity_kind (text: 'person'|'anonymous'|'culture'|'organization'|'attribution') — 작가 질문은 기본적으로 entity_kind='person'만 대상. 'anonymous'(작자 미상)·'culture'(국가/시대명)·'organization'(기업/공방)·'attribution'(귀속 표기, attribution_of → 본체 작가 id)은 사람 작가가 아님
   - ulan_id (text, Getty ULAN), wikidata_qid (text, Wikidata Q-ID) — 같은 ID면 같은 작가
1-b. artist_bio_generated (AI 생성 약력, 원본 아님): artist_id (FK), bio (text), model (text), generated_at — 인용 시 반드시 "[AI 생성 약력]"으로 표기
2. artworks (작품):
   - id (uuid, PK), artist_id (uuid, FK -> artists.id), title (text), title_en (text), year_created (text), medium (text), dimensions (text), description (text), source_id (uuid)
   - attribution_qualifier (text): 'copy after' / 'manner of; style of' / 'attributed to' / 'school of' / 'circle of' 등이면 artist_id 작가의 진작이 아니라 그 작가에 귀속된 작품. 작가의 작품 수·경매 기록을 셀 때는 attribution_qualifier is null 조건을 기본으로 하고, 귀속작은 따로 표기
3. museums (미술관):
   - id (uuid, PK), name (text), name_en (text), country (text), city (text), type (text), website (text), source_id (uuid)
4. museum_holdings (미술관 소장품):
   - id (uuid, PK), museum_id (uuid, FK -> museums.id), artwork_id (uuid, FK -> artworks.id), accession_number (text), acquisition_date (date), acquisition_method (text), donor_name (text), source_id (uuid)
5. galleries (갤러리/화랑):
   - id (uuid, PK), name (text), city (text), country (text), website (text), source_id (uuid)
6. gallery_representations (갤러리 전속/대표 관계):
   - id (uuid, PK), gallery_id (uuid, FK -> galleries.id), artist_id (uuid, FK -> artists.id), start_date (date), end_date (date, null이면 현재 대표 중), source_id (uuid)
7. auction_houses (경매사):
   - id (uuid, PK), name (text), country (text)
8. auctions (경매 회차):
   - id (uuid, PK), auction_house_id (uuid, FK -> auction_houses.id), name (text), auction_date (date), location (text), source_id (uuid)
9. auction_lots (경매 출품작/낙찰 기록):
   - id (uuid, PK), auction_id (uuid, FK -> auctions.id), artwork_id (uuid, FK -> artworks.id), lot_number (text), estimate_low (numeric), estimate_high (numeric), currency (text), hammer_price (numeric), sold (boolean), source_id (uuid)
   - price_usd, estimate_low_usd, estimate_high_usd (numeric): 1970년 이후·ISO 통화 로트에만 채워짐. 그 외(livres/florins 등 역사 통화)는 NULL — 역사 가격을 USD로 환산하거나 시대 간 가격을 비교하지 말 것
10. collectors (컬렉터/소장가/소장기관):
    - id (uuid, PK), name (text), is_institution (boolean), bio (text), source_id (uuid)
11. provenance_records (소유 이력 체인):
    - id (uuid, PK), artwork_id (uuid, FK -> artworks.id), owner_type ('collector'|'museum'|'gallery'|'auction_house'|'unknown'), owner_collector_id, owner_museum_id, owner_gallery_id, owner_auction_house_id, acquired_date, acquired_method, disposed_date, note, source_id (uuid)
12. sources (원본 출처):
    - id (uuid, PK), url (text), site_name (text), fetched_at (timestamptz), raw_path (text), license_note (text)
13. exhibitions (전시): id, title, venue_kind ('museum'|'gallery'|'fair'|'other'), museum_id, gallery_id, venue_name, city, country, start_date, end_date, url, source_id
14. exhibition_artists: exhibition_id (FK), artist_id (FK), role
15. artist_events (작가 사건): artist_id (FK), event_kind ('award'|'residency'|'acquisition'|'representation_start'|'representation_end'|'death'|'other'), event_date, detail, url, source_id
16. market_stats_kr (한국 미술시장 연간 공개 통계, K-ARTMARKET 2010~2024): year, metric, value, unit, source_url, note. metric 값은 영문 고정: auction_total_krw(경매 낙찰총액), auction_sell_through_rate(낙찰률 %), gallery_sales_krw(화랑 판매액), artfair_sales_krw(아트페어 매출), market_total_krw(합계, note "[산출값]"). value 단위는 unit 컬럼(백만원/%) — 한글로 metric을 검색하지 말고 위 영문 값을 = 로 조회할 것.

[데이터 범위 — 반드시 숙지]
- 미술관 소장품(약 200만 건)은 대형 공공 컬렉션 위주로 과거 작품이 대부분이며, museum_holdings.acquisition_date는 사실상 비어 있어 "최근 취득" 질문에는 답할 수 없다.
- 경매 기록은 (a) Getty Provenance Index 1675~1944년 유럽 판매 기록과 (b) Bonhams 2003년~현재 한 곳뿐이다. Christie's/Sotheby's/Phillips/서울옥션/K옥션 기록은 없다. 1950~1999년은 거의 공백. "최근 시세·시장 흐름" 질문은 Bonhams 단일 경매사 표본임을 명시해야 한다.
- 갤러리 전속 관계는 93개 갤러리 명부 기준이며 시작일이 없다. 전시·사건 테이블(13~15)은 2026-09-15 신설로 아직 비어 있을 수 있다.
- 한국 데이터는 국립현대미술관·서울시립·부산시립·리움·경기도미술관 소장품과 국내 갤러리 일부뿐이며 한국 경매 기록은 없다.
"""

TEXT_TO_SQL_SYSTEM_PROMPT = f"""당신은 아트그래프(ArtGraph) 데이터베이스 전문 SQL 엔지니어입니다.
사용자의 자연어 질문을 분석하여 PostgreSQL에서 필요한 데이터를 조회하는 최적의 SQL 쿼리를 작성하세요.

{SCHEMA_DESCRIPTION}

[작성 규칙]
1. 오직 데이터 조회(SELECT) 쿼리만 작성하세요. (DML, DDL 금지)
2. 한국어 및 영문 검색을 고려하여 ILIKE 또는 LIKE 검색을 활용하세요.
   - 예: `(a.name ILIKE '%이우환%' OR a.name_en ILIKE '%Lee Ufan%')`
   - 작가명에 괄호나 한자 등이 포함될 수 있으므로 `LIKE '%이름%'` 형태로 매칭하세요.
3. 여러 성격의 질문(예: 소장 현황 + 경매 기록 + 전속 갤러리)인 경우, 질문 목적에 맞는 1개~3개의 명확한 SELECT 쿼리를 분리하여 작성할 수 있습니다.
4. 출처 정보(`sources`)를 JOIN하여 `s.site_name`, `s.url`을 포함시키면 답변 생성 시 출처를 인용하기 좋습니다.
5. 결과가 너무 방대하지 않도록 적절한 `ORDER BY`와 `LIMIT 50`(목록형) 또는 `LIMIT 100`을 설정하세요.
6. 응답은 반드시 다음 JSON 포맷으로만 출력하세요 (Markdown 코드블록 없이 순수 JSON):
{{
  "thought": "질문 의도 분석 및 쿼리 설계 이유",
  "queries": [
    {{
      "title": "쿼리 설명(예: 미술관 소장 현황 통계)",
      "sql": "SELECT ..."
    }}
  ]
}}
"""

ANSWER_SYNTHESIS_SYSTEM_PROMPT = """당신은 아트그래프(ArtGraph) 미술 데이터 전문 AI 도슨트 & 애널리스트입니다.
제공된 데이터베이스 조회 결과만을 엄격한 근거로 삼아, 사용자의 질문에 대해 명확하고 구조화된 마크다운(Markdown) 보고서/답변을 작성하세요.

[답변 작성 가이드]
1. **요약(Executive Summary)**: 질문의 핵심에 대한 종합 요약을 서두에 2~3문장으로 제시하세요.
2. **구조화된 본문**:
   - 소장 현황, 경매 기록, 갤러리 정보 등 질문에 맞게 섹션(헤딩 `###`, 불릿, 표)으로 정리하세요.
   - 수량(작품 수), 미술관별 소장 건수, 대표 작품명, 제작 연도, 재료/기법 등의 정보를 읽기 쉽게 정리하세요.
3. **정확한 사실성 및 부재 정보 명시**:
   - DB에 조회된 내용만 사실로 기술하세요.
   - 만약 특정 항목(예: 경매 기록, 특정 미술관 소장작 등)이 DB에 존재하지 않거나 결과가 0건인 경우, "데이터베이스 내에 등록된 기록이 없습니다"라고 명확히 밝히세요. 추측으로 가상의 데이터를 지어내지 마세요.
4. **출처 인용(Citations)**:
   - 각 데이터의 출처(소장 미술관명, 데이터 소스 사이트 `site_name` 또는 `url`)를 문맥에 맞게 명시하세요.
5. **어조**:
   - 전문적이고 신뢰감 있는 한국어 문체로 작성하세요.
6. **데이터 범위와 기준 시점 명시**:
   - 답변 끝에 "데이터 범위" 한 줄을 붙이세요: 경매는 Getty 1675~1944(유럽) + Bonhams 2003~현재 한 곳뿐이며 Christie's/Sotheby's/한국 경매사는 없음, 미술관 취득 시점 정보 없음. 질문이 "요즘/최근/시세/트렌드"를 묻는 경우 이 한계를 요약 첫머리에서 먼저 밝히세요.
   - 조회 결과에 sources.fetched_at이 있으면 "기준 시점(as of)"으로 표기하세요. 역사 통화(livres, florins, guilders 등) 가격은 USD로 환산하지 말고 원 통화 그대로 적으세요.
   - artists.entity_kind가 'anonymous'/'culture'/'organization'인 행을 "작가"로 서술하지 마세요("작자 미상", "국가/시대 분류", "제작사"로 구분). artist_bio_generated의 약력은 "[AI 생성 약력]"이라고 명시하세요.
"""


def get_db_connection():
    """PostgreSQL 연결 생성 (UTF-8 인코딩)"""
    dsn = os.environ.get("DATABASE_URL", DATABASE_URL)
    conn = psycopg2.connect(dsn)
    conn.set_client_encoding("UTF8")
    with conn.cursor() as cur:
        cur.execute("SET default_transaction_read_only = on;")
    return conn


def call_gemini_api(system_prompt: str, user_content: str, max_retries: int = 3) -> str:
    """Gemini REST API 호출 (모델 폴백 및 재시도)"""
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY가 설정되지 않았습니다. pipeline/.env를 확인하세요.")

    last_error: Exception | None = None

    for model_name in GEMINI_MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": f"{system_prompt}\n\n---\n\n{user_content}"}],
                }
            ],
            "generationConfig": {
                "temperature": 0.1,
            },
        }

        for attempt in range(max_retries):
            try:
                resp = requests.post(
                    url,
                    params={"key": GEMINI_API_KEY},
                    json=payload,
                    timeout=60,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if candidates and "content" in candidates[0]:
                        parts = candidates[0]["content"].get("parts", [])
                        if parts and "text" in parts[0]:
                            return parts[0]["text"]
                elif resp.status_code in (429, 500, 503):
                    time.sleep(1.5 ** attempt)
                    continue
                else:
                    last_error = RuntimeError(f"HTTP {resp.status_code}: {resp.text}")
                    break
            except Exception as e:
                last_error = e
                time.sleep(1.5 ** attempt)

    raise RuntimeError(f"Gemini API 호출 실패: {last_error}")


def find_entity_hints(conn, question: str) -> str:
    """질문 내 주요 키워드를 바탕으로 DB 내 엔티티(작가, 미술관, 갤러리) 힌트 추출"""
    hints: list[str] = []
    
    # 2글자 이상의 한글/영문 단어 추출
    words = re.findall(r"[가-힣A-Za-z0-9]+", question)
    # 일반적인 질의어 제외
    stop_words = {
        "작가", "작가의", "작품", "작품들", "목록", "현황", "기록", "요약", "요약해줘",
        "알려줘", "알려주세요", "보여줘", "조회", "검색", "어느", "얼마", "얼마에", "소장",
        "소장된", "소장품", "경매", "경매가", "낙찰", "낙찰가", "미술관", "갤러리", "화랑",
        "알려", "목록을", "대해", "관련", "정보", "어디", "누구", "모두", "전체"
    }
    keywords = [w for w in words if w not in stop_words and len(w) >= 2]

    if not keywords:
        return ""

    with conn.cursor() as cur:
        # 작가 검색
        for kw in keywords:
            cur.execute(
                """
                SELECT id, name, name_en, birth_year, death_year
                FROM artists
                WHERE name ILIKE %s OR name_en ILIKE %s
                ORDER BY (name = %s) DESC, length(name) ASC
                LIMIT 3
                """,
                (f"%{kw}%", f"%{kw}%", kw),
            )
            artists = cur.fetchall()
            for aid, name, name_en, b_yr, d_yr in artists:
                hints.append(f"- 작가 후보: id='{aid}', name='{name}', name_en='{name_en}', life=({b_yr}~{d_yr})")

        # 미술관 검색
        for kw in keywords:
            cur.execute(
                """
                SELECT id, name, name_en, country, city
                FROM museums
                WHERE name ILIKE %s OR name_en ILIKE %s
                ORDER BY (name = %s) DESC, length(name) ASC
                LIMIT 3
                """,
                (f"%{kw}%", f"%{kw}%", kw),
            )
            museums = cur.fetchall()
            for mid, name, name_en, country, city in museums:
                hints.append(f"- 미술관 후보: id='{mid}', name='{name}', name_en='{name_en}', location=({country}, {city})")

        # 갤러리 검색
        for kw in keywords:
            cur.execute(
                """
                SELECT id, name, city, country
                FROM galleries
                WHERE name ILIKE %s
                LIMIT 2
                """,
                (f"%{kw}%",),
            )
            galleries = cur.fetchall()
            for gid, name, city, country in galleries:
                hints.append(f"- 갤러리 후보: id='{gid}', name='{name}', location=({country}, {city})")

    if hints:
        # 중복 제거
        unique_hints = list(dict.fromkeys(hints))
        return "\n[데이터베이스 내 매칭 엔티티 힌트]\n" + "\n".join(unique_hints)
    return ""


def generate_sql_queries(question: str, entity_hints: str) -> list[dict[str, str]]:
    """Gemini를 호출하여 질문에 맞는 SQL 쿼리 목록 생성"""
    user_prompt = f"질문: {question}\n{entity_hints}\n\n위 질문에 답하기 위한 최적의 PostgreSQL SELECT 쿼리 JSON을 작성하세요."
    response_text = call_gemini_api(TEXT_TO_SQL_SYSTEM_PROMPT, user_prompt)

    # JSON 추출
    json_match = re.search(r"\{[\s\S]*\}", response_text)
    if not json_match:
        raise ValueError(f"LLM 응답에서 JSON을 파싱할 수 없습니다:\n{response_text}")

    try:
        parsed = json.loads(json_match.group(0))
        queries = parsed.get("queries", [])
        if not queries and "sql" in parsed:
            queries = [{"title": "데이터 조회", "sql": parsed["sql"]}]
        return queries
    except Exception as e:
        raise ValueError(f"JSON 파싱 오류 ({e}):\n{json_match.group(0)}")


def execute_queries(conn, queries: list[dict[str, str]], question: str, max_fix_retries: int = 2) -> list[dict[str, Any]]:
    """SQL 쿼리들을 실행하고 결과 및 컬럼을 수집 (오류 발생 시 LLM 자동 수정)"""
    results: list[dict[str, Any]] = []

    for q_item in queries:
        title = q_item.get("title", "조회 쿼리")
        sql = q_item.get("sql", "").strip()
        if not sql:
            continue

        # 안전 검사: SELECT로 시작하는지 확인
        if not re.match(r"^\s*(WITH\s+.+\s+AS\s+\([\s\S]+\)\s+)?SELECT\b", sql, re.IGNORECASE):
            continue

        executed_successfully = False
        current_sql = sql

        for retry in range(max_fix_retries + 1):
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                try:
                    cur.execute(current_sql)
                    rows = cur.fetchall()
                    # RealDictCursor 결과를 일반 dict 리스트로 변환 (날짜/UUID 문자열화)
                    serialized_rows = []
                    for r in rows:
                        row_dict = {}
                        for k, v in r.items():
                            if v is not None:
                                row_dict[k] = str(v)
                            else:
                                row_dict[k] = None
                        serialized_rows.append(row_dict)

                    results.append({
                        "title": title,
                        "sql": current_sql,
                        "row_count": len(serialized_rows),
                        "rows": serialized_rows,
                        "error": None,
                    })
                    executed_successfully = True
                    break
                except Exception as db_err:
                    conn.rollback()
                    if retry < max_fix_retries:
                        # LLM에 SQL 오류 수정 요청
                        fix_prompt = f"""다음 SQL 실행 중 PostgreSQL 오류가 발생했습니다:
질문: {question}
실행한 SQL:
{current_sql}

발생한 에러:
{db_err}

{SCHEMA_DESCRIPTION}

오류를 수정한 올바른 SELECT SQL 1개만 JSON으로 반환하세요:
{{"title": "{title}", "sql": "수정된 SELECT SQL"}}
"""
                        try:
                            fix_resp = call_gemini_api(TEXT_TO_SQL_SYSTEM_PROMPT, fix_prompt)
                            fix_json = re.search(r"\{[\s\S]*\}", fix_resp)
                            if fix_json:
                                fix_data = json.loads(fix_json.group(0))
                                current_sql = fix_data.get("sql", current_sql).strip()
                        except Exception:
                            pass
                    else:
                        results.append({
                            "title": title,
                            "sql": current_sql,
                            "row_count": 0,
                            "rows": [],
                            "error": str(db_err),
                        })

    return results


def synthesize_answer(question: str, query_results: list[dict[str, Any]]) -> str:
    """DB 쿼리 결과들을 기반으로 Gemini를 통해 최종 마크다운 답변 생성"""
    context_sections = []
    for i, res in enumerate(query_results, 1):
        section = f"### [데이터셋 {i}] {res['title']} (조회 건수: {res['row_count']}건)\n"
        section += f"**실행 SQL**:\n```sql\n{res['sql']}\n```\n"
        if res.get("error"):
            section += f"**실행 오류**: {res['error']}\n"
        elif res["row_count"] == 0:
            section += "**결과**: 데이터 없음 (0 rows)\n"
        else:
            # 최대 50개 행까지 컨텍스트에 포함
            sample_rows = res["rows"][:50]
            section += "**조회 데이터**:\n```json\n"
            section += json.dumps(sample_rows, ensure_ascii=False, indent=2)
            section += "\n```\n"
        context_sections.append(section)

    full_context = "\n\n".join(context_sections)
    user_prompt = f"""[사용자 질문]
{question}

[데이터베이스 쿼리 및 결과 데이터]
{full_context}

위 데이터베이스 실제 조회 결과를 토대로 사용자의 질문에 대한 완벽한 마크다운 답변을 작성하세요.
"""
    return call_gemini_api(ANSWER_SYNTHESIS_SYSTEM_PROMPT, user_prompt)


def answer_artgraph_question(question: str, verbose: bool = False) -> tuple[str, list[dict[str, Any]]]:
    """단일 질문에 대한 Text-to-SQL + Hybrid QA 파이프라인 실행"""
    conn = get_db_connection()
    try:
        if verbose:
            print(f"[ArtGraph] 엔티티 힌트 검색 중...")
        entity_hints = find_entity_hints(conn, question)
        if verbose and entity_hints:
            print(entity_hints)

        if verbose:
            print(f"[ArtGraph] Text-to-SQL 쿼리 생성 중...")
        queries = generate_sql_queries(question, entity_hints)
        
        if verbose:
            for q in queries:
                print(f"  - [{q.get('title')}]: {q.get('sql')}")

        if verbose:
            print(f"[ArtGraph] SQL 실행 및 데이터 추출 중...")
        query_results = execute_queries(conn, queries, question)

        if verbose:
            for res in query_results:
                print(f"  - [{res['title']}]: {res['row_count']}건 반환 (에러: {res.get('error')})")

        if verbose:
            print(f"[ArtGraph] Gemini 답변 생성 중...\n")
        markdown_answer = synthesize_answer(question, query_results)

        return markdown_answer, query_results
    finally:
        conn.close()


def run_interactive():
    """대화형 인터랙티브 모드 실행"""
    print("=" * 60)
    print("  🎨 ArtGraph 지능형 질의응답 (Text-to-SQL + Hybrid QA)")
    print("  - 미술관 소장품, 경매 낙찰가, 전속 갤러리, 프로버넌스 질의")
    print("  - 종료하려면 'exit', 'quit' 또는 Ctrl+C를 입력하세요.")
    print("=" * 60)
    print()

    while True:
        try:
            user_input = input("ArtGraph> ").strip()
            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit", "q", "종료"):
                print("대화를 종료합니다. 감사합니다!")
                break

            print("\n[질의 분석 및 DB 검색 중...]")
            start_t = time.time()
            answer, results = answer_artgraph_question(user_input, verbose=False)
            elapsed = time.time() - start_t

            print("\n" + "=" * 60)
            print(answer)
            print("=" * 60)
            print(f"(응답 완료: {elapsed:.2f}초 | 쿼리 {len(results)}건 실행)\n")

        except KeyboardInterrupt:
            print("\n대화를 종료합니다.")
            break
        except Exception as e:
            print(f"\n[오류 발생] {e}\n")


def main():
    parser = argparse.ArgumentParser(description="ArtGraph Text-to-SQL + Hybrid QA 엔진")
    parser.add_argument("--question", "-q", type=str, help="질문 텍스트")
    parser.add_argument("--interactive", "-i", action="store_true", help="대화형 인터랙티브 모드 실행")
    parser.add_argument("--verbose", "-v", action="store_true", help="생성된 SQL 및 상세 실행 로그 출력")
    args = parser.parse_args()

    if args.interactive:
        run_interactive()
    elif args.question:
        start_t = time.time()
        answer, results = answer_artgraph_question(args.question, verbose=args.verbose)
        elapsed = time.time() - start_t
        
        print("\n" + "=" * 60)
        print(f"질문: {args.question}")
        print("=" * 60 + "\n")
        print(answer)
        print("\n" + "-" * 60)
        print(f"[실행 정보] 소요 시간: {elapsed:.2f}초 | 실행된 SQL 쿼리 수: {len(results)}건")
        for i, r in enumerate(results, 1):
            print(f"  쿼리 {i} [{r['title']}]: {r['row_count']}건 결과")
            if args.verbose:
                print(f"    SQL: {r['sql']}")
        print("-" * 60)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
