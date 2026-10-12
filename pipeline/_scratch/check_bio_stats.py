import os, sys, psycopg2, re
from dotenv import load_dotenv
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
load_dotenv(Path(__file__).parent / ".env")

conn = psycopg2.connect(os.environ["DATABASE_URL"])
conn.set_client_encoding("UTF8")
cur = conn.cursor()

# Check total artists in DB
cur.execute("SELECT count(*) FROM artists;")
print(f"Total artists in DB: {cur.fetchone()[0]}")

cur.execute("SELECT count(*) FROM artists WHERE bio IS NOT NULL AND length(trim(bio)) > 0;")
print(f"Total artists with non-empty bio in DB: {cur.fetchone()[0]}")

# Check Korean bios in artists
cur.execute("SELECT count(*) FROM artists WHERE bio ~ '[\uac00-\ud7a3]';")
print(f"Artists with Korean in bio: {cur.fetchone()[0]}")

cur.close()
conn.close()
