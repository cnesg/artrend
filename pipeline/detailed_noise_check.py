import sys

from db import get_connection

sys.stdout.reconfigure(encoding="utf-8")

conn = get_connection()
cur = conn.cursor()

print("--- Noise pattern check across all entity tables ---")

# 1. Artists
cur.execute("""
    SELECT count(*) FROM artists 
    WHERE name ~ '^#' 
       OR (name_en IS NOT NULL AND name_en ~ '^#')
       OR name ~ '^[0-9]{4}$'
       OR name ~ '^[0-9a-fA-F-]{32,}$'
       OR name ~ '^#agentOf'
       OR name ~ '^#Predmet'
       OR name ~ '^#134'
       OR name = '#NAME?'
""")
print("Dirty artists count:", cur.fetchone()[0])

# Check other potential dirty artists
cur.execute("""
    SELECT name, count(*) FROM artists 
    WHERE name ~ '^[^a-zA-Z가-힣\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\u00C0-\u024F]'
    GROUP BY name ORDER BY count(*) DESC LIMIT 30
""")
print("\nArtists starting with non-letter characters:")
for r in cur.fetchall():
    print(r)

# 2. Check references to dirty artists
cur.execute("""
    SELECT 
        (SELECT count(*) FROM artworks a JOIN artists ar ON a.artist_id = ar.id WHERE ar.name ~ '^#' OR ar.name ~ '^[0-9]{4}$'),
        (SELECT count(*) FROM gallery_representations gr JOIN artists ar ON gr.artist_id = ar.id WHERE ar.name ~ '^#' OR ar.name ~ '^[0-9]{4}$'),
        (SELECT count(*) FROM museum_holdings mh JOIN artworks a ON mh.artwork_id = a.id JOIN artists ar ON a.artist_id = ar.id WHERE ar.name ~ '^#' OR ar.name ~ '^[0-9]{4}$'),
        (SELECT count(*) FROM auction_lots al JOIN artworks a ON al.artwork_id = a.id JOIN artists ar ON a.artist_id = ar.id WHERE ar.name ~ '^#' OR ar.name ~ '^[0-9]{4}$')
""")
print("\nReferences to dirty artists (artworks, reps, holdings, auctions):", cur.fetchone())

# 3. Check Museums
cur.execute("""
    SELECT m.id, m.name, 
           (SELECT count(*) FROM museum_holdings mh WHERE mh.museum_id = m.id),
           (SELECT count(*) FROM provenance_records pr WHERE pr.owner_museum_id = m.id)
    FROM museums m
    WHERE m.name ~ '^[0-9]{4}\\s+(by|to)' OR m.name ~ '^#'
""")
print("\nDirty museums and references:")
for r in cur.fetchall():
    print(r)

# 4. Check Galleries
cur.execute("""
    SELECT g.id, g.name, 
           (SELECT count(*) FROM gallery_representations gr WHERE gr.gallery_id = g.id),
           (SELECT count(*) FROM provenance_records pr WHERE pr.owner_gallery_id = g.id)
    FROM galleries g
    WHERE g.name ~ '^[0-9]{4}\\s+(by|to)' OR g.name ~ '^#'
""")
print("\nDirty galleries and references:")
for r in cur.fetchall():
    print(r)

# 5. Check Auction Houses
cur.execute("""
    SELECT ah.id, ah.name,
           (SELECT count(*) FROM auctions au WHERE au.auction_house_id = ah.id),
           (SELECT count(*) FROM provenance_records pr WHERE pr.owner_auction_house_id = ah.id)
    FROM auction_houses ah
    WHERE ah.name ~ '^[0-9]{4}\\s+(by|to)' OR ah.name ~ '^#'
""")
print("\nDirty auction houses and references:")
for r in cur.fetchall():
    print(r)

# 6. Check Collectors
cur.execute("""
    SELECT count(*) FROM collectors
    WHERE name ~ '^[0-9]{4}\\s+(by|to)' OR name ~ '^#'
""")
print("\nDirty collectors count:", cur.fetchone()[0])
cur.execute("""
    SELECT count(*) FROM provenance_records pr
    JOIN collectors c ON pr.owner_collector_id = c.id
    WHERE c.name ~ '^[0-9]{4}\\s+(by|to)' OR c.name ~ '^#'
""")
print("Provenance records referencing dirty collectors:", cur.fetchone()[0])

conn.close()
