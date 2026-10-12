import os, sys, time, json, requests
from dotenv import load_dotenv
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
load_dotenv(Path(__file__).parent / ".env")
gemini_key = os.environ.get("GEMINI_API_KEY", "")

prompt = """당신은 세계적인 미술사학자이자 도슨트입니다.
제공된 작가 목록에 대해 각각 미술사적으로 정확한 한국어 약력 정보를 작성해주세요.

[작성 지침]
1. bio: [한국어 작가 개요] 2~3문장으로 명확하고 유려하게 작성. 작가의 미술사적 의의, 주요 양식/기법적 특징, 대표적인 활동상을 포함.
2. movement: [주요 사조/유파] (예: 바로크, 인상주의, 입체파, 단색화, 팝아트 등). 명확하지 않거나 광범위할 경우 미술사적 분류 제시.
3. nationality_period: [국적 및 활동시기] (예: 플랑드르, 17세기 / 이탈리아, 르네상스 / 한국, 20세기 등).
4. 만약 이름이 'Rubens'나 'Titian'처럼 단축 표기된 경우, 미술사적 맥락(페테르 파울 루벤스, 티치아노 베첼리오 등)을 파악하여 정확히 서술.
5. 'China'나 'Italian'처럼 작가 개인이 아닌 국가/지역/학파로 등재된 경우, 해당 지역/시대의 공예 또는 미술 전통(예: 중국 전통 회화 및 공예, 이탈리아 화파)을 반영한 해설 제공.

[응답 포맷 (JSON Array)]
[
  {
    "id": "작가ID",
    "name": "입력된 작가명",
    "bio": "2~3문장 개요",
    "movement": "주요 사조",
    "nationality_period": "국적 및 활동시기"
  }
]

대상 작가:
1. id: "1", name: "Rubens", nationality: None, years: "None-None"
2. id: "2", name: "Titian", nationality: "Italian", years: "1490-1576"
3. id: "3", name: "Teniers", nationality: None, years: "None-None"
4. id: "4", name: "China", nationality: "Chinese", years: "None-None"
5. id: "5", name: "Dan Graham", nationality: "American", years: "1942-2022"
"""

url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-lite-latest:generateContent"
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
    timeout=20
)

print(resp.status_code)
if resp.status_code == 200:
    data = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
    parsed = json.loads(data)
    for item in parsed:
        print(f"\n[{item['name']}]")
        print(f"Movement: {item.get('movement')}")
        print(f"Nat/Period: {item.get('nationality_period')}")
        print(f"Bio: {item.get('bio')}")
        # Formatted bio:
        full_bio = f"{item.get('bio')}\n\n- **주요 사조**: {item.get('movement')}\n- **국적 및 활동시기**: {item.get('nationality_period')}"
        print(f"Full Bio:\n{full_bio}")
else:
    print(resp.text)
