"""갤러리 작가 로스터(raw/gallery_<key>/) -> galleries/artists/gallery_representations 적재.

미술관 로더와 달리 artworks/museum_holdings를 채우지 않는다 — 갤러리 크롤러가
작가 로스터만 수집했기 때문에(관계 데이터), 여기서도 galleries 테이블과
gallery_representations 연결만 만든다.
"""
from __future__ import annotations

from raw_iter import iter_records

# site key -> (표시명, 도시, 국가)
GALLERY_INFO: dict[str, tuple[str, str, str]] = {
    "kukje": ("국제갤러리 (Kukje Gallery)", "서울", "대한민국"),
    "gallery_hyundai": ("갤러리현대 (Gallery Hyundai)", "서울", "대한민국"),
    "pkm": ("PKM갤러리", "서울", "대한민국"),
    "arario": ("아라리오갤러리 (Arario Gallery)", "서울", "대한민국"),
    "ropac": ("타데우스로팍 서울 (Thaddaeus Ropac)", "서울", "대한민국"),
    "wooson": ("우손갤러리 (Wooson Gallery)", "대구", "대한민국"),
    "gallery_baton": ("갤러리바톤 (Gallery Baton)", "서울", "대한민국"),
    "johyun": ("조현화랑 (Johyun Gallery)", "부산", "대한민국"),
    "pace": ("페이스갤러리 (Pace Gallery)", "뉴욕", "미국"),
    "lehmannmaupin": ("리만머핀 (Lehmann Maupin)", "뉴욕", "미국"),
    "perrotin": ("페로탕 (Perrotin)", "파리", "프랑스"),
    "davidzwirner": ("데이비드즈워너 (David Zwirner)", "뉴욕", "미국"),
    "whitecube": ("화이트큐브 (White Cube)", "런던", "영국"),
    "mariangoodman": ("마리안굿맨 (Marian Goodman Gallery)", "뉴욕", "미국"),
    "spruethmagers": ("스프루스마거스 (Sprüth Magers)", "베를린", "독일"),
    "victoriamiro": ("빅토리아미로 (Victoria Miro)", "런던", "영국"),
    "koeniggalerie": ("쾨니히갤러리 (König Galerie)", "베를린", "독일"),
    "gladstone": ("글래드스톤갤러리 (Gladstone Gallery)", "뉴욕", "미국"),
    "shugoarts": ("슈고아츠 (ShugoArts)", "도쿄", "일본"),
    "tomiokoyama": ("토미오코야마갤러리 (Tomio Koyama Gallery)", "도쿄", "일본"),
    "estherschipper": ("에스더쉬퍼 (Esther Schipper)", "베를린", "독일"),
    "maxhetzler": ("막스헤츨러갤러리 (Galerie Max Hetzler)", "베를린", "독일"),
    "otafinearts": ("오타파인아츠 (Ota Fine Arts)", "도쿄", "일본"),
    "leeahn": ("리안갤러리 (Leeahn Gallery)", "대구", "대한민국"),
    "313artproject": ("313 Art Project", "서울", "대한민국"),
    "gallery2": ("갤러리2 (Gallery2)", "서울", "대한민국"),
    "galleriacontinua": ("갤러리아 콘티누아 (Galleria Continua)", "산지미냐노", "이탈리아"),
    "massimodecarlo": ("마시모데카를로 (Massimo De Carlo)", "밀라노", "이탈리아"),
    "seankelly": ("션켈리갤러리 (Sean Kelly)", "뉴욕", "미국"),
    "303gallery": ("303 갤러리 (303 Gallery)", "뉴욕", "미국"),
    "alminerech": ("알민레쉬 (Almine Rech)", "파리", "프랑스"),
    "regenprojects": ("리젠프로젝츠 (Regen Projects)", "로스앤젤레스", "미국"),
    "mizuma": ("미즈마아트갤러리 (Mizuma Art Gallery)", "도쿄", "일본"),
    "scaithebathhouse": ("스카이더배스하우스 (SCAI The Bathhouse)", "도쿄", "일본"),
    "skarstedt": ("스카르스테트 (Skarstedt)", "뉴욕", "미국"),
    "mennour": ("멘누르 (Kamel Mennour)", "파리", "프랑스"),
    "gallerychosun": ("갤러리조선 (Gallery Chosun)", "서울", "대한민국"),
    "matthewmarks": ("매튜마크스갤러리 (Matthew Marks Gallery)", "뉴욕", "미국"),
    "paulacooper": ("폴라쿠퍼갤러리 (Paula Cooper Gallery)", "뉴욕", "미국"),
    "caseykaplan": ("케이시카플란갤러리 (Casey Kaplan)", "뉴욕", "미국"),
    "luhringaugustine": ("루링오거스틴 (Luhring Augustine)", "뉴욕", "미국"),
    "petzel": ("페첼갤러리 (Petzel Gallery)", "뉴욕", "미국"),
    "takeninagawa": ("타케니나가와 (Take Ninagawa)", "도쿄", "일본"),
    "anomalytokyo": ("아노말리 (ANOMALY)", "도쿄", "일본"),
    "carliergebauer": ("칼리에르게바우어 (carlier | gebauer)", "베를린", "독일"),
    "kurimanzutto": ("쿠리만수토 (kurimanzutto)", "멕시코시티", "멕시코"),
    "krinzinger": ("갤러리크린징거 (Galerie Krinzinger)", "빈", "오스트리아"),
    "sadiecoles": ("세이디콜스HQ (Sadie Coles HQ)", "런던", "영국"),
    "sungallery": ("선화랑 (Sun Gallery)", "서울", "대한민국"),
    "ocimuseum": ("OCI미술관 (OCI Museum)", "서울", "대한민국"),
    "tanyabonakdar": ("타냐본다카르갤러리 (Tanya Bonakdar Gallery)", "뉴욕", "미국"),
    "jamescohan": ("제임스코핸갤러리 (James Cohan Gallery)", "뉴욕", "미국"),
    "cheimread": ("체임리드갤러리 (Cheim & Read)", "뉴욕", "미국"),
    "nararoesler": ("나라뢰슬러갤러리 (Nara Roesler)", "상파울루", "브라질"),
    "kasmin": ("카스민갤러리 (Kasmin)", "뉴욕", "미국"),
    "milesmcenery": ("마일스맥에너리갤러리 (Miles McEnery Gallery)", "뉴욕", "미국"),
    "jackshainman": ("잭샤인먼갤러리 (Jack Shainman Gallery)", "뉴욕", "미국"),
    "antonkern": ("앤톤컨갤러리 (Anton Kern Gallery)", "뉴욕", "미국"),
    "miandn": ("미첼이네스앤내시 (Mitchell-Innes & Nash)", "뉴욕", "미국"),
    "nonakahill": ("노나카힐 (Nonaka-Hill)", "로스앤젤레스", "미국"),
    "waitingroom": ("웨이팅룸 (WAITINGROOM)", "도쿄", "일본"),
    "meyerriegger": ("마이어리거갤러리 (Meyer Riegger)", "베를린", "독일"),
    "wentrup": ("벤트룹갤러리 (Wentrup)", "베를린", "독일"),
    "mai36": ("마이36갤러리 (Galerie Mai 36)", "취리히", "스위스"),
    "capitainpetzel": ("카피탄페첼 (Capitain Petzel)", "베를린", "독일"),
    "annetgelink": ("아네트겔링크갤러리 (Annet Gelink Gallery)", "암스테르담", "네덜란드"),
    "vielmetter": ("수잔필메터갤러리 (Susanne Vielmetter Los Angeles Projects)", "로스앤젤레스", "미국"),
    "zenox": ("제노엑스갤러리 (Zeno X Gallery)", "안트베르펜", "벨기에"),
    "xavierhufkens": ("자비에위프켄스갤러리 (Xavier Hufkens)", "브뤼셀", "벨기에"),
    "dvirgallery": ("드비르갤러리 (Dvir Gallery)", "텔아비브", "이스라엘"),
    "cardigallery": ("카르디갤러리 (Cardi Gallery)", "밀라노", "이탈리아"),
    "meminc": ("MEM (mem-inc)", "도쿄", "일본"),
    "proyectosmonclova": ("프로옉토스몽클로바 (Proyectos Monclova)", "멕시코시티", "멕시코"),
    "gallerykiche": ("갤러리기체 (Gallery Kiche)", "서울", "대한민국"),
    "cristinaguerra": ("크리스티나게라갤러리 (Galeria Cristina Guerra)", "리스본", "포르투갈"),
    "vsf": ("베리어스스몰파이어스 (Various Small Fires)", "로스앤젤레스", "미국"),
    "nightgallery": ("나이트갤러리 (Night Gallery)", "로스앤젤레스", "미국"),
    "barakatcontemporary": ("바라캇컨템포러리 (Barakat Contemporary)", "서울", "대한민국"),
    "tinakimgallery": ("티나킴갤러리 (Tina Kim Gallery)", "뉴욕", "미국"),
    "andrewkreps": ("앤드류크렙스갤러리 (Andrew Kreps Gallery)", "뉴욕", "미국"),
    "thomasschulte": ("갤러리토마스슐테 (Galerie Thomas Schulte)", "베를린", "독일"),
    "kaynegriffin": ("케인그리핀갤러리 (Kayne Griffin)", "로스앤젤레스", "미국"),
    "ghebaly": ("프랑수아게발리갤러리 (François Ghebaly)", "로스앤젤레스", "미국"),
    "taronasu": ("타로나스갤러리 (Taro Nasu)", "도쿄", "일본"),
    "omr": ("갤러리아OMR (Galería OMR)", "멕시코시티", "멕시코"),
    "stpi": ("STPI (Singapore Tyler Print Institute)", "싱가포르", "싱가포르"),
    "whitespace": ("화이트스페이스 (White Space Beijing)", "베이징", "중국"),
    "thethirdline": ("더서드라인 (The Third Line)", "두바이", "아랍에미리트"),
    "athrart": ("아쓰르갤러리 (Athr Gallery)", "제다", "사우디아라비아"),
    "goodmangallery": ("굿맨갤러리 (Goodman Gallery)", "요하네스버그", "남아프리카공화국"),
    "roslynoxley9": ("로슬린옥슬리9 (Roslyn Oxley9 Gallery)", "시드니", "호주"),
}


def load(store) -> int:
    loaded = 0
    for key, (display_name, city, country) in GALLERY_INFO.items():
        site_name = f"gallery_{key}"
        gallery_id = None
        seen_artist_ids: set = set()

        for _record_id, data, meta in iter_records(site_name):
            if store.source_already_loaded(meta["raw_path"]):
                continue

            if gallery_id is None:
                gallery_id = store.get_or_create_gallery(display_name, city=city, country=country, website=data.get("url"))
                # 이전 실행에서 이미 넣은 (gallery_id, artist_id) 쌍도 seen에 미리 채워둔다
                # (실제 DB 적재 시에만 — dry-run에는 실 DB cursor가 없음).
                cur = getattr(store, "cur", None)
                if cur is not None:
                    cur.execute("select artist_id from gallery_representations where gallery_id = %s", (gallery_id,))
                    seen_artist_ids.update(str(row[0]) for row in cur.fetchall())

            source_id = store.insert_source(meta)
            artist_name = (data.get("name") or "").strip()
            artist_id = store.get_or_create_artist(artist_name, source_id=source_id)
            if artist_id is None:
                continue

            # 일부 갤러리 사이트 자체가 같은 작가를 두 URL(예: /artists/x, /artists/x2)로
            # 중복 서빙한다 — href는 다르지만 get_or_create_artist가 같은 artist_id로
            # 묶어주므로, (gallery_id, artist_id) 단위로 한 번만 넣는다.
            if artist_id in seen_artist_ids:
                continue
            seen_artist_ids.add(artist_id)

            store.insert_gallery_representation(
                gallery_id=gallery_id,
                artist_id=artist_id,
                source_id=source_id,
            )
            loaded += 1

    store.commit()
    print(f"[pipeline:galleries] {loaded}건 적재")
    return loaded
