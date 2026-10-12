import os, sys, psycopg2
from dotenv import load_dotenv
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
load_dotenv(Path(__file__).parent / ".env")

conn = psycopg2.connect(os.environ["DATABASE_URL"])
conn.set_client_encoding("UTF8")
cur = conn.cursor()

# Get curated 2500
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
    SELECT artist_id, total_lots_offered, record_price_usd
    FROM artist_market_metrics;
""")
artist_market_map = {}
for r in cur.fetchall():
    artist_market_map[str(r[0])] = {
        "offered": r[1],
        "record_usd": float(r[2] or 0),
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
        scored_artists.append((r, score))

scored_artists.sort(key=lambda x: x[1], reverse=True)
selected_artists = scored_artists[:2500]

has_bio = [x[0] for x in selected_artists if x[0][6] and len(x[0][6].strip()) > 0]
empty_bio = [x[0] for x in selected_artists if not x[0][6] or len(x[0][6].strip()) == 0]

print(f"Top 2500: has_bio={len(has_bio)}, empty_bio={len(empty_bio)}")
print("\n--- 10 random existing bios from top 2500 ---")
import random
random.seed(42)
for a in random.sample(has_bio, 10):
    print(f"[{a[1]}] (nat={a[5]}, y={a[3]}-{a[4]}): {a[6]}")

cur.close()
conn.close()
