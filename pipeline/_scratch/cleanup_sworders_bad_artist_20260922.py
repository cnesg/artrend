"""파싱 버그(장식미술 설명문 끝의 역사적 인물 생몰년을 작가로 오인)로 잘못 들어간
단일 레코드 삭제. 버그는 pipeline/sworders.py에서 이미 고쳤다(GENERIC_LEAD_RE + 60자
제한) — 이 스크립트는 고치기 전에 들어간 레코드 1건만 정확히 지운다.
전수 확인: artists.name이 정확히 이 문자열과 같은 행은 DB 전체에 1건뿐임을 먼저 확인하고
지운다(화이트리스트 = 이 이름 문자열 정확 일치 하나).
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "pipeline")
from db import get_connection

BAD_NAME = "A rare C J Spooner fairground/carousel 'Boer War' centaur in the form of General Redvers Buller"

conn = get_connection()
cur = conn.cursor()

cur.execute("select id from artists where name = %s", (BAD_NAME,))
rows = cur.fetchall()
print(f"matching artist rows: {len(rows)}")
if len(rows) != 1:
    print("전수 확인 실패(0건 또는 2건 이상) — 아무것도 지우지 않고 종료")
    sys.exit(1)

artist_id = rows[0][0]

cur.execute("select id, title from artworks where artist_id = %s", (artist_id,))
artworks = cur.fetchall()
print("artworks:", artworks)

artwork_ids = [str(a[0]) for a in artworks]
cur.execute(
    "select id, lot_number, hammer_price from auction_lots where artwork_id = any(%s::uuid[])",
    (artwork_ids,),
)
lots = cur.fetchall()
print("lots:", lots)

# 삭제 순서: auction_lots -> artworks -> artists (FK 의존성 역순)
cur.execute("delete from auction_lots where artwork_id = any(%s::uuid[])", (artwork_ids,))
cur.execute("delete from artworks where artist_id = %s", (artist_id,))
cur.execute("delete from artists where id = %s", (artist_id,))
conn.commit()
print("삭제 완료")

cur.close()
conn.close()
