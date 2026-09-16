"""핵심 작가 2,500명 한국어 약력(Bio) & 사조(Movement) 초고속 보강 파이프라인.

기능:
1. DB(PostgreSQL)에서 엄선된 상위 2,500명 핵심 작가 선별 (build_curated_vault.py와 동일한 스코어링 로직).
2. 약력(bio)이 비어있는 대상 작가들을 추출 (기본: bio IS NULL or empty, 옵션: --mode no-korean / all).
3. Gemini Flash Lite 최신 모델을 활용하여 20~30개 병렬 워커(ThreadPoolExecutor)로 초고속 생성:
   - [한국어 작가 개요 (2~3문장)]
   - [주요 사조/유파 (예: 바로크, 인상주의, 입체파, 단색화, 팝아트 등)]
   - [국적 및 활동시기]
4. 정제된 바이오 텍스트를 artists.bio 컬럼에 일괄 UPDATE (execute_values 배치 커밋).
5. 1~2분 내 전수 보강 완료 및 상세 검증 보고서 출력.

사용법:
    # 빈 바이오 작가 보강 (기본: empty 모드, 약 1,494명)
    python pipeline/enrich_artist_bios.py

    # 10명만 테스트 (드라이런)
    python pipeline/enrich_artist_bios.py --limit 10 --dry-run

    # 한국어가 없는 작가 전체 보강
    python pipeline/enrich_artist_bios.py --mode no-korean
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg2
from psycopg2.extras import execute_values
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

CACHE_FILE = Path(__file__).resolve().parent / "cache_core_2500_artists.json"

# Gemini 모델 우선순위 (Flash Lite 최신 모델 및 폴백)
GEMINI_MODELS = [
    "gemini-flash-lite-latest",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-flash-latest",
]


def get_db_connection():
    """PostgreSQL 연결 생성 (UTF-8 인코딩)"""
    conn = psycopg2.connect(DATABASE_URL)
    conn.set_client_encoding("UTF8")
    return conn


def get_core_2500_artists(use_cache: bool = True) -> list[dict[str, Any]]:
    """build_curated_vault.py와 완전히 동일한 로직으로 핵심 작가 2,500명을 선별/로드"""
    if use_cache and CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                cached_data = json.load(f)
            if len(cached_data) == 2500:
                print(f"[선별] 캐시 파일({CACHE_FILE.name})에서 핵심 작가 2,500명 즉시 로드 완료.")
                return cached_data
        except Exception as e:
            print(f"[선별] 캐시 로드 실패 ({e}), DB에서 재집계합니다.")

    print("[선별] DB에서 핵심 작가 2,500명 스코어링 및 선별 쿼리 실행 중 (약 30초 소요)...")
    t0 = time.time()
    conn = get_db_connection()
    cur = conn.cursor()

    # 1. Holdings count
    print("  - 미술관 소장품 수 집계 중...")
    cur.execute("""
        SELECT a.artist_id, count(mh.id) 
        FROM museum_holdings mh 
        JOIN artworks a ON a.id = mh.artwork_id 
        WHERE a.artist_id IS NOT NULL 
        GROUP BY a.artist_id
    """)
    artist_holdings_count = {str(r[0]): r[1] for r in cur.fetchall()}

    # 2. Representations count
    print("  - 갤러리 전속/대표 관계 집계 중...")
    cur.execute("""
        SELECT artist_id, count(gallery_id) 
        FROM gallery_representations 
        GROUP BY artist_id
    """)
    artist_reps_count = {str(r[0]): r[1] for r in cur.fetchall()}

    # 3. Market metrics
    # 2026-09-15 §W2: artist_market_metrics는 db/migrations/0004에서 DROP됨
    # (가짜 시장지표 — 역사 통화 임의 환율 기반). 테이블이 없으면 빈 dict로 폴백.
    print("  - 경매 시장 지표 로드 중...")
    artist_market_map = {}
    try:
        cur.execute("""
            SELECT artist_id, total_lots_offered, record_price_usd
            FROM artist_market_metrics;
        """)
        artist_market_map = {
            str(r[0]): {"offered": r[1], "record_usd": float(r[2] or 0)}
            for r in cur.fetchall()
        }
    except Exception:
        conn.rollback()
        print("  [경고] artist_market_metrics 테이블 없음 — 시장 지표 없이 진행")

    # 4. Candidates query with noise filtering
    print("  - 작가 노이즈 필터링 및 후보 작가 로드 중...")
    cur.execute("""
        SELECT id, name, name_en, birth_year, death_year, nationality, bio
        FROM artists
        WHERE name NOT ILIKE '%anoniem%' 
          AND name NOT ILIKE '%unknown%' 
          AND name NOT ILIKE '%anonymous%' 
          AND name NOT ILIKE '%unidentified%' 
          AND name NOT ILIKE '%unbekannt%' 
          AND name NOT ILIKE '%anonyme%' 
          AND name NOT ILIKE '%maker%' 
          AND name NOT ILIKE '%various%'
          AND name NOT ILIKE '%photographer%'
          AND name NOT ILIKE '%unbek%'
          AND name NOT ILIKE '%Jahrhundert%'
          AND name NOT ILIKE '%Century%'
          AND name NOT ILIKE '%School of%'
          AND name NOT ILIKE '%Follower of%'
          AND name NOT ILIKE '%Circle of%'
          AND name NOT ILIKE '%Manner of%'
          AND name NOT ILIKE '%After %'
          AND name NOT ILIKE '%Style of%'
          AND name NOT ILIKE '%Workshop of%'
          AND length(trim(name)) >= 2
    """)
    candidates = cur.fetchall()

    scored_artists = []
    for r in candidates:
        a_id = str(r[0])
        h_cnt = artist_holdings_count.get(a_id, 0)
        r_cnt = artist_reps_count.get(a_id, 0)
        m_info = artist_market_map.get(a_id, {})
        a_cnt = m_info.get("offered", 0)
        record_usd = m_info.get("record_usd", 0)

        if h_cnt == 0 and r_cnt == 0 and a_cnt == 0:
            continue

        score = (r_cnt * 100.0) + (a_cnt * 3.0) + (h_cnt * 1.0)
        if record_usd >= 1_000_000:
            score += 200.0
        elif record_usd >= 100_000:
            score += 50.0

        if (h_cnt > 0 and (r_cnt > 0 or a_cnt > 0)) or h_cnt >= 10 or r_cnt >= 1 or a_cnt >= 10 or record_usd >= 100_000:
            scored_artists.append({
                "id": a_id,
                "name": r[1],
                "name_en": r[2],
                "birth_year": r[3],
                "death_year": r[4],
                "nationality": r[5],
                "score": score,
                "holdings_count": h_cnt,
                "reps_count": r_cnt,
                "auction_count": a_cnt,
            })

    scored_artists.sort(key=lambda x: x["score"], reverse=True)
    selected = scored_artists[:2500]

    cur.close()
    conn.close()

    elapsed = time.time() - t0
    print(f"[선별] 핵심 작가 2,500명 선별 완료 ({elapsed:.1f}초). 캐시 파일에 저장합니다.")
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(selected, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[선별] 캐시 저장 실패: {e}")

    return selected


def fetch_current_bios(artist_ids: list[str]) -> dict[str, str | None]:
    """DB에서 지정된 작가들의 최신 bio 값을 조회"""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, bio FROM artists WHERE id = ANY(%s::uuid[])",
        (artist_ids,)
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return {str(r[0]): r[1] for r in rows}


def filter_target_artists(
    all_artists: list[dict[str, Any]],
    current_bios: dict[str, str | None],
    mode: str = "empty",
) -> list[dict[str, Any]]:
    """모드에 따라 보강 대상 작가 필터링
    - empty: bio가 NULL이거나 공백인 작가
    - no-korean: bio가 비어있거나 한국어가 한 글자도 없는 작가
    - all: 2,500명 전원
    """
    targets = []
    korean_regex = re.compile(r"[\uac00-\ud7a3]")

    for a in all_artists:
        bio = current_bios.get(a["id"])
        is_empty = not bio or len(bio.strip()) == 0

        if mode == "empty":
            if is_empty:
                targets.append(a)
        elif mode == "no-korean":
            if is_empty or not korean_regex.search(bio):
                targets.append(a)
        elif mode == "all":
            targets.append(a)

    return targets


SYSTEM_PROMPT = """당신은 세계적인 국립미술관의 수석 큐레이터이자 미술사학자입니다.
제공된 작가 목록에 대해 각 작가의 핵심 미술사 정보를 정확하고 깊이 있게 한국어로 작성해주세요.

[필수 작성 규칙]
1. bio: 작가의 미술사적 의의, 대표적 조형 양식 및 매체/기법적 특징, 주요 활동상을 압축한 [한국어 작가 개요]를 정확히 2~3문장의 완성도 높은 문장으로 서술하세요.
2. movement: [주요 사조/유파]를 명확히 기재하세요 (예: 르네상스, 바로크, 인상주의, 입체파, 단색화, 추상표현주의, 팝아트, 개념미술, 미니멀리즘 등).
3. nationality_period: [국적 및 활동시기]를 간결하고 표준적으로 기재하세요 (예: 프랑스, 19세기 후반 / 이탈리아, 16세기 / 한국, 20세기 중후반 등).
4. 입력된 작가명이 약칭(예: 'Rubens', 'Titian', 'Teniers', 'Callot')이거나 미술관 데이터셋 상 단축 표기된 경우, 미술사적 실체(페테르 파울 루벤스, 티치아노 베첼리오, 다비드 테니르스 2세, 자크 칼로 등)를 정확히 파악하여 충실히 서술하세요.
5. 'China'나 'Italian' 등 국가/지역/공방명으로 등재된 개체인 경우, 해당 지역 및 시대의 전통 미술·공예(예: 중국 전통 회화 및 도자, 이탈리아 화파)의 특성을 반영하여 전문적으로 기술하세요.

[반드시 준수할 출력 포맷: JSON Array]
[
  {
    "id": "입력받은 작가 ID",
    "name": "작가명",
    "bio": "한국어 작가 개요 2~3문장",
    "movement": "주요 사조/유파",
    "nationality_period": "국적 및 활동시기"
  }
]
"""


def generate_batch_bios(
    batch: list[dict[str, Any]],
    max_retries: int = 4
) -> list[tuple[str, str]]:
    """단일 배치의 작가들에 대해 Gemini API 호출 및 (artist_id, formatted_bio) 튜플 목록 반환"""
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY가 없습니다. pipeline/.env를 확인하세요.")

    # 프롬프트 입력 생성
    input_items = []
    for a in batch:
        item = {
            "id": a["id"],
            "name": a["name"],
            "name_en": a.get("name_en") or None,
            "nationality": a.get("nationality") or None,
            "years": f"{a.get('birth_year') or ''}-{a.get('death_year') or ''}".strip("-") or None
        }
        input_items.append(item)

    user_prompt = f"다음 작가 {len(input_items)}명에 대해 요청한 지침대로 JSON Array를 작성해주세요:\n{json.dumps(input_items, ensure_ascii=False, indent=2)}"

    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": f"{SYSTEM_PROMPT}\n\n---\n\n{user_prompt}"}]
            }
        ],
        "generationConfig": {
            "temperature": 0.2,
            "responseMimeType": "application/json"
        }
    }

    last_error = None
    for model_name in GEMINI_MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"

        for attempt in range(max_retries):
            try:
                resp = requests.post(
                    url,
                    params={"key": GEMINI_API_KEY},
                    json=payload,
                    timeout=35
                )

                if resp.status_code == 200:
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if candidates and "content" in candidates[0]:
                        parts = candidates[0]["content"].get("parts", [])
                        if parts and "text" in parts[0]:
                            raw_text = parts[0]["text"].strip()
                            parsed_list = []
                            try:
                                parsed_list = json.loads(raw_text)
                            except Exception:
                                # 1. Extract bracketed array
                                m = re.search(r'\[\s*\{.*\}\s*\]', raw_text, re.DOTALL)
                                if m:
                                    try:
                                        parsed_list = json.loads(m.group(0))
                                    except Exception:
                                        pass
                                # 2. Extract individual JSON objects
                                if not parsed_list:
                                    objs = re.findall(r'\{[^{}]*"id"[^{}]*\}', raw_text)
                                    for obj_str in objs:
                                        try:
                                            parsed_list.append(json.loads(obj_str))
                                        except Exception:
                                            pass

                            if not isinstance(parsed_list, list):
                                parsed_list = [parsed_list]

                            # 파싱 결과 가공
                            results = []
                            for item in parsed_list:
                                if not isinstance(item, dict):
                                    continue
                                aid = str(item.get("id", "")).strip()
                                bio_text = str(item.get("bio", "")).strip()
                                movement = str(item.get("movement", "")).strip()
                                nat_period = str(item.get("nationality_period", "")).strip()

                                if not aid or not bio_text:
                                    continue

                                # 최종 artists.bio 형식 구성
                                full_bio = f"{bio_text}\n\n- **주요 사조**: {movement}\n- **국적 및 활동시기**: {nat_period}"
                                results.append((aid, full_bio))

                            if len(results) > 0:
                                return results

                elif resp.status_code in (429, 500, 503):
                    # Rate limit or server error: backoff
                    sleep_time = (2.0 ** attempt) + random.uniform(0.2, 0.8)
                    time.sleep(sleep_time)
                    continue
                elif resp.status_code == 404:
                    # Model deprecated/not found: break and try next model
                    break
                else:
                    last_error = RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
                    break

            except Exception as e:
                last_error = e
                time.sleep((1.5 ** attempt) + random.uniform(0.1, 0.5))

    # 모든 재시도 실패 시 빈 목록 반환 (전체 파이프라인 중단 방지)
    print(f"\n[경고] 배치 {len(batch)}명 처리 실패: {last_error}")
    return []


def update_bios_in_db(batch_results: list[tuple[str, str]]) -> int:
    """DB의 artists.bio 컬럼에 일괄 UPDATE (execute_values)"""
    if not batch_results:
        return 0

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        execute_values(
            cur,
            """
            UPDATE artists AS a
            SET bio = v.bio
            FROM (VALUES %s) AS v(id, bio)
            WHERE a.id = v.id::uuid;
            """,
            batch_results,
            template="(%s::uuid, %s)"
        )
        conn.commit()
        return len(batch_results)
    except Exception as e:
        conn.rollback()
        print(f"[DB 에러] UPDATE 실패: {e}")
        return 0
    finally:
        cur.close()
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="핵심 작가 2,500명 한국어 약력 & 사조 초고속 보강")
    parser.add_argument("--workers", type=int, default=25, help="병렬 워커 수 (기본 25)")
    parser.add_argument("--batch-size", type=int, default=10, help="API 요청당 작가 수 (기본 10)")
    parser.add_argument("--mode", choices=["empty", "no-korean", "all"], default="empty",
                        help="대상 모드: empty(비어있는 약력, 기본), no-korean(한국어 부재), all(2500명 전원)")
    parser.add_argument("--limit", type=int, default=0, help="처리 건수 제한 (테스트용)")
    parser.add_argument("--dry-run", action="store_true", help="DB 실제 UPDATE 건너뜀")
    parser.add_argument("--no-cache", action="store_true", help="핵심 2500명 선별 캐시 무시하고 재집계")
    args = parser.parse_args()

    print("=" * 70)
    print("🎨 [ArtGraph] 핵심 작가 2,500명 한국어 약력(Bio) & 사조(Movement) 보강 파이프라인")
    print("=" * 70)
    print(f"  - DB URL: {DATABASE_URL}")
    print(f"  - 병렬 워커: {args.workers}개")
    print(f"  - 배치 크기: 요청당 {args.batch_size}명")
    print(f"  - 보강 모드: {args.mode}")
    print(f"  - Dry-run: {args.dry_run}")
    print(f"  - 시작 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("-" * 70)

    # 1. 핵심 작가 2,500명 로드
    all_core = get_core_2500_artists(use_cache=not args.no_cache)
    print(f"[진행] 로드된 핵심 작가 수: {len(all_core):,}명")

    # 2. 최신 DB bio 현황 조회
    all_ids = [a["id"] for a in all_core]
    current_bios = fetch_current_bios(all_ids)

    # 3. 대상 작가 필터링
    target_artists = filter_target_artists(all_core, current_bios, mode=args.mode)
    if args.limit > 0:
        target_artists = target_artists[:args.limit]

    print(f"[대상] 총 {len(target_artists):,}명의 작가가 보강 대상으로 선정되었습니다.")
    if len(target_artists) == 0:
        print("[완료] 보강 대상 작가가 없습니다. 모든 작가의 약력이 이미 채워져 있습니다.")
        return

    # 4. 배치 분할
    batches = []
    for i in range(0, len(target_artists), args.batch_size):
        batches.append(target_artists[i : i + args.batch_size])

    total_batches = len(batches)
    print(f"[배치] 총 {total_batches:,}개 배치 (배치당 {args.batch_size}명)를 {args.workers}개 워커로 가동합니다.")

    # 5. 병렬 실행 및 DB UPDATE
    t_start = time.time()
    completed_batches = 0
    total_updated_artists = 0
    sample_bios: list[dict[str, str]] = []

    print("\n[가동] Gemini Flash Lite 멀티스레드 병렬 생성 시작...")

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        future_to_batch = {
            executor.submit(generate_batch_bios, b): b for b in batches
        }

        for future in concurrent.futures.as_completed(future_to_batch):
            batch = future_to_batch[future]
            try:
                results = future.result()
                if results:
                    if not args.dry_run:
                        updated_cnt = update_bios_in_db(results)
                        total_updated_artists += updated_cnt
                    else:
                        total_updated_artists += len(results)

                    # 샘플 수집 (최대 10개)
                    if len(sample_bios) < 10:
                        for aid, bio in results:
                            # 작가 이름 매칭
                            aname = next((x["name"] for x in batch if x["id"] == aid), aid)
                            sample_bios.append({"id": aid, "name": aname, "bio": bio})
                            if len(sample_bios) >= 10:
                                break

                completed_batches += 1
                elapsed = time.time() - t_start
                rate = total_updated_artists / elapsed if elapsed > 0 else 0
                pct = (completed_batches / total_batches) * 100
                eta = (total_batches - completed_batches) * (elapsed / completed_batches) if completed_batches > 0 else 0

                sys.stdout.write(
                    f"\r  -> [{completed_batches:3d}/{total_batches:3d}] ({pct:5.1f}%) | "
                    f"완료: {total_updated_artists:4d}명 | "
                    f"속도: {rate:4.1f} 작가/초 | "
                    f"경과: {elapsed:4.1f}s | 남은시간: {eta:4.1f}s"
                )
                sys.stdout.flush()

            except Exception as e:
                print(f"\n[오류] 배치 실행 중 예외 발생: {e}")

    total_elapsed = time.time() - t_start
    print("\n" + "=" * 70)
    print(f"✨ [보강 완료] 총 {total_updated_artists:,}명 작가 약력 & 사조 보강 완료!")
    print(f"  - 총 소요 시간: {total_elapsed:.2f}초 ({total_elapsed / 60:.2f}분)")
    print(f"  - 평균 처리 속도: {total_updated_artists / total_elapsed:.2f} 작가/초")
    print("=" * 70)

    # 6. 샘플 결과 출력
    print("\n🔍 [보강된 작가 약력 샘플 (Sample Bios)]:")
    for idx, s in enumerate(sample_bios[:5], 1):
        print(f"\n--- [샘플 {idx}] {s['name']} (ID: {s['id']}) ---")
        print(s["bio"])

    # 7. DB 최종 검증
    if not args.dry_run:
        print("\n📊 [DB 최종 검증 현황]")
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT count(*) FROM artists WHERE id = ANY(%s::uuid[]) AND bio IS NOT NULL AND length(trim(bio)) > 0",
            (all_ids,)
        )
        filled_cnt = cur.fetchone()[0]
        cur.execute(
            "SELECT count(*) FROM artists WHERE id = ANY(%s::uuid[]) AND bio ~ '[\uac00-\ud7a3]'",
            (all_ids,)
        )
        korean_cnt = cur.fetchone()[0]
        cur.close()
        conn.close()

        print(f"  - 핵심 작가 2,500명 중 약력(bio) 보유: {filled_cnt:,} / 2,500명 ({(filled_cnt / 2500) * 100:.1f}%)")
        print(f"  - 핵심 작가 2,500명 중 한국어 약력 보유: {korean_cnt:,} / 2,500명 ({(korean_cnt / 2500) * 100:.1f}%)")
    print("=" * 70)


if __name__ == "__main__":
    main()
