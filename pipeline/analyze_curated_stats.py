import psycopg2

conn = psycopg2.connect("postgresql://postgres@127.0.0.1:5433/artrend")
cur = conn.cursor()

print("=== 1. 작가 (Artists) 선정 기준 분석 ===")
# 작가: 소장품 수 상위 + 갤러리 전속 or 경매 기록 보유 작가 (약 2,000~3,000명)
# Let's check how many artists have:
# A) museum holdings > 0
# B) gallery representation > 0
# C) auction lots > 0
# D) composite score / filter

cur.execute("""
    SELECT 
        count(*) as total_artists,
        count(*) FILTER (WHERE holding_cnt > 0) as with_holdings,
        count(*) FILTER (WHERE rep_cnt > 0) as with_reps,
        count(*) FILTER (WHERE auction_cnt > 0) as with_auctions,
        count(*) FILTER (WHERE holding_cnt > 0 AND (rep_cnt > 0 OR auction_cnt > 0)) as holdings_and_market,
        count(*) FILTER (WHERE holding_cnt >= 5 OR (rep_cnt > 0 AND (holding_cnt > 0 OR auction_cnt > 0)) OR auction_cnt >= 5) as curated_v1
    FROM (
        SELECT 
            ar.id,
            ar.name,
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
    ) t;
""")
row = cur.fetchone()
print(f"Total: {row[0]}, With Holdings: {row[1]}, With Reps: {row[2]}, With Auctions: {row[3]}, Holdings+Market: {row[4]}, Curated Candidate: {row[5]}")

print("\n=== 2. 미술관 (Museums) 분석 ===")
cur.execute("SELECT count(*) FROM museums")
print("Total museums in DB:", cur.fetchone()[0])
cur.execute("""
    SELECT m.id, m.name, count(mh.id) as holding_cnt
    FROM museums m
    LEFT JOIN museum_holdings mh ON mh.museum_id = m.id
    GROUP BY m.id, m.name
    ORDER BY holding_cnt DESC
    LIMIT 10
""")
for r in cur.fetchall():
    print(r)

cur.execute("""
    SELECT 
        count(*) FILTER (WHERE cnt > 0) as museums_with_holdings,
        count(*) FILTER (WHERE cnt >= 10) as museums_gte_10,
        count(*) FILTER (WHERE cnt >= 100) as museums_gte_100
    FROM (
        SELECT m.id, count(mh.id) as cnt
        FROM museums m
        LEFT JOIN museum_holdings mh ON mh.museum_id = m.id
        GROUP BY m.id
    ) t
""")
print("Museum counts by holdings:", cur.fetchone())

print("\n=== 3. 갤러리 및 경매사 분석 ===")
cur.execute("SELECT count(*) FROM galleries")
print("Total galleries:", cur.fetchone()[0])
cur.execute("""
    SELECT 
        count(*) FILTER (WHERE cnt > 0) as galleries_with_reps,
        count(*) FILTER (WHERE cnt >= 2) as galleries_gte_2,
        count(*) FILTER (WHERE cnt >= 5) as galleries_gte_5
    FROM (
        SELECT g.id, count(gr.id) as cnt
        FROM galleries g
        LEFT JOIN gallery_representations gr ON gr.gallery_id = g.id
        GROUP BY g.id
    ) t
""")
print("Galleries by representation count:", cur.fetchone())

cur.execute("SELECT count(*) FROM auction_houses")
print("Total auction houses:", cur.fetchone()[0])
cur.execute("""
    SELECT 
        count(*) FILTER (WHERE cnt > 0) as houses_with_auctions,
        count(*) FILTER (WHERE cnt >= 5) as houses_gte_5,
        count(*) FILTER (WHERE cnt >= 10) as houses_gte_10
    FROM (
        SELECT ah.id, count(au.id) as cnt
        FROM auction_houses ah
        LEFT JOIN auctions au ON au.auction_house_id = ah.id
        GROUP BY ah.id
    ) t
""")
print("Auction houses by auction count:", cur.fetchone())

print("\n=== 4. 컬렉터 분석 ===")
cur.execute("SELECT count(*) FROM collectors")
print("Total collectors:", cur.fetchone()[0])
cur.execute("""
    SELECT 
        count(*) FILTER (WHERE cnt >= 1) as collectors_gte_1,
        count(*) FILTER (WHERE cnt >= 2) as collectors_gte_2,
        count(*) FILTER (WHERE cnt >= 3) as collectors_gte_3,
        count(*) FILTER (WHERE cnt >= 5) as collectors_gte_5
    FROM (
        SELECT c.id, count(pr.id) as cnt
        FROM collectors c
        LEFT JOIN provenance_records pr ON pr.owner_collector_id = c.id
        GROUP BY c.id
    ) t
""")
print("Collectors by provenance count:", cur.fetchone())

conn.close()
