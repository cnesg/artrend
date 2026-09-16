import os, sys, time, json, requests
from dotenv import load_dotenv
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
load_dotenv(Path(__file__).parent / ".env")
gemini_key = os.environ.get("GEMINI_API_KEY", "")

artists = [
    {"id": "1", "name": "Jacques Callot", "nationality": "French", "years": "1592-1635"},
    {"id": "2", "name": "Paul Gavarni", "nationality": "French", "years": "1804-1866"},
    {"id": "3", "name": "Niels Larsen Stevns", "nationality": "Dansk", "years": "1864-1941"},
    {"id": "4", "name": "Rembrandt", "nationality": "Dutch", "years": "1606-1669"},
    {"id": "5", "name": "Carven", "nationality": None, "years": "None-None"},
    {"id": "6", "name": "Honoré Daumier", "nationality": "French", "years": "1808-1879"},
    {"id": "7", "name": "Walker Evans", "nationality": "American", "years": "1903-1975"},
    {"id": "8", "name": "Robert Frank", "nationality": "American", "years": "1924-2019"},
    {"id": "9", "name": "Agnes Martin", "nationality": "American", "years": "1912-2004"},
    {"id": "10", "name": "Adrian Ghenie", "nationality": "Romanian", "years": "1977-None"},
]

prompt = f"""당신은 세계적인 미술사학자이자 국립미술관 수석 큐레이터입니다.
아래 제공된 미술 작가 10명에 대해 각각 전문적이고 유려한 한국어 약력(Bio) 및 미술사적 정보를 작성해주세요.

[작성 원칙]
1. bio: 작가의 미술사적 중요도, 대표적 양식 및 기법적 특징, 주요 활동상을 압축한 [한국어 작가 개요] 2~3문장.
2. movement: [주요 사조/유파] (예: 바로크, 인상주의, 단색화, 추상표현주의, 팝아트 등).
3. nationality_period: [국적 및 활동시기] (예: 프랑스, 17세기 / 미국, 20세기 중후반 등).
4. 만약 약칭이거나 생몰년이 비어있어도 미술사적 실체를 정확히 복원하여 충실히 서술할 것.

[출력 형식: 순수 JSON Array]
[
  {{
    "id": "작가 ID",
    "name": "작가명",
    "bio": "한국어 개요 2~3문장",
    "movement": "주요 사조/유파",
    "nationality_period": "국적 및 활동시기"
  }}
]

대상 작가 목록:
{json.dumps(artists, ensure_ascii=False, indent=2)}
"""

url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-lite-latest:generateContent"
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
    timeout=30
)
elapsed = time.time() - t0
print(f"Status: {resp.status_code}, Elapsed: {elapsed:.2f}s")
if resp.status_code == 200:
    items = json.loads(resp.json()["candidates"][0]["content"]["parts"][0]["text"])
    print(f"Received {len(items)} items:")
    for it in items[:3]:
        print(f"- {it['name']}: {it['movement']} | {it['nationality_period']}")
        print(f"  {it['bio']}")
else:
    print(resp.text)
