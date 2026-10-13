"""Frieze 2016–2026 (런던·마스터스·뉴욕·LA·서울) — research/frieze/build.py가 웨이백 사본·보도자료 PDF로 조립한
회차 JSON을 적재 (2026-10-13). **내부 연구용 한정** — frieze.com 약관이 서면 허가 없는 수집을 금지(사용자 결정으로 내부 연구용 적재).
제외(빈 회차): frieze_la_2021, frieze_london_2026, frieze_seoul_2026."""

EDITIONS = {'frieze_la_2019': {'series': 'frieze_la',
                    'year': 2019,
                    'label': 'Frieze Los Angeles 2019',
                    'title': None,
                    'start_date': '2019-02-15',
                    'end_date': '2019-02-17',
                    'city': 'Los Angeles',
                    'announced': None,
                    'coverage': 'partial',
                    'coverage_note': '큐레이션 섹션·프로그램 작가만 — 일반 부스 출품작가는 프리즈가 공개하지 않음. 갤러리 70 / 작가 16. [내부 연구용] announced '
                                     "count phrase: 'More than 70 invited galleries' dates confirmed in fetched source "
                                     "text rows by section: {'main': 70, 'Frieze Projects': 16} gallery rows with "
                                     'artists: 0/70 (artists exist only for curated solo/duo sections in press '
                                     'releases; ',
                    'prebuilt': 'research/frieze/frieze_la_2019.json',
                    'license': '내부 연구용 한정(2026-10-13 사용자 결정): frieze.com 약관상 서면 허가 없는 수집 금지 — 웨이백 사본·공식 보도자료 PDF만 사용, '
                               '현 사이트 봇 차단 우회 없음. 외부 공개·상업 이용 금지',
                    'sources': []},
 'frieze_la_2020': {'series': 'frieze_la',
                    'year': 2020,
                    'label': 'Frieze Los Angeles 2020',
                    'title': None,
                    'start_date': '2020-02-14',
                    'end_date': '2020-02-16',
                    'city': 'Los Angeles',
                    'announced': None,
                    'coverage': 'partial',
                    'coverage_note': '갤러리 목록 일부만 아카이브됨. 갤러리 40 / 작가 16. [내부 연구용] dates confirmed in fetched source '
                                     "text rows by section: {None: 40, 'Frieze Projects': 16} gallery rows with "
                                     'artists: 0/40 (artists exist only for curated solo/duo sections in press '
                                     'releases; frieze.com never lists main-section booth artists) INCOMPLE',
                    'prebuilt': 'research/frieze/frieze_la_2020.json',
                    'license': '내부 연구용 한정(2026-10-13 사용자 결정): frieze.com 약관상 서면 허가 없는 수집 금지 — 웨이백 사본·공식 보도자료 PDF만 사용, '
                               '현 사이트 봇 차단 우회 없음. 외부 공개·상업 이용 금지',
                    'sources': []},
 'frieze_la_2022': {'series': 'frieze_la',
                    'year': 2022,
                    'label': 'Frieze Los Angeles 2022',
                    'title': None,
                    'start_date': '2022-02-17',
                    'end_date': '2022-02-20',
                    'city': 'Los Angeles',
                    'announced': None,
                    'coverage': 'partial',
                    'coverage_note': '갤러리 목록만 — 부스 출품작가 비공개. 갤러리 100 / 작가 0. [내부 연구용] section filter pages archived '
                                     "for ['focus la'] (options on page: ['focus la', 'main']); 0 rows left "
                                     "section=null dates confirmed in fetched source text rows by section: {'main': "
                                     "89, 'focus la': 11} gallery rows with artists: 0/100 (artists exist only",
                    'prebuilt': 'research/frieze/frieze_la_2022.json',
                    'license': '내부 연구용 한정(2026-10-13 사용자 결정): frieze.com 약관상 서면 허가 없는 수집 금지 — 웨이백 사본·공식 보도자료 PDF만 사용, '
                               '현 사이트 봇 차단 우회 없음. 외부 공개·상업 이용 금지',
                    'sources': []},
 'frieze_la_2023': {'series': 'frieze_la',
                    'year': 2023,
                    'label': 'Frieze Los Angeles 2023',
                    'title': None,
                    'start_date': '2023-02-16',
                    'end_date': '2023-02-19',
                    'city': 'Los Angeles',
                    'announced': None,
                    'coverage': 'partial',
                    'coverage_note': '갤러리 목록만 — 부스 출품작가 비공개. 갤러리 129 / 작가 0. [내부 연구용] section per gallery unknown (no '
                                     "archived ?section= pages); section=null. Section options on page: ['focus', "
                                     "'main'] dates confirmed in fetched source text rows by section: {None: 128} "
                                     'gallery rows with artists: 0/128 (artists exist only for curated s',
                    'prebuilt': 'research/frieze/frieze_la_2023.json',
                    'license': '내부 연구용 한정(2026-10-13 사용자 결정): frieze.com 약관상 서면 허가 없는 수집 금지 — 웨이백 사본·공식 보도자료 PDF만 사용, '
                               '현 사이트 봇 차단 우회 없음. 외부 공개·상업 이용 금지',
                    'sources': []},
 'frieze_la_2024': {'series': 'frieze_la',
                    'year': 2024,
                    'label': 'Frieze Los Angeles 2024',
                    'title': None,
                    'start_date': '2024-02-29',
                    'end_date': '2024-03-03',
                    'city': 'Los Angeles',
                    'announced': None,
                    'coverage': 'partial',
                    'coverage_note': '갤러리 목록만 — 부스 출품작가 비공개. 갤러리 98 / 작가 0. [내부 연구용] section per gallery unknown (no '
                                     "archived ?section= pages); section=null. Section options on page: ['focus', "
                                     "'galleries'] dates confirmed in fetched source text rows by section: {None: 98} "
                                     'gallery rows with artists: 0/98 (artists exist only for curate',
                    'prebuilt': 'research/frieze/frieze_la_2024.json',
                    'license': '내부 연구용 한정(2026-10-13 사용자 결정): frieze.com 약관상 서면 허가 없는 수집 금지 — 웨이백 사본·공식 보도자료 PDF만 사용, '
                               '현 사이트 봇 차단 우회 없음. 외부 공개·상업 이용 금지',
                    'sources': []},
 'frieze_la_2025': {'series': 'frieze_la',
                    'year': 2025,
                    'label': 'Frieze Los Angeles 2025',
                    'title': None,
                    'start_date': '2025-02-20',
                    'end_date': '2025-02-23',
                    'city': 'Los Angeles',
                    'announced': None,
                    'coverage': 'partial',
                    'coverage_note': '갤러리 목록만 — 부스 출품작가 비공개. 갤러리 97 / 작가 0. [내부 연구용] section per gallery unknown (no '
                                     "archived ?section= pages); section=null. Section options on page: ['focus', "
                                     "'galleries'] dates confirmed in fetched source text rows by section: {None: 96} "
                                     'gallery rows with artists: 0/96 (artists exist only for curate',
                    'prebuilt': 'research/frieze/frieze_la_2025.json',
                    'license': '내부 연구용 한정(2026-10-13 사용자 결정): frieze.com 약관상 서면 허가 없는 수집 금지 — 웨이백 사본·공식 보도자료 PDF만 사용, '
                               '현 사이트 봇 차단 우회 없음. 외부 공개·상업 이용 금지',
                    'sources': []},
 'frieze_la_2026': {'series': 'frieze_la',
                    'year': 2026,
                    'label': 'Frieze Los Angeles 2026',
                    'title': None,
                    'start_date': '2026-02-26',
                    'end_date': '2026-03-01',
                    'city': 'Los Angeles',
                    'announced': None,
                    'coverage': 'partial',
                    'coverage_note': '갤러리 목록만 — 부스 출품작가 비공개. 갤러리 100 / 작가 0. [내부 연구용] section per gallery unknown (no '
                                     "archived ?section= pages); section=null. Section options on page: ['focus', "
                                     "'galleries'] dates confirmed in fetched source text rows by section: {None: 99} "
                                     'gallery rows with artists: 0/99 (artists exist only for curate',
                    'prebuilt': 'research/frieze/frieze_la_2026.json',
                    'license': '내부 연구용 한정(2026-10-13 사용자 결정): frieze.com 약관상 서면 허가 없는 수집 금지 — 웨이백 사본·공식 보도자료 PDF만 사용, '
                               '현 사이트 봇 차단 우회 없음. 외부 공개·상업 이용 금지',
                    'sources': []},
 'frieze_london_2016': {'series': 'frieze_london',
                        'year': 2016,
                        'label': 'Frieze London 2016',
                        'title': None,
                        'start_date': '2016-10-06',
                        'end_date': '2016-10-09',
                        'city': 'London',
                        'announced': None,
                        'coverage': 'partial',
                        'coverage_note': '큐레이션 섹션·프로그램 작가만 — 일반 부스 출품작가는 프리즈가 공개하지 않음. 갤러리 168 / 작가 29. [내부 연구용] booth '
                                         'numbers from the printed fair guide index for 151 rows announced count '
                                         "phrase: 'more than 160 of the world’s leading galleries' dates confirmed in "
                                         "fetched source text rows by section: {'main': 118, 'Focus': 37, 'Live': 5, "
                                         "'The Nineties': 11, 'F",
                        'prebuilt': 'research/frieze/frieze_london_2016.json',
                        'license': '내부 연구용 한정(2026-10-13 사용자 결정): frieze.com 약관상 서면 허가 없는 수집 금지 — 웨이백 사본·공식 보도자료 PDF만 '
                                   '사용, 현 사이트 봇 차단 우회 없음. 외부 공개·상업 이용 금지',
                        'sources': []},
 'frieze_london_2017': {'series': 'frieze_london',
                        'year': 2017,
                        'label': 'Frieze London 2017',
                        'title': None,
                        'start_date': '2017-10-05',
                        'end_date': '2017-10-08',
                        'city': 'London',
                        'announced': None,
                        'coverage': 'partial',
                        'coverage_note': '큐레이션 섹션·프로그램 작가만 — 일반 부스 출품작가는 프리즈가 공개하지 않음. 갤러리 165 / 작가 47. [내부 연구용] '
                                         "announced count phrase: 'More than 160 leading galleries' dates confirmed in "
                                         "fetched source text rows by section: {'main': 117, 'Focus': 34, 'Sex Work': "
                                         "12, 'Live': 4, 'Frieze Projects': 9, 'Frieze Sculpture': 25, 'Frieze Artist "
                                         "Award': 1} gallery ro",
                        'prebuilt': 'research/frieze/frieze_london_2017.json',
                        'license': '내부 연구용 한정(2026-10-13 사용자 결정): frieze.com 약관상 서면 허가 없는 수집 금지 — 웨이백 사본·공식 보도자료 PDF만 '
                                   '사용, 현 사이트 봇 차단 우회 없음. 외부 공개·상업 이용 금지',
                        'sources': []},
 'frieze_london_2018': {'series': 'frieze_london',
                        'year': 2018,
                        'label': 'Frieze London 2018',
                        'title': None,
                        'start_date': '2018-10-05',
                        'end_date': '2018-10-07',
                        'city': 'London',
                        'announced': None,
                        'coverage': 'partial',
                        'coverage_note': '큐레이션 섹션·프로그램 작가만 — 일반 부스 출품작가는 프리즈가 공개하지 않음. 갤러리 158 / 작가 43. [내부 연구용] '
                                         "announced count phrase: 'around 160 galleries' dates confirmed in fetched "
                                         "source text rows by section: {'main': 115, 'Focus': 33, 'Social Work': 9, "
                                         "'Live': 11, 'Frieze Sculpture': 26} gallery rows with artists: 20/168 "
                                         '(artists exist only for curated ',
                        'prebuilt': 'research/frieze/frieze_london_2018.json',
                        'license': '내부 연구용 한정(2026-10-13 사용자 결정): frieze.com 약관상 서면 허가 없는 수집 금지 — 웨이백 사본·공식 보도자료 PDF만 '
                                   '사용, 현 사이트 봇 차단 우회 없음. 외부 공개·상업 이용 금지',
                        'sources': []},
 'frieze_london_2019': {'series': 'frieze_london',
                        'year': 2019,
                        'label': 'Frieze London 2019',
                        'title': None,
                        'start_date': '2019-10-03',
                        'end_date': '2019-10-06',
                        'city': 'London',
                        'announced': None,
                        'coverage': 'partial',
                        'coverage_note': '큐레이션 섹션·프로그램 작가만 — 일반 부스 출품작가는 프리즈가 공개하지 않음. 갤러리 163 / 작가 31. [내부 연구용] '
                                         "announced count phrase: 'more than 160 galleries' dates entered from Frieze "
                                         'announcements (not found verbatim in the fetched source) rows by section: '
                                         "{'main': 122, 'Woven': 8, 'Focus': 33, 'Frieze Sculpture': 23} gallery rows "
                                         'with artists: 8/163 (art',
                        'prebuilt': 'research/frieze/frieze_london_2019.json',
                        'license': '내부 연구용 한정(2026-10-13 사용자 결정): frieze.com 약관상 서면 허가 없는 수집 금지 — 웨이백 사본·공식 보도자료 PDF만 '
                                   '사용, 현 사이트 봇 차단 우회 없음. 외부 공개·상업 이용 금지',
                        'sources': []},
 'frieze_london_2020': {'series': 'frieze_london',
                        'year': 2020,
                        'label': 'Frieze London 2020',
                        'title': None,
                        'start_date': '2020-10-09',
                        'end_date': '2020-10-16',
                        'city': 'London',
                        'announced': None,
                        'coverage': 'partial',
                        'coverage_note': '큐레이션 섹션·프로그램 작가만 — 일반 부스 출품작가는 프리즈가 공개하지 않음. 갤러리 159 / 작가 1. [내부 연구용] '
                                         'online-only edition (Frieze Viewing Room, 9-16 Oct 2020); list = online '
                                         "exhibitors section filter pages archived for ['focus'] (options on page: "
                                         "['focus', 'main', 'possessions']); 126 rows left section=null dates entered "
                                         'from Frieze announcements (no',
                        'prebuilt': 'research/frieze/frieze_london_2020.json',
                        'license': '내부 연구용 한정(2026-10-13 사용자 결정): frieze.com 약관상 서면 허가 없는 수집 금지 — 웨이백 사본·공식 보도자료 PDF만 '
                                   '사용, 현 사이트 봇 차단 우회 없음. 외부 공개·상업 이용 금지',
                        'sources': []},
 'frieze_london_2021': {'series': 'frieze_london',
                        'year': 2021,
                        'label': 'Frieze London 2021',
                        'title': None,
                        'start_date': '2021-10-13',
                        'end_date': '2021-10-17',
                        'city': 'London',
                        'announced': None,
                        'coverage': 'partial',
                        'coverage_note': '갤러리 목록만 — 부스 출품작가 비공개. 갤러리 159 / 작가 0. [내부 연구용] section per gallery unknown '
                                         '(no archived ?section= pages); section=null. Section options on page: '
                                         "['editions', 'focus', 'main', 'unworlding'] dates confirmed in fetched "
                                         'source text rows by section: {None: 158} gallery rows with artists: 0/158 '
                                         '(artist',
                        'prebuilt': 'research/frieze/frieze_london_2021.json',
                        'license': '내부 연구용 한정(2026-10-13 사용자 결정): frieze.com 약관상 서면 허가 없는 수집 금지 — 웨이백 사본·공식 보도자료 PDF만 '
                                   '사용, 현 사이트 봇 차단 우회 없음. 외부 공개·상업 이용 금지',
                        'sources': []},
 'frieze_london_2022': {'series': 'frieze_london',
                        'year': 2022,
                        'label': 'Frieze London 2022',
                        'title': None,
                        'start_date': '2022-10-12',
                        'end_date': '2022-10-16',
                        'city': 'London',
                        'announced': None,
                        'coverage': 'partial',
                        'coverage_note': '큐레이션 섹션·프로그램 작가만 — 일반 부스 출품작가는 프리즈가 공개하지 않음. 갤러리 167 / 작가 1. [내부 연구용] '
                                         'section filter pages archived for [\'editions\', "indra\'s net"] (options on '
                                         'page: [\'editions\', \'focus\', "indra\'s net", \'main\', \'non-profit\']); '
                                         '151 rows left section=null dates confirmed in fetched source text rows by '
                                         "section: {None: 151, 'editions': 5,",
                        'prebuilt': 'research/frieze/frieze_london_2022.json',
                        'license': '내부 연구용 한정(2026-10-13 사용자 결정): frieze.com 약관상 서면 허가 없는 수집 금지 — 웨이백 사본·공식 보도자료 PDF만 '
                                   '사용, 현 사이트 봇 차단 우회 없음. 외부 공개·상업 이용 금지',
                        'sources': []},
 'frieze_london_2023': {'series': 'frieze_london',
                        'year': 2023,
                        'label': 'Frieze London 2023',
                        'title': None,
                        'start_date': '2023-10-11',
                        'end_date': '2023-10-15',
                        'city': 'London',
                        'announced': None,
                        'coverage': 'partial',
                        'coverage_note': '큐레이션 섹션·프로그램 작가만 — 일반 부스 출품작가는 프리즈가 공개하지 않음. 갤러리 167 / 작가 1. [내부 연구용] '
                                         'section per gallery unknown (no archived ?section= pages); section=null. '
                                         "Section options on page: ['artist to artist', 'editions', 'focus', 'main'] "
                                         "dates confirmed in fetched source text rows by section: {None: 166, 'Frieze "
                                         "Artist Award': 1} gallery ",
                        'prebuilt': 'research/frieze/frieze_london_2023.json',
                        'license': '내부 연구용 한정(2026-10-13 사용자 결정): frieze.com 약관상 서면 허가 없는 수집 금지 — 웨이백 사본·공식 보도자료 PDF만 '
                                   '사용, 현 사이트 봇 차단 우회 없음. 외부 공개·상업 이용 금지',
                        'sources': []},
 'frieze_london_2024': {'series': 'frieze_london',
                        'year': 2024,
                        'label': 'Frieze London 2024',
                        'title': None,
                        'start_date': '2024-10-09',
                        'end_date': '2024-10-13',
                        'city': 'London',
                        'announced': None,
                        'coverage': 'partial',
                        'coverage_note': '갤러리 목록만 — 부스 출품작가 비공개. 갤러리 170 / 작가 0. [내부 연구용] section per gallery unknown '
                                         '(no archived ?section= pages); section=null. Section options on page: '
                                         "['artist-to-artist', 'editions', 'focus', 'galleries', 'smoke'] dates "
                                         'confirmed in fetched source text rows by section: {None: 169} gallery rows '
                                         'with ar',
                        'prebuilt': 'research/frieze/frieze_london_2024.json',
                        'license': '내부 연구용 한정(2026-10-13 사용자 결정): frieze.com 약관상 서면 허가 없는 수집 금지 — 웨이백 사본·공식 보도자료 PDF만 '
                                   '사용, 현 사이트 봇 차단 우회 없음. 외부 공개·상업 이용 금지',
                        'sources': []},
 'frieze_london_2025': {'series': 'frieze_london',
                        'year': 2025,
                        'label': 'Frieze London 2025',
                        'title': None,
                        'start_date': '2025-10-15',
                        'end_date': '2025-10-19',
                        'city': 'London',
                        'announced': None,
                        'coverage': 'partial',
                        'coverage_note': '갤러리 목록만 — 부스 출품작가 비공개. 갤러리 169 / 작가 0. [내부 연구용] section per gallery unknown '
                                         '(no archived ?section= pages); section=null. Section options on page: '
                                         "['artist-to-artist', 'echoes in the present', 'editions', 'focus', "
                                         "'galleries'] dates confirmed in fetched source text rows by section: {None: "
                                         '168} gall',
                        'prebuilt': 'research/frieze/frieze_london_2025.json',
                        'license': '내부 연구용 한정(2026-10-13 사용자 결정): frieze.com 약관상 서면 허가 없는 수집 금지 — 웨이백 사본·공식 보도자료 PDF만 '
                                   '사용, 현 사이트 봇 차단 우회 없음. 외부 공개·상업 이용 금지',
                        'sources': []},
 'frieze_masters_2016': {'series': 'frieze_masters',
                         'year': 2016,
                         'label': 'Frieze Masters 2016',
                         'title': None,
                         'start_date': '2016-10-06',
                         'end_date': '2016-10-09',
                         'city': 'London',
                         'announced': None,
                         'coverage': 'partial',
                         'coverage_note': '큐레이션 섹션·프로그램 작가만 — 일반 부스 출품작가는 프리즈가 공개하지 않음. 갤러리 135 / 작가 21. [내부 연구용] '
                                          'booth numbers from the printed fair guide index for 110 rows dates '
                                          "confirmed in fetched source text rows by section: {'main': 106, "
                                          "'Collections': 8, 'Spotlight': 21} gallery rows with artists: 21/135 "
                                          '(artists exist only for curated solo/duo sections ',
                         'prebuilt': 'research/frieze/frieze_masters_2016.json',
                         'license': '내부 연구용 한정(2026-10-13 사용자 결정): frieze.com 약관상 서면 허가 없는 수집 금지 — 웨이백 사본·공식 보도자료 PDF만 '
                                    '사용, 현 사이트 봇 차단 우회 없음. 외부 공개·상업 이용 금지',
                         'sources': []},
 'frieze_masters_2017': {'series': 'frieze_masters',
                         'year': 2017,
                         'label': 'Frieze Masters 2017',
                         'title': None,
                         'start_date': '2017-10-05',
                         'end_date': '2017-10-08',
                         'city': 'London',
                         'announced': None,
                         'coverage': 'partial',
                         'coverage_note': '큐레이션 섹션·프로그램 작가만 — 일반 부스 출품작가는 프리즈가 공개하지 않음. 갤러리 138 / 작가 21. [내부 연구용] '
                                          "dates confirmed in fetched source text rows by section: {'main': 109, "
                                          "'Collections': 7, 'Spotlight': 21} gallery rows with artists: 21/137 "
                                          '(artists exist only for curated solo/duo sections in press releases; '
                                          'frieze.com never lists main-section booth ',
                         'prebuilt': 'research/frieze/frieze_masters_2017.json',
                         'license': '내부 연구용 한정(2026-10-13 사용자 결정): frieze.com 약관상 서면 허가 없는 수집 금지 — 웨이백 사본·공식 보도자료 PDF만 '
                                    '사용, 현 사이트 봇 차단 우회 없음. 외부 공개·상업 이용 금지',
                         'sources': []},
 'frieze_masters_2018': {'series': 'frieze_masters',
                         'year': 2018,
                         'label': 'Frieze Masters 2018',
                         'title': None,
                         'start_date': '2018-10-05',
                         'end_date': '2018-10-07',
                         'city': 'London',
                         'announced': None,
                         'coverage': 'partial',
                         'coverage_note': '갤러리 목록 일부만 아카이브됨. 갤러리 20 / 작가 0. [내부 연구용] dates entered from Frieze '
                                          'announcements (not found verbatim in the fetched source) rows by section: '
                                          '{None: 20} gallery rows with artists: 0/20 (artists exist only for curated '
                                          'solo/duo sections in press releases; frieze.com never lists main-section bo',
                         'prebuilt': 'research/frieze/frieze_masters_2018.json',
                         'license': '내부 연구용 한정(2026-10-13 사용자 결정): frieze.com 약관상 서면 허가 없는 수집 금지 — 웨이백 사본·공식 보도자료 PDF만 '
                                    '사용, 현 사이트 봇 차단 우회 없음. 외부 공개·상업 이용 금지',
                         'sources': []},
 'frieze_masters_2019': {'series': 'frieze_masters',
                         'year': 2019,
                         'label': 'Frieze Masters 2019',
                         'title': None,
                         'start_date': '2019-10-03',
                         'end_date': '2019-10-06',
                         'city': 'London',
                         'announced': None,
                         'coverage': 'partial',
                         'coverage_note': '큐레이션 섹션·프로그램 작가만 — 일반 부스 출품작가는 프리즈가 공개하지 않음. 갤러리 133 / 작가 23. [내부 연구용] '
                                          'dates entered from Frieze announcements (not found verbatim in the fetched '
                                          "source) rows by section: {'main': 102, 'Spotlight': 24, 'Collections': 8} "
                                          'gallery rows with artists: 24/134 (artists exist only for curated solo/duo '
                                          'sections in press releases',
                         'prebuilt': 'research/frieze/frieze_masters_2019.json',
                         'license': '내부 연구용 한정(2026-10-13 사용자 결정): frieze.com 약관상 서면 허가 없는 수집 금지 — 웨이백 사본·공식 보도자료 PDF만 '
                                    '사용, 현 사이트 봇 차단 우회 없음. 외부 공개·상업 이용 금지',
                         'sources': []},
 'frieze_masters_2020': {'series': 'frieze_masters',
                         'year': 2020,
                         'label': 'Frieze Masters 2020',
                         'title': None,
                         'start_date': '2020-10-09',
                         'end_date': '2020-10-16',
                         'city': 'London',
                         'announced': None,
                         'coverage': 'partial',
                         'coverage_note': '갤러리 목록만 — 부스 출품작가 비공개. 갤러리 106 / 작가 0. [내부 연구용] online-only edition (Frieze '
                                          'Viewing Room, 9-16 Oct 2020); list = online exhibitors section per gallery '
                                          'unknown (no archived ?section= pages); section=null. Section options on '
                                          "page: ['main', 'spotlight'] dates entered from Frieze announcements (not fo",
                         'prebuilt': 'research/frieze/frieze_masters_2020.json',
                         'license': '내부 연구용 한정(2026-10-13 사용자 결정): frieze.com 약관상 서면 허가 없는 수집 금지 — 웨이백 사본·공식 보도자료 PDF만 '
                                    '사용, 현 사이트 봇 차단 우회 없음. 외부 공개·상업 이용 금지',
                         'sources': []},
 'frieze_masters_2021': {'series': 'frieze_masters',
                         'year': 2021,
                         'label': 'Frieze Masters 2021',
                         'title': None,
                         'start_date': '2021-10-13',
                         'end_date': '2021-10-17',
                         'city': 'London',
                         'announced': None,
                         'coverage': 'partial',
                         'coverage_note': '갤러리 목록만 — 부스 출품작가 비공개. 갤러리 134 / 작가 0. [내부 연구용] section per gallery unknown '
                                          '(no archived ?section= pages); section=null. Section options on page: '
                                          "['main', 'spotlight', 'stand out'] dates confirmed in fetched source text "
                                          'rows by section: {None: 132} gallery rows with artists: 0/132 (artists '
                                          'exist o',
                         'prebuilt': 'research/frieze/frieze_masters_2021.json',
                         'license': '내부 연구용 한정(2026-10-13 사용자 결정): frieze.com 약관상 서면 허가 없는 수집 금지 — 웨이백 사본·공식 보도자료 PDF만 '
                                    '사용, 현 사이트 봇 차단 우회 없음. 외부 공개·상업 이용 금지',
                         'sources': []},
 'frieze_masters_2022': {'series': 'frieze_masters',
                         'year': 2022,
                         'label': 'Frieze Masters 2022',
                         'title': None,
                         'start_date': '2022-10-12',
                         'end_date': '2022-10-16',
                         'city': 'London',
                         'announced': None,
                         'coverage': 'partial',
                         'coverage_note': '갤러리 목록만 — 부스 출품작가 비공개. 갤러리 130 / 작가 0. [내부 연구용] section filter pages '
                                          "archived for ['main', 'spotlight', 'stand out'] (options on page: ['focus', "
                                          "'main', 'spotlight', 'stand out']); 2 rows left section=null dates "
                                          "confirmed in fetched source text rows by section: {'main': 95, 'spotlight': "
                                          '28, None: ',
                         'prebuilt': 'research/frieze/frieze_masters_2022.json',
                         'license': '내부 연구용 한정(2026-10-13 사용자 결정): frieze.com 약관상 서면 허가 없는 수집 금지 — 웨이백 사본·공식 보도자료 PDF만 '
                                    '사용, 현 사이트 봇 차단 우회 없음. 외부 공개·상업 이용 금지',
                         'sources': []},
 'frieze_masters_2023': {'series': 'frieze_masters',
                         'year': 2023,
                         'label': 'Frieze Masters 2023',
                         'title': None,
                         'start_date': '2023-10-11',
                         'end_date': '2023-10-15',
                         'city': 'London',
                         'announced': None,
                         'coverage': 'partial',
                         'coverage_note': '갤러리 목록만 — 부스 출품작가 비공개. 갤러리 137 / 작가 0. [내부 연구용] section per gallery unknown '
                                          '(no archived ?section= pages); section=null. Section options on page: '
                                          "['main', 'modern women', 'spotlight', 'stand out', 'studio'] dates "
                                          'confirmed in fetched source text rows by section: {None: 135} gallery rows '
                                          'with artis',
                         'prebuilt': 'research/frieze/frieze_masters_2023.json',
                         'license': '내부 연구용 한정(2026-10-13 사용자 결정): frieze.com 약관상 서면 허가 없는 수집 금지 — 웨이백 사본·공식 보도자료 PDF만 '
                                    '사용, 현 사이트 봇 차단 우회 없음. 외부 공개·상업 이용 금지',
                         'sources': []},
 'frieze_masters_2024': {'series': 'frieze_masters',
                         'year': 2024,
                         'label': 'Frieze Masters 2024',
                         'title': None,
                         'start_date': '2024-10-09',
                         'end_date': '2024-10-13',
                         'city': 'London',
                         'announced': None,
                         'coverage': 'partial',
                         'coverage_note': '갤러리 목록만 — 부스 출품작가 비공개. 갤러리 133 / 작가 0. [내부 연구용] section per gallery unknown '
                                          '(no archived ?section= pages); section=null. Section options on page: '
                                          "['galleries', 'spotlight', 'studio'] dates confirmed in fetched source text "
                                          'rows by section: {None: 131} gallery rows with artists: 0/131 (artists '
                                          'exist',
                         'prebuilt': 'research/frieze/frieze_masters_2024.json',
                         'license': '내부 연구용 한정(2026-10-13 사용자 결정): frieze.com 약관상 서면 허가 없는 수집 금지 — 웨이백 사본·공식 보도자료 PDF만 '
                                    '사용, 현 사이트 봇 차단 우회 없음. 외부 공개·상업 이용 금지',
                         'sources': []},
 'frieze_masters_2025': {'series': 'frieze_masters',
                         'year': 2025,
                         'label': 'Frieze Masters 2025',
                         'title': None,
                         'start_date': '2025-10-15',
                         'end_date': '2025-10-19',
                         'city': 'London',
                         'announced': None,
                         'coverage': 'partial',
                         'coverage_note': '갤러리 목록만 — 부스 출품작가 비공개. 갤러리 138 / 작가 0. [내부 연구용] section per gallery unknown '
                                          '(no archived ?section= pages); section=null. Section options on page: '
                                          "['galleries', 'reflections', 'spotlight', 'studio'] dates confirmed in "
                                          'fetched source text rows by section: {None: 136} gallery rows with artists: '
                                          '0/136',
                         'prebuilt': 'research/frieze/frieze_masters_2025.json',
                         'license': '내부 연구용 한정(2026-10-13 사용자 결정): frieze.com 약관상 서면 허가 없는 수집 금지 — 웨이백 사본·공식 보도자료 PDF만 '
                                    '사용, 현 사이트 봇 차단 우회 없음. 외부 공개·상업 이용 금지',
                         'sources': []},
 'frieze_masters_2026': {'series': 'frieze_masters',
                         'year': 2026,
                         'label': 'Frieze Masters 2026',
                         'title': None,
                         'start_date': '2026-10-14',
                         'end_date': '2026-10-18',
                         'city': 'London',
                         'announced': None,
                         'coverage': 'partial',
                         'coverage_note': '갤러리 목록만 — 부스 출품작가 비공개. 갤러리 143 / 작가 0. [내부 연구용] section per gallery unknown '
                                          '(no archived ?section= pages); section=null. Section options on page: '
                                          "['galleries', 'queering modernism', 'reflections', 'spotlight'] dates "
                                          'confirmed in fetched source text rows by section: {None: 141} gallery rows '
                                          'with ar',
                         'prebuilt': 'research/frieze/frieze_masters_2026.json',
                         'license': '내부 연구용 한정(2026-10-13 사용자 결정): frieze.com 약관상 서면 허가 없는 수집 금지 — 웨이백 사본·공식 보도자료 PDF만 '
                                    '사용, 현 사이트 봇 차단 우회 없음. 외부 공개·상업 이용 금지',
                         'sources': []},
 'frieze_ny_2016': {'series': 'frieze_ny',
                    'year': 2016,
                    'label': 'Frieze New York 2016',
                    'title': None,
                    'start_date': '2016-05-05',
                    'end_date': '2016-05-08',
                    'city': 'New York',
                    'announced': None,
                    'coverage': 'partial',
                    'coverage_note': '큐레이션 섹션·프로그램 작가만 — 일반 부스 출품작가는 프리즈가 공개하지 않음. 갤러리 204 / 작가 39. [내부 연구용] announced '
                                     "count phrase: 'more than 200 international galleries' dates confirmed in fetched "
                                     "source text rows by section: {'main': 131, 'Focus': 32, 'Frame': 18, "
                                     "'Spotlight': 20, 'Non-Profits': 3} gallery rows with artists: 38/204 (artists "
                                     'exist only f',
                    'prebuilt': 'research/frieze/frieze_ny_2016.json',
                    'license': '내부 연구용 한정(2026-10-13 사용자 결정): frieze.com 약관상 서면 허가 없는 수집 금지 — 웨이백 사본·공식 보도자료 PDF만 사용, '
                               '현 사이트 봇 차단 우회 없음. 외부 공개·상업 이용 금지',
                    'sources': []},
 'frieze_ny_2017': {'series': 'frieze_ny',
                    'year': 2017,
                    'label': 'Frieze New York 2017',
                    'title': None,
                    'start_date': '2017-05-05',
                    'end_date': '2017-05-07',
                    'city': 'New York',
                    'announced': None,
                    'coverage': 'partial',
                    'coverage_note': '큐레이션 섹션·프로그램 작가만 — 일반 부스 출품작가는 프리즈가 공개하지 않음. 갤러리 201 / 작가 45. [내부 연구용] announced '
                                     "count phrase: 'more than 200 galleries' dates confirmed in fetched source text "
                                     "rows by section: {'main': 124, 'Focus': 30, 'Frame': 16, 'Spotlight': 31} "
                                     'gallery rows with artists: 47/201 (artists exist only for curated solo/duo '
                                     'sections in ',
                    'prebuilt': 'research/frieze/frieze_ny_2017.json',
                    'license': '내부 연구용 한정(2026-10-13 사용자 결정): frieze.com 약관상 서면 허가 없는 수집 금지 — 웨이백 사본·공식 보도자료 PDF만 사용, '
                               '현 사이트 봇 차단 우회 없음. 외부 공개·상업 이용 금지',
                    'sources': []},
 'frieze_ny_2018': {'series': 'frieze_ny',
                    'year': 2018,
                    'label': 'Frieze New York 2018',
                    'title': None,
                    'start_date': '2018-05-04',
                    'end_date': '2018-05-06',
                    'city': 'New York',
                    'announced': None,
                    'coverage': 'partial',
                    'coverage_note': '큐레이션 섹션·프로그램 작가만 — 일반 부스 출품작가는 프리즈가 공개하지 않음. 갤러리 192 / 작가 53. [내부 연구용] announced '
                                     "count phrase: 'more than 190 galleries' dates confirmed in fetched source text "
                                     "rows by section: {'main': 113, 'Focus': 26, 'Frame': 19, 'Spotlight': 34, "
                                     "'Non-Profits': 2, 'Frieze Artist Award': 1} gallery rows with artists: 53/194 "
                                     '(artists ',
                    'prebuilt': 'research/frieze/frieze_ny_2018.json',
                    'license': '내부 연구용 한정(2026-10-13 사용자 결정): frieze.com 약관상 서면 허가 없는 수집 금지 — 웨이백 사본·공식 보도자료 PDF만 사용, '
                               '현 사이트 봇 차단 우회 없음. 외부 공개·상업 이용 금지',
                    'sources': []},
 'frieze_ny_2019': {'series': 'frieze_ny',
                    'year': 2019,
                    'label': 'Frieze New York 2019',
                    'title': None,
                    'start_date': '2019-05-02',
                    'end_date': '2019-05-05',
                    'city': 'New York',
                    'announced': None,
                    'coverage': 'partial',
                    'coverage_note': '큐레이션 섹션·프로그램 작가만 — 일반 부스 출품작가는 프리즈가 공개하지 않음. 갤러리 186 / 작가 73. [내부 연구용] dates '
                                     'entered from Frieze announcements (not found verbatim in the fetched source) '
                                     "rows by section: {'main': 93, 'Focus': 28, 'Frame': 20, 'Spotlight': 33, "
                                     "'Non-Profits': 2, 'Diálogos': 14, 'Just Above Midtown': 7, 'Frieze Artist "
                                     "Award': 1} 21 curate",
                    'prebuilt': 'research/frieze/frieze_ny_2019.json',
                    'license': '내부 연구용 한정(2026-10-13 사용자 결정): frieze.com 약관상 서면 허가 없는 수집 금지 — 웨이백 사본·공식 보도자료 PDF만 사용, '
                               '현 사이트 봇 차단 우회 없음. 외부 공개·상업 이용 금지',
                    'sources': []},
 'frieze_ny_2020': {'series': 'frieze_ny',
                    'year': 2020,
                    'label': 'Frieze New York 2020',
                    'title': None,
                    'start_date': '2020-05-08',
                    'end_date': '2020-05-15',
                    'city': 'New York',
                    'announced': None,
                    'coverage': 'partial',
                    'coverage_note': '큐레이션 섹션·프로그램 작가만 — 일반 부스 출품작가는 프리즈가 공개하지 않음. 갤러리 203 / 작가 58. [내부 연구용] physical '
                                     'fair cancelled (COVID); held online in Frieze Viewing Room 8-15 May 2020; source '
                                     "is the Jan 2020 'galleries announced' release (pre-cancellation list) dates "
                                     'entered from Frieze announcements (not found verbatim in the fetched source) '
                                     'rows by',
                    'prebuilt': 'research/frieze/frieze_ny_2020.json',
                    'license': '내부 연구용 한정(2026-10-13 사용자 결정): frieze.com 약관상 서면 허가 없는 수집 금지 — 웨이백 사본·공식 보도자료 PDF만 사용, '
                               '현 사이트 봇 차단 우회 없음. 외부 공개·상업 이용 금지',
                    'sources': []},
 'frieze_ny_2021': {'series': 'frieze_ny',
                    'year': 2021,
                    'label': 'Frieze New York 2021',
                    'title': None,
                    'start_date': '2021-05-05',
                    'end_date': '2021-05-09',
                    'city': 'New York',
                    'announced': None,
                    'coverage': 'partial',
                    'coverage_note': '큐레이션 섹션·프로그램 작가만 — 일반 부스 출품작가는 프리즈가 공개하지 않음. 갤러리 64 / 작가 1. [내부 연구용] section per '
                                     'gallery unknown (no archived ?section= pages); section=null. Section options on '
                                     "page: ['frame', 'main'] dates confirmed in fetched source text rows by section: "
                                     "{None: 64, 'Frieze Artist Award': 1} gallery rows with artists: 0/64 (artists ",
                    'prebuilt': 'research/frieze/frieze_ny_2021.json',
                    'license': '내부 연구용 한정(2026-10-13 사용자 결정): frieze.com 약관상 서면 허가 없는 수집 금지 — 웨이백 사본·공식 보도자료 PDF만 사용, '
                               '현 사이트 봇 차단 우회 없음. 외부 공개·상업 이용 금지',
                    'sources': []},
 'frieze_ny_2022': {'series': 'frieze_ny',
                    'year': 2022,
                    'label': 'Frieze New York 2022',
                    'title': None,
                    'start_date': '2022-05-18',
                    'end_date': '2022-05-22',
                    'city': 'New York',
                    'announced': None,
                    'coverage': 'partial',
                    'coverage_note': '갤러리 목록만 — 부스 출품작가 비공개. 갤러리 66 / 작가 0. [내부 연구용] section per gallery unknown (no '
                                     "archived ?section= pages); section=null. Section options on page: ['frame', "
                                     "'main'] dates confirmed in fetched source text rows by section: {None: 66} "
                                     'gallery rows with artists: 0/66 (artists exist only for curated sol',
                    'prebuilt': 'research/frieze/frieze_ny_2022.json',
                    'license': '내부 연구용 한정(2026-10-13 사용자 결정): frieze.com 약관상 서면 허가 없는 수집 금지 — 웨이백 사본·공식 보도자료 PDF만 사용, '
                               '현 사이트 봇 차단 우회 없음. 외부 공개·상업 이용 금지',
                    'sources': []},
 'frieze_ny_2023': {'series': 'frieze_ny',
                    'year': 2023,
                    'label': 'Frieze New York 2023',
                    'title': None,
                    'start_date': '2023-05-17',
                    'end_date': '2023-05-21',
                    'city': 'New York',
                    'announced': None,
                    'coverage': 'partial',
                    'coverage_note': '갤러리 목록만 — 부스 출품작가 비공개. 갤러리 68 / 작가 0. [내부 연구용] section per gallery unknown (no '
                                     "archived ?section= pages); section=null. Section options on page: ['focus', "
                                     "'main'] dates confirmed in fetched source text rows by section: {None: 68} "
                                     'gallery rows with artists: 0/68 (artists exist only for curated sol',
                    'prebuilt': 'research/frieze/frieze_ny_2023.json',
                    'license': '내부 연구용 한정(2026-10-13 사용자 결정): frieze.com 약관상 서면 허가 없는 수집 금지 — 웨이백 사본·공식 보도자료 PDF만 사용, '
                               '현 사이트 봇 차단 우회 없음. 외부 공개·상업 이용 금지',
                    'sources': []},
 'frieze_ny_2024': {'series': 'frieze_ny',
                    'year': 2024,
                    'label': 'Frieze New York 2024',
                    'title': None,
                    'start_date': '2024-05-01',
                    'end_date': '2024-05-05',
                    'city': 'New York',
                    'announced': None,
                    'coverage': 'partial',
                    'coverage_note': '갤러리 목록만 — 부스 출품작가 비공개. 갤러리 68 / 작가 0. [내부 연구용] section per gallery unknown (no '
                                     "archived ?section= pages); section=null. Section options on page: ['focus', "
                                     "'galleries'] announced count phrase: 'more than 60 galleries' dates confirmed in "
                                     'fetched source text rows by section: {None: 68} gallery rows ',
                    'prebuilt': 'research/frieze/frieze_ny_2024.json',
                    'license': '내부 연구용 한정(2026-10-13 사용자 결정): frieze.com 약관상 서면 허가 없는 수집 금지 — 웨이백 사본·공식 보도자료 PDF만 사용, '
                               '현 사이트 봇 차단 우회 없음. 외부 공개·상업 이용 금지',
                    'sources': []},
 'frieze_ny_2025': {'series': 'frieze_ny',
                    'year': 2025,
                    'label': 'Frieze New York 2025',
                    'title': None,
                    'start_date': '2025-05-07',
                    'end_date': '2025-05-11',
                    'city': 'New York',
                    'announced': None,
                    'coverage': 'partial',
                    'coverage_note': '갤러리 목록만 — 부스 출품작가 비공개. 갤러리 66 / 작가 0. [내부 연구용] section per gallery unknown (no '
                                     "archived ?section= pages); section=null. Section options on page: ['focus', "
                                     "'galleries'] dates confirmed in fetched source text rows by section: {None: 66} "
                                     'gallery rows with artists: 0/66 (artists exist only for curate',
                    'prebuilt': 'research/frieze/frieze_ny_2025.json',
                    'license': '내부 연구용 한정(2026-10-13 사용자 결정): frieze.com 약관상 서면 허가 없는 수집 금지 — 웨이백 사본·공식 보도자료 PDF만 사용, '
                               '현 사이트 봇 차단 우회 없음. 외부 공개·상업 이용 금지',
                    'sources': []},
 'frieze_ny_2026': {'series': 'frieze_ny',
                    'year': 2026,
                    'label': 'Frieze New York 2026',
                    'title': None,
                    'start_date': '2026-05-13',
                    'end_date': '2026-05-17',
                    'city': 'New York',
                    'announced': None,
                    'coverage': 'partial',
                    'coverage_note': '갤러리 목록만 — 부스 출품작가 비공개. 갤러리 68 / 작가 0. [내부 연구용] section per gallery unknown (no '
                                     "archived ?section= pages); section=null. Section options on page: ['focus', "
                                     "'galleries'] dates confirmed in fetched source text rows by section: {None: 68} "
                                     'gallery rows with artists: 0/68 (artists exist only for curate',
                    'prebuilt': 'research/frieze/frieze_ny_2026.json',
                    'license': '내부 연구용 한정(2026-10-13 사용자 결정): frieze.com 약관상 서면 허가 없는 수집 금지 — 웨이백 사본·공식 보도자료 PDF만 사용, '
                               '현 사이트 봇 차단 우회 없음. 외부 공개·상업 이용 금지',
                    'sources': []},
 'frieze_seoul_2022': {'series': 'frieze_seoul',
                       'year': 2022,
                       'label': 'Frieze Seoul 2022',
                       'title': None,
                       'start_date': '2022-09-02',
                       'end_date': '2022-09-05',
                       'city': 'Seoul',
                       'announced': None,
                       'coverage': 'partial',
                       'coverage_note': '갤러리 목록만 — 부스 출품작가 비공개. 갤러리 119 / 작가 0. [내부 연구용] section filter pages archived '
                                        "for ['focus asia', 'frieze masters'] (options on page: ['focus asia', 'frieze "
                                        "masters', 'main']); 0 rows left section=null dates confirmed in fetched "
                                        "source text rows by section: {'frieze masters': 18, 'main': 91, 'focus",
                       'prebuilt': 'research/frieze/frieze_seoul_2022.json',
                       'license': '내부 연구용 한정(2026-10-13 사용자 결정): frieze.com 약관상 서면 허가 없는 수집 금지 — 웨이백 사본·공식 보도자료 PDF만 '
                                  '사용, 현 사이트 봇 차단 우회 없음. 외부 공개·상업 이용 금지',
                       'sources': []},
 'frieze_seoul_2023': {'series': 'frieze_seoul',
                       'year': 2023,
                       'label': 'Frieze Seoul 2023',
                       'title': None,
                       'start_date': '2023-09-06',
                       'end_date': '2023-09-09',
                       'city': 'Seoul',
                       'announced': None,
                       'coverage': 'partial',
                       'coverage_note': '갤러리 목록만 — 부스 출품작가 비공개. 갤러리 121 / 작가 0. [내부 연구용] section filter pages archived '
                                        "for ['focus asia'] (options on page: ['focus asia', 'frieze masters', "
                                        "'galleries']); 111 rows left section=null dates confirmed in fetched source "
                                        "text rows by section: {None: 111, 'focus asia': 10} gallery rows with arti",
                       'prebuilt': 'research/frieze/frieze_seoul_2023.json',
                       'license': '내부 연구용 한정(2026-10-13 사용자 결정): frieze.com 약관상 서면 허가 없는 수집 금지 — 웨이백 사본·공식 보도자료 PDF만 '
                                  '사용, 현 사이트 봇 차단 우회 없음. 외부 공개·상업 이용 금지',
                       'sources': []},
 'frieze_seoul_2024': {'series': 'frieze_seoul',
                       'year': 2024,
                       'label': 'Frieze Seoul 2024',
                       'title': None,
                       'start_date': '2024-09-04',
                       'end_date': '2024-09-07',
                       'city': 'Seoul',
                       'announced': None,
                       'coverage': 'partial',
                       'coverage_note': '큐레이션 섹션·프로그램 작가만 — 일반 부스 출품작가는 프리즈가 공개하지 않음. 갤러리 116 / 작가 1. [내부 연구용] section '
                                        'per gallery unknown (no archived ?section= pages); section=null. Section '
                                        "options on page: ['focus asia', 'frieze masters', 'galleries'] announced "
                                        "count phrase: 'More than 110 of the world’s leading galleries' dates "
                                        'confirmed in fetched source',
                       'prebuilt': 'research/frieze/frieze_seoul_2024.json',
                       'license': '내부 연구용 한정(2026-10-13 사용자 결정): frieze.com 약관상 서면 허가 없는 수집 금지 — 웨이백 사본·공식 보도자료 PDF만 '
                                  '사용, 현 사이트 봇 차단 우회 없음. 외부 공개·상업 이용 금지',
                       'sources': []},
 'frieze_seoul_2025': {'series': 'frieze_seoul',
                       'year': 2025,
                       'label': 'Frieze Seoul 2025',
                       'title': None,
                       'start_date': '2025-09-03',
                       'end_date': '2025-09-06',
                       'city': 'Seoul',
                       'announced': None,
                       'coverage': 'partial',
                       'coverage_note': '갤러리 목록만 — 부스 출품작가 비공개. 갤러리 121 / 작가 0. [내부 연구용] section per gallery unknown '
                                        "(no archived ?section= pages); section=null. Section options on page: ['focus "
                                        "asia', 'frieze masters', 'galleries'] dates confirmed in fetched source text "
                                        'rows by section: {None: 121} gallery rows with artists: 0/121 (arti',
                       'prebuilt': 'research/frieze/frieze_seoul_2025.json',
                       'license': '내부 연구용 한정(2026-10-13 사용자 결정): frieze.com 약관상 서면 허가 없는 수집 금지 — 웨이백 사본·공식 보도자료 PDF만 '
                                  '사용, 현 사이트 봇 차단 우회 없음. 외부 공개·상업 이용 금지',
                       'sources': []}}
