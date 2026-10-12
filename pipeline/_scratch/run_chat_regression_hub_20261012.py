"""2026-10-12 작가 허브 부착 전후 chat 회귀 비교용 (20문항 + 허브 신규 3문항).
사용: python pipeline/_scratch/run_chat_regression_hub_20261012.py <label>   # label: before | after
출력: docs/logs/chat_회귀_20261012_<label>.json  (환경변수 ARTGRAPH_HUB=0이면 허브 비활성)
"""
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8")

from artgraph_chat import answer_artgraph_question
from run_chat_regression_20 import QUESTIONS as BASE

QUESTIONS = BASE + [
    "이우환의 1차 시장(전속 갤러리)과 2차 시장(경매) 현황을 비교해줘",
    "Jeff Wall은 어떤 미술관·갤러리·경매에서 확인돼?",
    "박서보의 소장처와 경매 낙찰가 분포를 알려줘",
]


def main():
    label = sys.argv[1]
    results = []
    for i, q in enumerate(QUESTIONS, start=1):
        t0 = time.time()
        try:
            answer, queries = answer_artgraph_question(q, verbose=False)
            err = None
        except Exception as exc:  # noqa: BLE001
            answer, queries, err = None, [], str(exc)
        short = re.sub(r"key=[^&\s\"']+", "key=***", err or "")[:160]
        print(f"[{i:02d}/{len(QUESTIONS)}] {round(time.time()-t0,1)}s err={short or False} — {q}", flush=True)
        results.append({
            "n": i, "question": q, "elapsed_sec": round(time.time() - t0, 2),
            "answer": answer, "error": err,
            "queries": [{"title": x.get("title"), "row_count": x.get("row_count"), "error": x.get("error")}
                        for x in queries],
        })
    out = Path(__file__).resolve().parent.parent.parent / "docs" / "logs" / f"chat_회귀_20261012_{label}.json"
    out.write_text(json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(), "label": label,
                               "questions": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("저장:", out)


if __name__ == "__main__":
    main()
