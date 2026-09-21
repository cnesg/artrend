"""DB 노이즈 데이터 정제 스크립트.

정제 대상:
1. 작가 (artists):
   - ^# 로 시작하거나 내부식별자 (#agentOf, #Predmet, #134E, #NAME?, UUID 등)
   - 4자리 연도로만 된 작가 ('1778', '1810')
   - artworks.artist_id = NULL 처리 후 artists 레코드 삭제
2. 미술관 (museums):
   - ^[0-9]{4}\\s+(by|to) 프로버넌스 파싱 잔여물
   - provenance_records.owner_museum_id 정리 (기존 미술관 연결 또는 unknown 처리) 후 삭제
3. 갤러리 (galleries):
   - ^[0-9]{4}\\s+(by|to) 프로버넌스 파싱 잔여물
   - provenance_records.owner_gallery_id 정리 (기존 갤러리 연결 또는 unknown 처리) 후 삭제
4. 경매사 (auction_houses):
   - ^[0-9]{4}\\s+(by|to) 또는 날짜 파싱 잔여물
   - provenance_records.owner_auction_house_id 정리 (unknown 처리 또는 적절한 컬렉터 연결) 후 삭제
5. 컬렉터 (collectors):
   - ^[0-9]{4}\\s+(by|to) 프로버넌스 파싱 잔여물 정제 / 병합 및 불량 레코드 정리
"""
import sys
import re

from db import get_connection

sys.stdout.reconfigure(encoding="utf-8")

def clean_database():
    conn = get_connection()
    conn.autocommit = False
    cur = conn.cursor()

    try:
        print("=== 1. 작가(artists) 노이즈 데이터 정제 ===")
        dirty_artists_sql = """
            SELECT id, name FROM artists 
            WHERE name ~ '^#' 
               OR (name_en IS NOT NULL AND name_en ~ '^#')
               OR name ~ '^[0-9]{4}$'
               OR name ~ '^[0-9a-fA-F-]{32,}$'
               OR name ~ '^#agentOf'
               OR name ~ '^#Predmet'
               OR name ~ '^#134'
               OR name = '#NAME?'
        """
        cur.execute(dirty_artists_sql)
        dirty_artists = cur.fetchall()
        dirty_artist_ids = [r[0] for r in dirty_artists]
        print(f"발견된 노이즈 작가 수: {len(dirty_artist_ids)}")

        if dirty_artist_ids:
            # 1-1. gallery_representations 삭제
            cur.execute("""
                DELETE FROM gallery_representations 
                WHERE artist_id = ANY(%s::uuid[])
            """, (dirty_artist_ids,))
            print(f"삭제된 갤러리 전속 관계: {cur.rowcount}건")

            # 1-2. artworks.artist_id = NULL
            cur.execute("""
                UPDATE artworks 
                SET artist_id = NULL 
                WHERE artist_id = ANY(%s::uuid[])
            """, (dirty_artist_ids,))
            print(f"artist_id NULL 처리된 작품: {cur.rowcount}건")

            # 1-3. artists 삭제
            cur.execute("""
                DELETE FROM artists 
                WHERE id = ANY(%s::uuid[])
            """, (dirty_artist_ids,))
            print(f"삭제된 노이즈 작가: {cur.rowcount}건")

        print("\n=== 2. 미술관(museums) 노이즈 데이터 정제 ===")
        cur.execute("""
            SELECT id, name FROM museums 
            WHERE name ~ '^[0-9]{4}\\s+(by|to)' OR name ~ '^#'
        """)
        dirty_museums = cur.fetchall()
        print(f"발견된 노이즈 미술관: {len(dirty_museums)}")
        for m_id, m_name in dirty_museums:
            print(f"  - {m_id}: {m_name}")
            # 'British Museum' 매핑 시도
            cur.execute("SELECT id FROM museums WHERE name = 'British Museum' AND id != %s LIMIT 1", (m_id,))
            real_bm = cur.fetchone()
            if real_bm:
                cur.execute("UPDATE provenance_records SET owner_museum_id = %s WHERE owner_museum_id = %s", (real_bm[0], m_id))
            else:
                cur.execute("UPDATE provenance_records SET owner_type = 'unknown', owner_museum_id = NULL WHERE owner_museum_id = %s", (m_id,))
            cur.execute("DELETE FROM museum_holdings WHERE museum_id = %s", (m_id,))
            cur.execute("DELETE FROM museums WHERE id = %s", (m_id,))
        print(f"미술관 노이즈 {len(dirty_museums)}건 정리 완료")

        print("\n=== 3. 갤러리(galleries) 노이즈 데이터 정제 ===")
        cur.execute("""
            SELECT id, name FROM galleries 
            WHERE name ~ '^[0-9]{4}\\s+(by|to)' OR name ~ '^#'
        """)
        dirty_galleries = cur.fetchall()
        print(f"발견된 노이즈 갤러리: {len(dirty_galleries)}")
        for g_id, g_name in dirty_galleries:
            print(f"  - {g_id}: {g_name}")
            clean_name = re.sub(r'^[0-9]{4}\s+(by|to)\s+', '', g_name).strip()
            cur.execute("SELECT id FROM galleries WHERE name = %s AND id != %s LIMIT 1", (clean_name, g_id))
            real_g = cur.fetchone()
            if real_g:
                cur.execute("UPDATE provenance_records SET owner_gallery_id = %s WHERE owner_gallery_id = %s", (real_g[0], g_id))
                cur.execute("UPDATE gallery_representations SET gallery_id = %s WHERE gallery_id = %s", (real_g[0], g_id))
            else:
                cur.execute("UPDATE provenance_records SET owner_type = 'unknown', owner_gallery_id = NULL WHERE owner_gallery_id = %s", (g_id,))
                cur.execute("DELETE FROM gallery_representations WHERE gallery_id = %s", (g_id,))
            cur.execute("DELETE FROM galleries WHERE id = %s", (g_id,))
        print(f"갤러리 노이즈 {len(dirty_galleries)}건 정리 완료")

        print("\n=== 4. 경매사(auction_houses) 노이즈 데이터 정제 ===")
        cur.execute("""
            SELECT id, name FROM auction_houses 
            WHERE name ~ '^[0-9]{4}\\s+(by|to)' OR name ~ '^#' OR name ~ '^[A-Za-z]+\\s+[0-9]{4}\\s+to'
        """)
        dirty_houses = cur.fetchall()
        print(f"발견된 노이즈 경매사: {len(dirty_houses)}")
        for h_id, h_name in dirty_houses:
            print(f"  - {h_id}: {h_name}")
            # Check if this was actually a collector (e.g. Duncan Phillips)
            clean_name = re.sub(r'^[A-Za-z]+\s+[0-9]{4}\s+to\s+', '', h_name)
            clean_name = re.sub(r'^[0-9]{4}\s+(by|to)\s+', '', clean_name).strip()
            cur.execute("SELECT id FROM collectors WHERE name = %s LIMIT 1", (clean_name,))
            col = cur.fetchone()
            if col:
                cur.execute("UPDATE provenance_records SET owner_type = 'collector', owner_collector_id = %s, owner_auction_house_id = NULL WHERE owner_auction_house_id = %s", (col[0], h_id))
            else:
                cur.execute("UPDATE provenance_records SET owner_type = 'unknown', owner_auction_house_id = NULL WHERE owner_auction_house_id = %s", (h_id,))
            
            cur.execute("DELETE FROM auction_lots WHERE auction_id IN (SELECT id FROM auctions WHERE auction_house_id = %s)", (h_id,))
            cur.execute("DELETE FROM auctions WHERE auction_house_id = %s", (h_id,))
            cur.execute("DELETE FROM auction_houses WHERE id = %s", (h_id,))
        print(f"경매사 노이즈 {len(dirty_houses)}건 정리 완료")

        print("\n=== 5. 컬렉터(collectors) 노이즈 데이터 정제 ===")
        cur.execute("""
            SELECT id, name FROM collectors 
            WHERE name ~ '^[0-9]{4}\\s+(by|to)' OR name ~ '^#'
        """)
        dirty_collectors = cur.fetchall()
        print(f"발견된 노이즈 컬렉터: {len(dirty_collectors)}")
        merged_count = 0
        cleaned_count = 0
        deleted_count = 0

        for c_id, c_name in dirty_collectors:
            clean_name = re.sub(r'^[0-9]{4}\s+(by|to)\s+', '', c_name).strip()
            clean_name = re.sub(r'^#\s*', '', clean_name).strip()
            if not clean_name or len(clean_name) < 2 or clean_name.isdigit():
                cur.execute("UPDATE provenance_records SET owner_type = 'unknown', owner_collector_id = NULL WHERE owner_collector_id = %s", (c_id,))
                cur.execute("DELETE FROM collectors WHERE id = %s", (c_id,))
                deleted_count += 1
            else:
                cur.execute("SELECT id FROM collectors WHERE name = %s AND id != %s LIMIT 1", (clean_name, c_id))
                existing = cur.fetchone()
                if existing:
                    cur.execute("UPDATE provenance_records SET owner_collector_id = %s WHERE owner_collector_id = %s", (existing[0], c_id))
                    cur.execute("DELETE FROM collectors WHERE id = %s", (c_id,))
                    merged_count += 1
                else:
                    cur.execute("UPDATE collectors SET name = %s WHERE id = %s", (clean_name, c_id))
                    cleaned_count += 1

        print(f"컬렉터 정제 결과: {merged_count}건 기존 컬렉터로 병합, {cleaned_count}건 이름 정제, {deleted_count}건 불량 삭제")

        conn.commit()
        print("\n[성공] 모든 DB 클렌징 작업이 완료되고 커밋되었습니다.")

    except Exception as e:
        conn.rollback()
        print(f"\n[오류] 클렌징 중 에러 발생, 롤백됨: {e}")
        raise
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    clean_database()
