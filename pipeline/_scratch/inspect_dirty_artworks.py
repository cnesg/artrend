import sys
import psycopg2

sys.stdout.reconfigure(encoding="utf-8")

conn = psycopg2.connect("postgresql://postgres@127.0.0.1:5433/artrend")
cur = conn.cursor()

cur.execute("""
    SELECT a.id, a.title, a.year_created, a.source_id, ar.name
    FROM artworks a
    JOIN artists ar ON a.artist_id = ar.id
    WHERE ar.name ~ '^#' OR (ar.name_en IS NOT NULL AND ar.name_en ~ '^#')
    LIMIT 20
""")
for r in cur.fetchall():
    print(r, flush=True)

conn.close()
