import sys
import psycopg2

sys.stdout.reconfigure(encoding="utf-8")

conn = psycopg2.connect("postgresql://postgres@127.0.0.1:5433/artrend")
cur = conn.cursor()

print("=== ARTISTS NOISE CHECK ===")
cur.execute("SELECT count(*) FROM artists WHERE name LIKE '#%' OR name_en LIKE '#%'")
print("Artists starting with #: ", cur.fetchone()[0])

cur.execute("SELECT id, name, name_en FROM artists WHERE name LIKE '#%' OR name_en LIKE '#%' LIMIT 20")
for r in cur.fetchall():
    print(r)

print("\n=== Other suspicious artist patterns ===")
# Check for UUID-like, #agentOf, #NAME?, empty/blank, or pure numbers
cur.execute("SELECT count(*) FROM artists WHERE name ~ '^[0-9a-fA-F-]{32,}$'")
print("UUID-only artists:", cur.fetchone()[0])

cur.execute("SELECT count(*) FROM artists WHERE name ~ '^[0-9]+$'")
print("Pure numeric artists:", cur.fetchone()[0])
cur.execute("SELECT id, name FROM artists WHERE name ~ '^[0-9]+$' LIMIT 10")
for r in cur.fetchall():
    print(r)

# Check for #... patterns (e.g. #agentOf, #134E, #NAME?, #uuid)
cur.execute("SELECT count(*) FROM artists WHERE name ~ '^#' OR (name_en IS NOT NULL AND name_en ~ '^#')")
print("Total artists matching regex '^#':", cur.fetchone()[0])

# Artworks linked to # artists
cur.execute("""
    SELECT count(*) FROM artworks a
    JOIN artists ar ON a.artist_id = ar.id
    WHERE ar.name ~ '^#' OR (ar.name_en IS NOT NULL AND ar.name_en ~ '^#')
""")
print("Artworks linked to '^#' artists:", cur.fetchone()[0])

# Gallery reps linked to # artists
cur.execute("""
    SELECT count(*) FROM gallery_representations gr
    JOIN artists ar ON gr.artist_id = ar.id
    WHERE ar.name ~ '^#' OR (ar.name_en IS NOT NULL AND ar.name_en ~ '^#')
""")
print("Gallery reps linked to '^#' artists:", cur.fetchone()[0])

print("\n=== MUSEUMS NOISE CHECK ===")
cur.execute("SELECT id, name, name_en FROM museums WHERE name ~ '^[0-9]{4}\\s+(by|to)' OR name ~ '^[0-9]{4}' OR name LIKE '#%'")
rows = cur.fetchall()
print(f"Museums matching noise patterns: {len(rows)}")
for r in rows:
    print(r)

print("\n=== GALLERIES NOISE CHECK ===")
cur.execute("SELECT id, name FROM galleries WHERE name ~ '^[0-9]{4}\\s+(by|to)' OR name LIKE '#%'")
rows = cur.fetchall()
print(f"Galleries matching '^[0-9]{{4}}\\s+(by|to)' or '#': {len(rows)}")
for r in rows[:30]:
    print(r)

cur.execute("SELECT id, name FROM galleries WHERE name ~ '^[0-9]{4}'")
rows = cur.fetchall()
print(f"Galleries starting with 4 digits: {len(rows)}")
for r in rows[:20]:
    print(r)

print("\n=== COLLECTORS NOISE CHECK ===")
cur.execute("SELECT count(*) FROM collectors WHERE name ~ '^[0-9]{4}\\s+(by|to)' OR name LIKE '#%'")
print("Collectors with year by/to or #: ", cur.fetchone()[0])
cur.execute("SELECT id, name FROM collectors WHERE name ~ '^[0-9]{4}\\s+(by|to)' OR name LIKE '#%' LIMIT 20")
for r in cur.fetchall():
    print(r)

print("\n=== AUCTION HOUSES NOISE CHECK ===")
cur.execute("SELECT count(*) FROM auction_houses WHERE name ~ '^[0-9]{4}\\s+(by|to)' OR name LIKE '#%'")
print("Auction houses with year by/to or #: ", cur.fetchone()[0])
cur.execute("SELECT id, name FROM auction_houses WHERE name ~ '^[0-9]{4}\\s+(by|to)' OR name LIKE '#%' LIMIT 20")
for r in cur.fetchall():
    print(r)

conn.close()
