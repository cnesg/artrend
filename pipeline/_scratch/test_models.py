import os
import sys
import time
from pathlib import Path
from dotenv import load_dotenv
import requests

sys.stdout.reconfigure(encoding="utf-8")
load_dotenv(Path(__file__).parent / ".env")
gemini_key = os.environ.get("GEMINI_API_KEY", "")

models = ["gemini-flash-lite-latest", "gemini-3.1-flash-lite", "gemini-3.5-flash-lite", "gemini-flash-latest", "gemini-3.6-flash"]

prompt = """다음 작가 3명에 대해 각각 [한국어 작가 개요 (2~3문장)], [주요 사조/유파 (예: 인상주의, 입체파, 단색화 등)], [국적 및 활동시기]를 아래 JSON 형식으로 작성해줘:
[
  {
    "name": "Rubens",
    "bio": "페테르 파울 루벤스는 17세기 바로크 미술의 대표적인 거장으로...",
    "movement": "바로크",
    "nationality_period": "플랑드르, 17세기"
  }
]
대상 작가:
1. Rubens (생몰년 미상)
2. Callot, Jacques (1592-1635, 국적: French)
3. Titian (1490-1576, 국적: Italian)
"""

for model in models:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    try:
        t0 = time.time()
        resp = requests.post(
            url,
            params={"key": gemini_key},
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.2,
                    "responseMimeType": "application/json"
                }
            },
            timeout=25
        )
        elapsed = time.time() - t0
        if resp.status_code == 200:
            txt = resp.json()['candidates'][0]['content']['parts'][0]['text'].strip()
            print(f"Model {model} ({elapsed:.2f}s): SUCCESS ->\n{txt[:250]}...\n")
        else:
            print(f"Model {model} ({elapsed:.2f}s): {resp.status_code} -> {resp.text[:120]}")
    except Exception as e:
        print(f"Model {model}: EXCEPTION -> {e}")
