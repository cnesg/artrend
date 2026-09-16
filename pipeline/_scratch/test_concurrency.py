import os, time, requests, concurrent.futures
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")
key = os.environ.get("GEMINI_API_KEY", "")

def test_call(i):
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-lite-latest:generateContent"
    t0 = time.time()
    resp = requests.post(
        url,
        params={"key": key},
        json={"contents": [{"parts": [{"text": f"Reply with the number {i} only."}]}]},
        timeout=15
    )
    return i, resp.status_code, time.time() - t0

t_start = time.time()
with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
    futs = [ex.submit(test_call, i) for i in range(5)]
    results = [f.result() for f in concurrent.futures.as_completed(futs)]

print(f"Total time: {time.time() - t_start:.2f}s")
for r in sorted(results):
    print(f"Call {r[0]}: status={r[1]}, elapsed={r[2]:.2f}s")
