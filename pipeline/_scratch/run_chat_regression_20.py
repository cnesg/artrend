"""2026-09-17 메인 지시: chat 회귀 10→20문항 확대, docs/logs/chat_회귀_20260917.json.
일회성 실행 스크립트(_scratch 관례). 신규 10문항: 갤러리 전시 5곳·사건 데이터·
market_stats 연도별·entity_kind 제외·데이터 범위 고지 각 1개 이상 포함.
"""
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from artgraph_chat import answer_artgraph_question

QUESTIONS = [
    "이우환의 미술관 소장작과 경매 기록을 알려줘",
    "Rembrandt van Rijn 소장작 수와 경매 낙찰 상위 5건",
    "국립현대미술관에서 2025년에 열린 전시 목록",
    "2023년 한국 미술시장 경매 낙찰총액은?",
    "박서보가 받은 상은?",
    "Picasso 작품 중 귀속 한정(copy after 등) 없이 진작으로 기록된 소장작 수",
    "페이스갤러리 전속 작가 중 국립현대미술관 소장작이 있는 작가",
    "2020년 이후 사망한 한국 작가",
    "Bonhams에서 2021년에 낙찰된 최고가 작품",
    "1850~1999년 경매 기록이 왜 적은지",
    # --- 신규 10문항(2026-09-17) ---
    "글래드스톤 갤러리에서 열린 전시 목록을 알려줘",
    "리만머핀 갤러리 전속 작가들의 전시 이력",
    "타카 이시이 갤러리 도쿄 전시 목록",
    "표갤러리에서 전시한 작가 목록",
    "갤러리 시몬 전시 이력",
    "이우환의 전시 이력과 수상 경력을 알려줘",
    "2015~2024년 한국 미술시장 낙찰총액 연도별 추이",
    "2021년 market_stats_kr에 등록된 지표는 뭐가 있어?",
    "국립현대미술관 소장작 중 개인 작가(단체·재단·국가 명의 제외) 작품은 몇 건이야?",
    "요즘 한국 미술시장 트렌드가 어때?",
]


def main():
    results = []
    for i, q in enumerate(QUESTIONS, start=1):
        t0 = time.time()
        try:
            answer, queries = answer_artgraph_question(q, verbose=False)
            err = None
        except Exception as exc:  # noqa: BLE001
            answer, queries, err = None, [], str(exc)
        elapsed = round(time.time() - t0, 2)
        print(f"[{i:02d}/{len(QUESTIONS)}] {elapsed}s — {q}")
        results.append({
            "n": i,
            "question": q,
            "elapsed_sec": elapsed,
            "answer": answer,
            "queries": [
                {"title": qq.get("title"), "sql": qq.get("sql"), "row_count": qq.get("row_count"), "error": qq.get("error")}
                for qq in queries
            ],
            "error": err,
        })

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "note": "10→20문항 확대(메인 지시 20260917): 신규 11-20 갤러리5곳·사건데이터·market_stats연도별·entity_kind제외·데이터범위고지",
        "questions": results,
    }
    out_path = Path(__file__).resolve().parent.parent.parent / "docs" / "logs" / "chat_회귀_20260917.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"저장: {out_path}")


if __name__ == "__main__":
    main()
