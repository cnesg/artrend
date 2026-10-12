import sys; sys.path.insert(0, "pipeline")
from db import get_connection

conn = get_connection()
cur = conn.cursor()
cur.execute("select count(*) from auction_lots al join auctions a on a.id=al.auction_id join auction_houses ah on ah.id=a.auction_house_id where ah.name='Bukowskis'")
print("total lots:", cur.fetchone())
cur.execute("select count(distinct a.id) from auctions a join auction_houses ah on ah.id=a.auction_house_id where ah.name='Bukowskis'")
print("total auctions:", cur.fetchone())
cur.execute("select count(distinct aw.artist_id) from auction_lots al join auctions a on a.id=al.auction_id join auction_houses ah on ah.id=a.auction_house_id join artworks aw on aw.id=al.artwork_id where ah.name='Bukowskis'")
print("distinct artists:", cur.fetchone())
