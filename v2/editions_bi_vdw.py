"""베니스·도큐멘타·휘트니 회차 (2026-10-12 조사, 공식 사이트 + 베니스 2022/2024는 ASAC 아카이브). 생성: scratchpad/gen_vdw.py"""

EDITIONS = {'venice_2017': {'series': 'venice_biennale',
                 'year': 2017,
                 'label': '57th Venice Biennale - 57th International Art Exhibition',
                 'title': 'Viva Arte Viva',
                 'start_date': '2017-05-13',
                 'end_date': '2017-11-26',
                 'city': 'Venice',
                 'announced': 120,
                 'coverage': 'complete',
                 'coverage_note': 'research extracted=120, announced=120. Exact match: 120 numbered entries = 120 '
                                  "announced. Main exhibition = the nine 'Trans-pavilions'; national pavilions, "
                                  'collateral events, LUXUS (Venice Pavilion) and the Applied Arts Pavilion are '
                                  "excluded. Source prints 'SURNAME, Given'; name is rebuilt as 'Given Surname' (East "
                                  "Asian artists therefore appear as e.g. 'Jianyi Geng', 'Mingwei Lee', 'Tao Zhou' - "
                                  'name_raw/given_name/family_name kept for ',
                 'edition_parser': 'bi_vdw:parse_pages',
                 'edition_parser_kwargs': {'edition_id': 'venice_2017'},
                 'sources': [{'url': 'https://www.labiennale.org/en/art/2017/artists',
                              'fetch': 'html',
                              'tier': 'official',
                              'license': '공식 사이트 참가작가 명단, robots.txt 허용 확인(2026-10-12)',
                              'delay': 61}],
                 'research_extracted': 120},
 'venice_2019': {'series': 'venice_biennale',
                 'year': 2019,
                 'label': '58th Venice Biennale - 58th International Art Exhibition',
                 'title': 'May You Live in Interesting Times',
                 'start_date': '2019-05-11',
                 'end_date': '2019-11-24',
                 'city': 'Venice',
                 'announced': 79,
                 'coverage': 'complete',
                 'coverage_note': 'research extracted=79, announced=79. Exact match: 79 cards = 79 announced (Proposta '
                                  'A Arsenale + Proposta B Central Pavilion are the same 79 artists). Duos are single '
                                  "entries as on the site: 'Sun Yuan and Peng Yu', 'Christine and Margaret Wertheim'; "
                                  "'Slavs and Tatars' is a collective. Official page spells 'Dahn Vo' (artist is "
                                  'usually written Danh Vo - see asac_names); kept as printed. country = birth country '
                                  "as printed on the card ('",
                 'edition_parser': 'bi_vdw:parse_pages',
                 'edition_parser_kwargs': {'edition_id': 'venice_2019'},
                 'sources': [{'url': 'https://www.labiennale.org/en/art/2019/artists',
                              'fetch': 'html',
                              'tier': 'official',
                              'license': '공식 사이트 참가작가 명단, robots.txt 허용 확인(2026-10-12)',
                              'delay': 61},
                             {'url': 'https://www.labiennale.org/en/art/2019/artists?page=1',
                              'fetch': 'html',
                              'tier': 'official',
                              'license': '공식 사이트 참가작가 명단, robots.txt 허용 확인(2026-10-12)',
                              'delay': 61},
                             {'url': 'https://www.labiennale.org/en/art/2019/artists?page=2',
                              'fetch': 'html',
                              'tier': 'official',
                              'license': '공식 사이트 참가작가 명단, robots.txt 허용 확인(2026-10-12)',
                              'delay': 61},
                             {'url': 'https://www.labiennale.org/en/art/2019/artists?page=3',
                              'fetch': 'html',
                              'tier': 'official',
                              'license': '공식 사이트 참가작가 명단, robots.txt 허용 확인(2026-10-12)',
                              'delay': 61},
                             {'url': 'https://www.labiennale.org/en/art/2019/artists?page=4',
                              'fetch': 'html',
                              'tier': 'official',
                              'license': '공식 사이트 참가작가 명단, robots.txt 허용 확인(2026-10-12)',
                              'delay': 61},
                             {'url': 'https://www.labiennale.org/en/art/2019/artists?page=5',
                              'fetch': 'html',
                              'tier': 'official',
                              'license': '공식 사이트 참가작가 명단, robots.txt 허용 확인(2026-10-12)',
                              'delay': 61},
                             {'url': 'https://www.labiennale.org/en/art/2019/artists?page=6',
                              'fetch': 'html',
                              'tier': 'official',
                              'license': '공식 사이트 참가작가 명단, robots.txt 허용 확인(2026-10-12)',
                              'delay': 61},
                             {'url': 'https://www.labiennale.org/en/art/2019/artists?page=7',
                              'fetch': 'html',
                              'tier': 'official',
                              'license': '공식 사이트 참가작가 명단, robots.txt 허용 확인(2026-10-12)',
                              'delay': 61},
                             {'url': 'https://www.labiennale.org/en/art/2019/artists?page=8',
                              'fetch': 'html',
                              'tier': 'official',
                              'license': '공식 사이트 참가작가 명단, robots.txt 허용 확인(2026-10-12)',
                              'delay': 61}],
                 'research_extracted': 79},
 'venice_2022': {'series': 'venice_biennale',
                 'year': 2022,
                 'label': '59th Venice Biennale - 59th International Art Exhibition',
                 'title': 'The Milk of Dreams (Il latte dei sogni)',
                 'start_date': '2022-04-23',
                 'end_date': '2022-11-27',
                 'city': 'Venice',
                 'announced': 213,
                 'coverage': 'partial',
                 'coverage_note': '[ASAC 아카이브 기준: 전시 출품 단위가 아니라 인물 단위 — 듀오가 개인으로 쪼개지고 협업자가 추가될 수 있음, 동아시아 이름은 이름-성 순으로 '
                                  '뒤집혀 있음(성-이름 별칭으로 매칭). 공식 웹 목록(9명/쪽, 크롤 지연 60초)으로 교체 가능] research extracted=210, '
                                  "announced=213. Sections included: 'Il latte dei sogni (Giardini)', '(Arsenale)', "
                                  "'(Arsenale, Giardino delle Vergini)', the five historical 'Capsule' "
                                  "(section='historical_capsule'), the Forte Marghera special project (Elisa Giardina "
                                  'Papa, also in the main show) and Biennale College Arte (4 artists, out of '
                                  "competition but officially 'part of the 59th International Art Exhibition'; section "
                                  'flags them). Excluded: na',
                 'edition_parser': 'bi_vdw:parse_pages',
                 'edition_parser_kwargs': {'edition_id': 'venice_2022'},
                 'sources': [{'url': 'https://asac.labiennale.org/api/ricerca-semplice',
                              'fetch': 'json',
                              'tier': 'official',
                              'license': '라 비엔날레 공식 역사 아카이브(ASAC) 검색 API — robots.txt 없음(404), 회차별 1회 요청',
                              'method': 'POST',
                              'json_body': {'callBody': {'query': {'match': {'anno': '2022'}}},
                                            'callIndex': 'annali_arti_visive'},
                              'delay': 5}],
                 'research_extracted': 210},
 'venice_2024': {'series': 'venice_biennale',
                 'year': 2024,
                 'label': '60th Venice Biennale - 60th International Art Exhibition',
                 'title': 'Foreigners Everywhere (Stranieri Ovunque)',
                 'start_date': '2024-04-20',
                 'end_date': '2024-11-24',
                 'city': 'Venice',
                 'announced': 331,
                 'coverage': 'partial',
                 'coverage_note': '[ASAC 아카이브 기준: 전시 출품 단위가 아니라 인물 단위 — 듀오가 개인으로 쪼개지고 협업자가 추가될 수 있음, 동아시아 이름은 이름-성 순으로 '
                                  '뒤집혀 있음(성-이름 별칭으로 매칭). 공식 웹 목록(9명/쪽, 크롤 지연 60초)으로 교체 가능] research extracted=338, '
                                  'announced=331. Sections included: Nucleo contemporaneo (Giardini, Giardini esterno, '
                                  'Arsenale, Arsenale esterno; incl. Disobedience Archive), Nucleo storico: Ritratti / '
                                  'Astrazioni / Italiani Ovunque, Forte Marghera special project, and Biennale College '
                                  '(4, out of competition, flagged). Excluded: national participations, collateral '
                                  "events, Padiglione Venezia ('Sestante Domestico'), Applied Arts Pavilion (Beatriz M",
                 'edition_parser': 'bi_vdw:parse_pages',
                 'edition_parser_kwargs': {'edition_id': 'venice_2024'},
                 'sources': [{'url': 'https://asac.labiennale.org/api/ricerca-semplice',
                              'fetch': 'json',
                              'tier': 'official',
                              'license': '라 비엔날레 공식 역사 아카이브(ASAC) 검색 API — robots.txt 없음(404), 회차별 1회 요청',
                              'method': 'POST',
                              'json_body': {'callBody': {'query': {'match': {'anno': '2024'}}},
                                            'callIndex': 'annali_arti_visive'},
                              'delay': 5}],
                 'research_extracted': 338},
 'venice_2026': {'series': 'venice_biennale',
                 'year': 2026,
                 'label': '61st Venice Biennale - 61st International Art Exhibition',
                 'title': 'In Minor Keys',
                 'start_date': '2026-05-09',
                 'end_date': '2026-11-22',
                 'city': 'Venice',
                 'announced': 110,
                 'coverage': 'complete',
                 'coverage_note': 'research extracted=109, announced=110. Exhibition opened 9 May 2026, so the list is '
                                  'final-as-announced. 110 numbered entries; #110 Gala Porras-Kim is the Applied Arts '
                                  'Pavilion special project (with the V&A, out of competition) and is moved to '
                                  "excluded_entries -> 109 main entries. #6 'arms ache avid aeon' is a group entry "
                                  'whose members (Nancy Brooks Brody, Joy Episalla, Zoe Leonard, Carrie Yamaoka, '
                                  'fierce pussy, Jo-ey Tang) are in `memb',
                 'edition_parser': 'bi_vdw:parse_pages',
                 'edition_parser_kwargs': {'edition_id': 'venice_2026'},
                 'sources': [{'url': 'https://www.labiennale.org/en/news/biennale-arte-2026-invited-artists',
                              'fetch': 'html',
                              'tier': 'official',
                              'license': '공식 사이트 참가작가 명단, robots.txt 허용 확인(2026-10-12)',
                              'delay': 61}],
                 'research_extracted': 109},
 'documenta_2017': {'series': 'documenta',
                    'year': 2017,
                    'label': 'documenta 14',
                    'title': "documenta 14 (working title 'Learning from Athens')",
                    'start_date': '2017-04-08',
                    'end_date': '2017-09-17',
                    'city': 'Athens; Kassel',
                    'announced': 160,
                    'coverage': 'complete',
                    'coverage_note': "research extracted=149, announced=160. 149 'Artists' entries vs 'over 160 "
                                     "artists': entries are curatorial units - duos/trios/collectives count once (e.g. "
                                     "'Israel Galván, Niño de Elche, and Pedro G. Romero', 'Sámi Artist Group (...3 "
                                     "members)', 'Postcommodity', 'iQhiya'); splitting them brings the count to ~160+. "
                                     'Exhibition dates are the overall run (Athens opened 8 Apr, Kassel closed 17 Sep '
                                     '2017) per the closing press release. The page',
                    'edition_parser': 'bi_vdw:parse_pages',
                    'edition_parser_kwargs': {'edition_id': 'documenta_2017'},
                    'sources': [{'url': 'https://www.documenta14.de/en/public-exhibition/',
                                 'fetch': 'html',
                                 'tier': 'official',
                                 'license': '공식 사이트 참가작가 명단, robots.txt 허용 확인(2026-10-12)'}],
                    'research_extracted': 149},
 'documenta_2022': {'series': 'documenta',
                    'year': 2022,
                    'label': 'documenta fifteen',
                    'title': 'lumbung',
                    'start_date': '2022-06-18',
                    'end_date': '2022-09-25',
                    'city': 'Kassel',
                    'announced': 67,
                    'coverage': 'complete',
                    'coverage_note': "research extracted=67, announced=67. Structure: 14 'lumbung members' "
                                     "(category=lumbung_member) + 53 'lumbung artists' (category=lumbung_artist) = 67, "
                                     'matches the page filter counts. The Oct-2021 announcement lists 54 lumbung '
                                     "artists; 'Sakuliu' (Taiwan) is not on the final members & artists page. Name "
                                     "changes between announcement and final page: 'Wakaliwood Ug' -> 'Wakaliga "
                                     "Uganda', 'ook_reinaart vanhoe' -> 'ook_ [...]'. Collectives a",
                    'edition_parser': 'bi_vdw:parse_pages',
                    'edition_parser_kwargs': {'edition_id': 'documenta_2022'},
                    'sources': [{'url': 'https://documenta-fifteen.de/en/lumbung-members-artists/',
                                 'fetch': 'html',
                                 'tier': 'official',
                                 'license': '공식 사이트 참가작가 명단, robots.txt 허용 확인(2026-10-12)'}],
                    'research_extracted': 67},
 'whitney_2017': {'series': 'whitney_biennial',
                  'year': 2017,
                  'label': 'Whitney Biennial 2017 (78th edition)',
                  'title': None,
                  'start_date': '2017-03-17',
                  'end_date': '2017-06-11',
                  'city': 'New York',
                  'announced': 63,
                  'coverage': 'complete',
                  'coverage_note': 'research extracted=63, announced=63. Names only on the index. Birth '
                                   'year/place/residence are on per-artist section pages '
                                   '(https://whitney.org/exhibitions/2017-biennial/art?section=N, N=1..63, '
                                   'server-rendered, allowed by robots) - not fetched here to stay within a few dozen '
                                   'requests; parse_whitney_section_detail() handles them. Section 1 (and 2024 section '
                                   '24) were enriched from pages already fetched. Duos/collectives are single entrie',
                  'edition_parser': 'bi_vdw:parse_pages',
                  'edition_parser_kwargs': {'edition_id': 'whitney_2017'},
                  'sources': [{'url': 'https://whitney.org/exhibitions/2017-biennial/art',
                               'fetch': 'html',
                               'tier': 'official',
                               'license': '공식 사이트 참가작가 명단, robots.txt 허용 확인(2026-10-12)'}],
                  'research_extracted': 63},
 'whitney_2019': {'series': 'whitney_biennial',
                  'year': 2019,
                  'label': 'Whitney Biennial 2019 (79th edition)',
                  'title': None,
                  'start_date': '2019-05-17',
                  'end_date': '2019-10-27',
                  'city': 'New York',
                  'announced': 75,
                  'coverage': 'complete',
                  'coverage_note': 'research extracted=75, announced=75. Header shows May 17–Oct 27, 2019; the body '
                                   'text still says May 17–September 22, 2019 (original closing date, later extended). '
                                   'Names only on the index. Birth year/place/residence are on per-artist section '
                                   'pages (https://whitney.org/exhibitions/2019-biennial/art?section=N, N=1..75, '
                                   'server-rendered, allowed by robots) - not fetched here to stay within a few dozen '
                                   'requests; parse_whitney_section_detai',
                  'edition_parser': 'bi_vdw:parse_pages',
                  'edition_parser_kwargs': {'edition_id': 'whitney_2019'},
                  'sources': [{'url': 'https://whitney.org/exhibitions/2019-biennial/art',
                               'fetch': 'html',
                               'tier': 'official',
                               'license': '공식 사이트 참가작가 명단, robots.txt 허용 확인(2026-10-12)'}],
                  'research_extracted': 75},
 'whitney_2022': {'series': 'whitney_biennial',
                  'year': 2022,
                  'label': 'Whitney Biennial 2022 (80th edition)',
                  'title': "Quiet as It's Kept",
                  'start_date': '2022-04-06',
                  'end_date': '2022-10-16',
                  'city': 'New York',
                  'announced': 63,
                  'coverage': 'complete',
                  'coverage_note': 'research extracted=63, announced=63. Header shows Apr 6–Oct 16, 2022; the body '
                                   'text says April 6–September 5, 2022 (original closing date, later extended). Names '
                                   'only on the index. Birth year/place/residence are on per-artist section pages '
                                   '(https://whitney.org/exhibitions/2022-biennial/art?section=N, N=1..63, '
                                   'server-rendered, allowed by robots) - not fetched here to stay within a few dozen '
                                   'requests; parse_whitney_section_detail() han',
                  'edition_parser': 'bi_vdw:parse_pages',
                  'edition_parser_kwargs': {'edition_id': 'whitney_2022'},
                  'sources': [{'url': 'https://whitney.org/exhibitions/2022-biennial/art',
                               'fetch': 'html',
                               'tier': 'official',
                               'license': '공식 사이트 참가작가 명단, robots.txt 허용 확인(2026-10-12)'}],
                  'research_extracted': 63},
 'whitney_2024': {'series': 'whitney_biennial',
                  'year': 2024,
                  'label': 'Whitney Biennial 2024 (81st edition)',
                  'title': 'Even Better Than the Real Thing',
                  'start_date': '2024-03-20',
                  'end_date': '2024-08-11',
                  'city': 'New York',
                  'announced': 71,
                  'coverage': 'complete',
                  'coverage_note': 'research extracted=69, announced=71. 69 entries vs 71 announced: the Art & Artists '
                                   "index (and en.wikipedia '2024 Whitney Biennial', checked) lists 69; the difference "
                                   "matches the two duo entries counted as individuals ('Holly Herndon and Mat "
                                   "Dryhurst', 'Gbenga Komolafe and Tee Park') - an inference, not stated by the "
                                   "source. Entry 'Niillasaš-Jovnna Máreha Juhani Sunná Máret–Sunna Nousuniemi' is one "
                                   'artist (Sámi + Finnish name forms). ',
                  'edition_parser': 'bi_vdw:parse_pages',
                  'edition_parser_kwargs': {'edition_id': 'whitney_2024'},
                  'sources': [{'url': 'https://whitney.org/exhibitions/2024-biennial/art',
                               'fetch': 'html',
                               'tier': 'official',
                               'license': '공식 사이트 참가작가 명단, robots.txt 허용 확인(2026-10-12)'}],
                  'research_extracted': 69},
 'whitney_2026': {'series': 'whitney_biennial',
                  'year': 2026,
                  'label': 'Whitney Biennial 2026 (82nd edition)',
                  'title': None,
                  'start_date': '2026-03-08',
                  'end_date': '2026-10-12',
                  'city': 'New York',
                  'announced': 56,
                  'coverage': 'complete',
                  'coverage_note': 'research extracted=56, announced=56. Overview page (fetched 2026-10-12): floor 5 '
                                   'on view through Aug 23, floor 1 through Sept 7, floor 6 through Oct 12; end_date = '
                                   'last floor closing. The list is final (exhibition already open). Names only on the '
                                   'index. Birth year/place/residence are on per-artist section pages '
                                   '(https://whitney.org/exhibitions/2026-biennial/art?section=N, N=1..56, '
                                   'server-rendered, allowed by robots) - not fetched her',
                  'edition_parser': 'bi_vdw:parse_pages',
                  'edition_parser_kwargs': {'edition_id': 'whitney_2026'},
                  'sources': [{'url': 'https://whitney.org/exhibitions/2026-biennial/art',
                               'fetch': 'html',
                               'tier': 'official',
                               'license': '공식 사이트 참가작가 명단, robots.txt 허용 확인(2026-10-12)'}],
                  'research_extracted': 56}}
