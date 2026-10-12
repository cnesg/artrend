import os
import sys
import time
import psycopg2
from pathlib import Path
from dotenv import load_dotenv
import requests

load_dotenv(Path(__file__).parent / ".env")

db_url = os.environ.get("DATABASE_URL", "postgresql://postgres@127.0.0.1:5433/artrend")
gemini_key = os.environ.get("GEMINI_API_KEY", "")

print("Testing DB connection...")
conn = psycopg2.connect(db_url)
conn.set_client_encoding("UTF8")
cur = conn.cursor()

# Get the scoring logic matching build_curated_vault.py
cur.execute("""
    SELECT a.artist_id, count(mh.id) 
    FROM museum_holdings mh 
    JOIN artworks a ON a.id = mh.artwork_id 
    WHERE a.artist_id IS NOT NULL 
    GROUP BY a.artist_id
""")
artist_holdings_count = {str(r[0]): r[1] for r in cur.fetchall()}

cur.execute("""
    SELECT artist_id, count(gallery_id) 
    FROM gallery_representations 
    GROUP BY artist_id
""")
artist_reps_count = {str(r[0]): r[1] for r in cur.fetchall()}

cur.execute("""
    SELECT 
        artist_id, 
        total_lots_offered, 
        total_lots_sold, 
        sold_rate_pct, 
        total_turnover_usd, 
        avg_price_usd, 
        record_price_usd
    FROM artist_market_metrics;
""")
artist_market_map = {}
for r in cur.fetchall():
    artist_market_map[str(r[0])] = {
        "offered": r[1],
        "sold": r[2],
        "sold_rate": float(r[3] or 0),
        "turnover_usd": float(r[4] or 0),
        "avg_price_usd": float(r[5] or 0),
        "record_usd": float(r[6] or 0),
    }

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
candidate_artists = cur.fetchall()

scored_artists = []
for r in candidate_artists:
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
        scored_artists.append((r, h_cnt, r_cnt, a_cnt, score, m_info))

scored_artists.sort(key=lambda x: x[4], reverse=True)
selected_artists = scored_artists[:2500]

sys.stdout.reconfigure(encoding="utf-8")

print(f"Total candidate scored: {len(scored_artists)}, Selected: {len(selected_artists)}")

has_bio = [x for x in selected_artists if x[0][6] and len(x[0][6].strip()) > 0]
empty_bio = [x for x in selected_artists if not x[0][6] or len(x[0][6].strip()) == 0]

print(f"Among top 2500: {len(has_bio)} have bio, {len(empty_bio)} have empty bio.")

if has_bio:
    print("\nSample existing bios (first 5):")
    for sample in has_bio[:5]:
        print(f"Artist: {sample[0][1]} ({sample[0][2]})")
        print(f"Bio: {repr(sample[0][6][:150])}")

print("\nSample empty bio artists (first 10):")
for x in empty_bio[:10]:
    print(f"- {x[0][1]} ({x[0][2]}), nat: {x[0][5]}, years: {x[0][3]}-{x[0][4]}")

print("\nTesting Gemini API models...")
for model in ["gemini-flash-lite-latest", "gemini-3.1-flash-lite", "gemini-3.5-flash-lite", "gemini-flash-latest"]:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    try:
        t0 = time.time()
        resp = requests.post(
            url,
            params={"key": gemini_key},
            json={
                "contents": [{"parts": [{"text": "Hello, respond in 1 sentence in Korean."}]}]
            },
            timeout=20
        )
        elapsed = time.time() - t0
        if resp.status_code == 200:
            txt = resp.json()['candidates'][0]['content']['parts'][0]['text'].strip()
            print(f"Model {model} ({elapsed:.2f}s): SUCCESS -> {txt}")
        else:
            print(f"Model {model} ({elapsed:.2f}s): {resp.status_code} -> {resp.text[:100]}")
    except Exception as e:
        print(f"Model {model}: EXCEPTION -> {e}")

cur.close()
conn.close()
