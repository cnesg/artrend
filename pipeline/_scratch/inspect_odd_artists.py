import os, sys, psycopg2
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")
conn = psycopg2.connect(os.environ["DATABASE_URL"])
cur = conn.cursor()

cur.execute("SELECT id, name, name_en, nationality, birth_year, death_year, bio FROM artists WHERE name IN ('China', 'Italian', 'Rubens', 'Teniers', 'Carven', 'Guido')")
for r in cur.fetchall():
    print(r)

cur.close()
conn.close()
