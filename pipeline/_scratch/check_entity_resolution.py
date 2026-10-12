import sys
import psycopg2

sys.stdout.reconfigure(encoding="utf-8")

conn = psycopg2.connect("postgresql://postgres@127.0.0.1:5433/artrend")
cur = conn.cursor()

# Check British Museum
cur.execute("SELECT id, name FROM museums WHERE name ILIKE '%British Museum%'")
print("British museums:", cur.fetchall(), flush=True)

# Check Sidney Janis / Squire
cur.execute("SELECT id, name FROM galleries WHERE name ILIKE '%Janis%' OR name ILIKE '%Squire%'")
print("Galleries:", cur.fetchall(), flush=True)

# Check Duncan Phillips / Lionel Phillips
cur.execute("SELECT id, name FROM auction_houses WHERE name ILIKE '%Phillips%'")
print("Auction houses:", cur.fetchall(), flush=True)

# Check collectors with year by/to
cur.execute("SELECT id, name FROM collectors WHERE name ~ '^[0-9]{4}\\s+(by|to)' OR name LIKE '#%' LIMIT 10")
print("Sample dirty collectors:", cur.fetchall(), flush=True)

conn.close()
