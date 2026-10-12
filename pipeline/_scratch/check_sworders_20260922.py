import sys
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "pipeline")
from db import get_connection

conn = get_connection()
cur = conn.cursor()

cur.execute("select id, name, country from auction_houses where name = 'Sworders'")
house = cur.fetchone()
print("auction_house:", house)

cur.execute(
    """
    select a.auction_date, count(*)
    from auction_lots al
    join auctions a on a.id = al.auction_id
    where a.auction_house_id = %s
    group by a.auction_date
    order by a.auction_date
    """,
    (house[0],),
)
print("\nauctions/lot counts:")
for row in cur.fetchall():
    print(" ", row)

cur.execute(
    """
    select ar.name, ar.birth_year, ar.death_year, aw.title, al.lot_number, al.hammer_price, al.currency
    from auction_lots al
    join artworks aw on aw.id = al.artwork_id
    left join artists ar on ar.id = aw.artist_id
    join auctions a on a.id = al.auction_id
    where a.auction_house_id = %s
    order by al.hammer_price desc nulls last
    limit 15
    """,
    (house[0],),
)
print("\ntop lots by hammer price:")
for row in cur.fetchall():
    print(" ", row)

cur.execute(
    """
    select count(*), count(distinct al.lot_number || ':' || a.id::text)
    from auction_lots al
    join auctions a on a.id = al.auction_id
    where a.auction_house_id = %s
    """,
    (house[0],),
)
print("\ntotal lots vs distinct (lot_number, auction) pairs (dup check):", cur.fetchone())

cur.close()
conn.close()
