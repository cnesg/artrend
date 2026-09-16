import psycopg2

conn = psycopg2.connect("postgresql://postgres@127.0.0.1:5433/artrend")
conn.autocommit = True
cur = conn.cursor()

indexes = [
    ("idx_provenance_collector", "CREATE INDEX IF NOT EXISTS idx_provenance_collector ON provenance_records (owner_collector_id) WHERE owner_collector_id IS NOT NULL"),
    ("idx_provenance_museum", "CREATE INDEX IF NOT EXISTS idx_provenance_museum ON provenance_records (owner_museum_id) WHERE owner_museum_id IS NOT NULL"),
    ("idx_provenance_gallery", "CREATE INDEX IF NOT EXISTS idx_provenance_gallery ON provenance_records (owner_gallery_id) WHERE owner_gallery_id IS NOT NULL"),
    ("idx_provenance_auction_house", "CREATE INDEX IF NOT EXISTS idx_provenance_auction_house ON provenance_records (owner_auction_house_id) WHERE owner_auction_house_id IS NOT NULL"),
]

for name, sql in indexes:
    print(f"Creating {name}...", flush=True)
    cur.execute(sql)
    print(f"Created {name}.", flush=True)

cur.close()
conn.close()
print("All indexes created successfully!", flush=True)
