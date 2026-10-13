"""Kiaf 2016–2026 — research/kiaf/build_kiaf.py가 캐시 원본으로 조립한 회차 JSON을 적재 (2026-10-13).
조립 코드 사본: v2/research/kiaf/ (실행은 캐시와 같은 폴더인 ~/artgraph_v2_data/research/kiaf/ 에서)."""

EDITIONS = {'kiaf_2016': {'series': 'kiaf',
               'year': 2016,
               'label': 'Kiaf 2016',
               'title': None,
               'start_date': '2016-10-13',
               'end_date': '2016-10-16',
               'city': 'Seoul',
               'announced': None,
               'coverage': 'partial',
               'coverage_note': '갤러리 목록 + 특별전/하이라이트 작가만 — 부스별 출품작가를 공개한 기계판독 출처 없음. 갤러리 171 / 작가 9. No official count '
                                "found for 2016: kiaf.org/2016 'About' (Wayback 20160906) says only 'about 20 "
                                "countries' 180 galleries are participating in KIAF annually'; Aesthetica (secondary) "
                                'reported ~170 galleries / 16 countries. Dates from a coex.co.kr listing (secondary, '
                                'via web search); VIP preview 10-12 n',
               'prebuilt': 'research/kiaf/kiaf_2016.json',
               'prebuilt_adapter': 'fair_kiaf:adapt',
               'license': 'kiaf.org 공식 아카이브·카탈로그 PDF(static-edge.kiaf.org)·웨이백 스냅샷, robots.txt 허용 확인(2026-10-12). 갤러리 '
                          '계정·사업자등록 엔드포인트와 robots 차단 드라이브 카탈로그는 사용 안 함',
               'sources': []},
 'kiaf_2017': {'series': 'kiaf',
               'year': 2017,
               'label': 'Kiaf 2017',
               'title': None,
               'start_date': '2017-09-20',
               'end_date': '2017-09-24',
               'city': 'Seoul',
               'announced': None,
               'coverage': 'partial',
               'coverage_note': '갤러리 목록 + 특별전/하이라이트 작가만 — 부스별 출품작가를 공개한 기계판독 출처 없음. 갤러리 168 / 작가 18. No official count '
                                'captured; secondary press reports conflict (e.g. 161). 09-20 = VIP preview, public '
                                '09-21..24 (secondary press via web search). | Gallery list = official 2017 exhibitor '
                                'page (Wayback 20170927125359, 167 galleries) matched to the kiaf.org past-exhibitors '
                                'archive DB (167 galleries for',
               'prebuilt': 'research/kiaf/kiaf_2017.json',
               'prebuilt_adapter': 'fair_kiaf:adapt',
               'license': 'kiaf.org 공식 아카이브·카탈로그 PDF(static-edge.kiaf.org)·웨이백 스냅샷, robots.txt 허용 확인(2026-10-12). 갤러리 '
                          '계정·사업자등록 엔드포인트와 robots 차단 드라이브 카탈로그는 사용 안 함',
               'sources': []},
 'kiaf_2018': {'series': 'kiaf',
               'year': 2018,
               'label': 'Kiaf 2018',
               'title': None,
               'start_date': '2018-10-04',
               'end_date': '2018-10-07',
               'city': 'Seoul',
               'announced': 174,
               'coverage': 'partial',
               'coverage_note': '갤러리 목록 + 특별전/하이라이트 작가만 — 부스별 출품작가를 공개한 기계판독 출처 없음. 갤러리 174 / 작가 4. 174 galleries / 14 '
                                'countries (Korea JoongAng Daily, secondary). Dates from archived '
                                "kiaf.org/2018/about-us ('Oct. 4th (Thu.) to 7th (Sun)'); VIP preview 10-03 not "
                                'verified. | Gallery list = official 2018 exhibitor page (Wayback 20181005144207, 174 '
                                'galleries) matched to the kiaf.org past-exhibitors a',
               'prebuilt': 'research/kiaf/kiaf_2018.json',
               'prebuilt_adapter': 'fair_kiaf:adapt',
               'license': 'kiaf.org 공식 아카이브·카탈로그 PDF(static-edge.kiaf.org)·웨이백 스냅샷, robots.txt 허용 확인(2026-10-12). 갤러리 '
                          '계정·사업자등록 엔드포인트와 robots 차단 드라이브 카탈로그는 사용 안 함',
               'sources': []},
 'kiaf_2019': {'series': 'kiaf',
               'year': 2019,
               'label': 'Kiaf 2019',
               'title': None,
               'start_date': '2019-09-26',
               'end_date': '2019-09-29',
               'city': 'Seoul',
               'announced': 175,
               'coverage': 'partial',
               'coverage_note': '갤러리 목록 + 특별전/하이라이트 작가만 — 부스별 출품작가를 공개한 기계판독 출처 없음. 갤러리 175 / 작가 24. 175 galleries / '
                                '17 countries (Newsis 2019-09-21, secondary). Public days 09-26..29 per archived '
                                'kiaf.org/2019/visitor-info-k; VIP opening 09-25. | Gallery list = official 2019 '
                                'exhibitor page (Wayback 20200127014918, 175 galleries) matched to the kiaf.org '
                                'past-exhibitors archive DB (175 galleries for',
               'prebuilt': 'research/kiaf/kiaf_2019.json',
               'prebuilt_adapter': 'fair_kiaf:adapt',
               'license': 'kiaf.org 공식 아카이브·카탈로그 PDF(static-edge.kiaf.org)·웨이백 스냅샷, robots.txt 허용 확인(2026-10-12). 갤러리 '
                          '계정·사업자등록 엔드포인트와 robots 차단 드라이브 카탈로그는 사용 안 함',
               'sources': []},
 'kiaf_2020': {'series': 'kiaf',
               'year': 2020,
               'label': 'Kiaf 2020',
               'title': None,
               'start_date': '2020-09-16',
               'end_date': '2020-10-18',
               'city': 'Seoul',
               'announced': 139,
               'coverage': 'partial',
               'coverage_note': '갤러리 목록 + 특별전/하이라이트 작가만 — 부스별 출품작가를 공개한 기계판독 출처 없음. 갤러리 138 / 작가 30. Physical fair '
                                'cancelled (COVID-19); held online 2020-09-16..10-18 with 139 galleries / 4,000+ works '
                                'per kiaf.org/about-history. The whole edition was the online fair, so booths are '
                                "section 'main' (no physical booths). kiaf_code 'OVR' marks 7 galleries coded "
                                'online-only even in the DB; the other code',
               'prebuilt': 'research/kiaf/kiaf_2020.json',
               'prebuilt_adapter': 'fair_kiaf:adapt',
               'license': 'kiaf.org 공식 아카이브·카탈로그 PDF(static-edge.kiaf.org)·웨이백 스냅샷, robots.txt 허용 확인(2026-10-12). 갤러리 '
                          '계정·사업자등록 엔드포인트와 robots 차단 드라이브 카탈로그는 사용 안 함',
               'sources': []},
 'kiaf_2021': {'series': 'kiaf',
               'year': 2021,
               'label': 'Kiaf 2021',
               'title': None,
               'start_date': '2021-10-13',
               'end_date': '2021-10-17',
               'city': 'Seoul',
               'announced': 170,
               'coverage': 'partial',
               'coverage_note': '갤러리 목록 + 특별전/하이라이트 작가만 — 부스별 출품작가를 공개한 기계판독 출처 없음. 갤러리 170 / 작가 0. 170 galleries / 10 '
                                "countries (kiaf.org press clip 7387 title; kiaf.org/about-history '170'). Dates from "
                                'press clips listed on kiaf.org (7387, 7424). No per-booth artists: 2021 OVR data is '
                                'not exposed by the current CMS and was not archived; the 2021 Incheon Airport special '
                                'exhibition is gallery-leve',
               'prebuilt': 'research/kiaf/kiaf_2021.json',
               'prebuilt_adapter': 'fair_kiaf:adapt',
               'license': 'kiaf.org 공식 아카이브·카탈로그 PDF(static-edge.kiaf.org)·웨이백 스냅샷, robots.txt 허용 확인(2026-10-12). 갤러리 '
                          '계정·사업자등록 엔드포인트와 robots 차단 드라이브 카탈로그는 사용 안 함',
               'sources': []},
 'kiaf_2022': {'series': 'kiaf',
               'year': 2022,
               'label': 'Kiaf SEOUL 2022',
               'title': None,
               'start_date': '2022-09-02',
               'end_date': '2022-09-05',
               'city': 'Seoul',
               'announced': 163,
               'coverage': 'partial',
               'coverage_note': '온라인 뷰잉룸 업로드 기준 — 본 페어 131/162, PLUS 52/73 갤러리만 작가 있음(확정 부스 명단 아님). 갤러리 162 / 작가 967. '
                                'Kiaf SEOUL 2022: 163 galleries / 17 countries per kiaf.org/about-history (164 in the '
                                'July 2022 announcement, press clips 15155/15159); Kiaf PLUS 2022 (separate satellite '
                                "fair at SETEC): 73 galleries / 10 countries -> separate section 'Kiaf PLUS 2022 "
                                "(satellite fair, SETEC)', NOT merged. Artists come",
               'prebuilt': 'research/kiaf/kiaf_2022.json',
               'prebuilt_adapter': 'fair_kiaf:adapt',
               'license': 'kiaf.org 공식 아카이브·카탈로그 PDF(static-edge.kiaf.org)·웨이백 스냅샷, robots.txt 허용 확인(2026-10-12). 갤러리 '
                          '계정·사업자등록 엔드포인트와 robots 차단 드라이브 카탈로그는 사용 안 함',
               'sources': []},
 'kiaf_2023': {'series': 'kiaf',
               'year': 2023,
               'label': 'Kiaf SEOUL 2023',
               'title': None,
               'start_date': '2023-09-06',
               'end_date': '2023-09-10',
               'city': 'Seoul',
               'announced': 210,
               'coverage': 'partial',
               'coverage_note': '갤러리 목록 + 특별전/하이라이트 작가만 — 부스별 출품작가를 공개한 기계판독 출처 없음. 갤러리 208 / 작가 2. 210 galleries / 20 '
                                'countries (kiaf.org/about-history and press clip 30373; clip 34238 says 211). '
                                "kiaf_code 'G' (30) most likely = Grand Ballroom, where Kiaf PLUS 2023 was held per "
                                'the history page (not verified per gallery). No per-booth artists: no 2023 catalogue '
                                'PDF found, OVR 2023 not archived (1',
               'prebuilt': 'research/kiaf/kiaf_2023.json',
               'prebuilt_adapter': 'fair_kiaf:adapt',
               'license': 'kiaf.org 공식 아카이브·카탈로그 PDF(static-edge.kiaf.org)·웨이백 스냅샷, robots.txt 허용 확인(2026-10-12). 갤러리 '
                          '계정·사업자등록 엔드포인트와 robots 차단 드라이브 카탈로그는 사용 안 함',
               'sources': []},
 'kiaf_2024': {'series': 'kiaf',
               'year': 2024,
               'label': 'Kiaf SEOUL 2024',
               'title': None,
               'start_date': '2024-09-04',
               'end_date': '2024-09-08',
               'city': 'Seoul',
               'announced': 206,
               'coverage': 'complete',
               'coverage_note': '공식 카탈로그 기준 전 부스 출품작가. 갤러리 206 / 작가 1015. 206 galleries / 21 countries (catalogue '
                                'greetings; dates on the catalogue cover). Booth prefixes A/B (halls), G (Grand '
                                'Ballroom), P (16 booths; per kiaf.org/about-history Kiaf PLUS 2024 had 27 exhibitors '
                                'at The Platz, so P booths are probably Kiaf PLUS, not verified per booth) - kept in '
                                "section 'mai",
               'prebuilt': 'research/kiaf/kiaf_2024.json',
               'prebuilt_adapter': 'fair_kiaf:adapt',
               'license': 'kiaf.org 공식 아카이브·카탈로그 PDF(static-edge.kiaf.org)·웨이백 스냅샷, robots.txt 허용 확인(2026-10-12). 갤러리 '
                          '계정·사업자등록 엔드포인트와 robots 차단 드라이브 카탈로그는 사용 안 함',
               'sources': []},
 'kiaf_2025': {'series': 'kiaf',
               'year': 2025,
               'label': 'Kiaf SEOUL 2025',
               'title': None,
               'start_date': '2025-09-03',
               'end_date': '2025-09-07',
               'city': 'Seoul',
               'announced': 175,
               'coverage': 'complete',
               'coverage_note': '공식 카탈로그 기준 전 부스 출품작가. 갤러리 175 / 작가 905. 175 galleries (kiaf.org/about-history; 176 in '
                                'the pre-fair list announcement). Kiaf PLUS 2025 (19 emerging galleries) was inside '
                                'the main fair; booth prefix G (19 booths) matches that count but is not labelled PLUS '
                                "in the catalogue - kept in 'main'. Catalogue error handled: the Wooson Gallery page p",
               'prebuilt': 'research/kiaf/kiaf_2025.json',
               'prebuilt_adapter': 'fair_kiaf:adapt',
               'license': 'kiaf.org 공식 아카이브·카탈로그 PDF(static-edge.kiaf.org)·웨이백 스냅샷, robots.txt 허용 확인(2026-10-12). 갤러리 '
                          '계정·사업자등록 엔드포인트와 robots 차단 드라이브 카탈로그는 사용 안 함',
               'sources': []},
 'kiaf_2026': {'series': 'kiaf',
               'year': 2026,
               'label': 'Kiaf SEOUL 2026',
               'title': None,
               'start_date': '2026-09-02',
               'end_date': '2026-09-06',
               'city': 'Seoul',
               'announced': 175,
               'coverage': 'partial',
               'coverage_note': '갤러리 목록 + 특별전/하이라이트 작가만 — 부스별 출품작가를 공개한 기계판독 출처 없음. 갤러리 175 / 작가 21. 175 galleries / '
                                '18 countries (Newsis 2026-06-09, secondary; dates/venue from kiaf.org/info). Booth '
                                'codes matched from the floor plan for 175/175 galleries; 175/175 matched to the '
                                'archive DB list. NO per-booth artists: the 2026 catalogue is only linked as a Google '
                                'Drive file (kiaf.org/catalogue -> dr',
               'prebuilt': 'research/kiaf/kiaf_2026.json',
               'prebuilt_adapter': 'fair_kiaf:adapt',
               'license': 'kiaf.org 공식 아카이브·카탈로그 PDF(static-edge.kiaf.org)·웨이백 스냅샷, robots.txt 허용 확인(2026-10-12). 갤러리 '
                          '계정·사업자등록 엔드포인트와 robots 차단 드라이브 카탈로그는 사용 안 함',
               'sources': []}}
