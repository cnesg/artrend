"""
Curated Vault Data Fetchers & Builders
"""
import sys
import psycopg2

sys.stdout.reconfigure(encoding="utf-8")

conn = psycopg2.connect("postgresql://postgres@127.0.0.1:5433/artrend")
cur = conn.cursor()

print("Testing Curated Selection Queries...")

# 1. Top Artists query
# Curated target: 2,500 artists
cur.execute("""
    WITH artist_metrics AS (
        SELECT 
            ar.id,
            ar.name,
            ar.name_en,
            ar.birth_year,
            ar.death_year,
            ar.nationality,
            ar.bio,
            COALESCE(h.cnt, 0) as holding_cnt,
            COALESCE(r.cnt, 0) as rep_cnt,
            COALESCE(a.cnt, 0) as auction_cnt
        FROM artists ar
        LEFT JOIN (
            SELECT a.artist_id, count(*) as cnt 
            FROM museum_holdings mh 
            JOIN artworks a ON a.id = mh.artwork_id 
            WHERE a.artist_id IS NOT NULL 
            GROUP BY a.artist_id
        ) h ON h.artist_id = ar.id
        LEFT JOIN (
            SELECT artist_id, count(*) as cnt 
            FROM gallery_representations 
            GROUP BY artist_id
        ) r ON r.artist_id = ar.id
        LEFT JOIN (
            SELECT a.artist_id, count(*) as cnt 
            FROM auction_lots al 
            JOIN artworks a ON a.id = al.artwork_id 
            WHERE a.artist_id IS NOT NULL 
            GROUP BY a.artist_id
        ) a ON a.artist_id = ar.id
        WHERE (COALESCE(h.cnt, 0) > 0 AND (COALESCE(r.cnt, 0) > 0 OR COALESCE(a.cnt, 0) > 0))
           OR (COALESCE(h.cnt, 0) >= 10)
           OR (COALESCE(r.cnt, 0) >= 2)
           OR (COALESCE(a.cnt, 0) >= 20)
    )
    SELECT id, name, name_en, birth_year, death_year, nationality, bio,
           holding_cnt, rep_cnt, auction_cnt,
           (holding_cnt + rep_cnt * 50 + auction_cnt * 2) as score
    FROM artist_metrics
    ORDER BY score DESC
    LIMIT 2500;
""")
top_artists = cur.fetchall()
print(f"Top Artists Selected: {len(top_artists)}")
for a in top_artists[:5]:
    print(a[1], f"(holdings={a[7]}, reps={a[8]}, auctions={a[9]}, score={a[10]})")

# 2. Top Museums
cur.execute("""
    SELECT m.id, m.name, m.name_en, m.country, m.city, m.type, m.website,
           count(mh.id) as holding_cnt
    FROM museums m
    LEFT JOIN museum_holdings mh ON mh.museum_id = m.id
    GROUP BY m.id, m.name, m.name_en, m.country, m.city, m.type, m.website
    ORDER BY holding_cnt DESC
    LIMIT 400;
""")
top_museums = cur.fetchall()
print(f"\nTop Museums Selected: {len(top_museums)}")
for m in top_museums[:5]:
    print(m[1], f"(holdings={m[7]})")

# 3. Top Galleries
cur.execute("""
    SELECT g.id, g.name, g.city, g.country, g.website,
           count(gr.id) as rep_cnt
    FROM galleries g
    LEFT JOIN gallery_representations gr ON gr.gallery_id = g.id
    GROUP BY g.id, g.name, g.city, g.country, g.website
    ORDER BY rep_cnt DESC, g.name
    LIMIT 250;
""")
top_galleries = cur.fetchall()
print(f"\nTop Galleries Selected: {len(top_galleries)}")
for g in top_galleries[:5]:
    print(g[1], f"(reps={g[5]})")

# 4. Top Auction Houses
cur.execute("""
    SELECT ah.id, ah.name, ah.city, ah.country, ah.website,
           count(DISTINCT au.id) as auction_cnt,
           count(al.id) as lot_cnt
    FROM auction_houses ah
    LEFT JOIN auctions au ON au.auction_house_id = ah.id
    LEFT JOIN auction_lots al ON al.auction_id = au.id
    GROUP BY ah.id, ah.name, ah.city, ah.country, ah.website
    ORDER BY lot_cnt DESC, auction_cnt DESC
    LIMIT 250;
""")
top_houses = cur.fetchall()
print(f"\nTop Auction Houses Selected: {len(top_houses)}")
for h in top_houses[:5]:
    print(h[1], f"(auctions={h[5]}, lots={h[6]})")

# 5. Top Collectors
cur.execute("""
    SELECT c.id, c.name, c.bio, count(pr.id) as prov_cnt
    FROM collectors c
    JOIN provenance_records pr ON pr.owner_collector_id = c.id
    GROUP BY c.id, c.name, c.bio
    HAVING count(pr.id) >= 3
    ORDER BY prov_cnt DESC
    LIMIT 500;
""")
top_collectors = cur.fetchall()
print(f"\nTop Collectors Selected: {len(top_collectors)}")
for c in top_collectors[:5]:
    print(c[1], f"(provenances={c[3]})")

conn.close()
print("\nTotal Curated Entities:", len(top_artists) + len(top_museums) + len(top_galleries) + len(top_houses) + len(top_collectors))
