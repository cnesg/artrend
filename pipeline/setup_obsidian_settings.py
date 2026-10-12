"""Setup Obsidian Preferences, Colored Graph View, Bookmarks, and Custom CSS."""
import json
from pathlib import Path

vault = Path(r"c:\Users\CNCITY\artrend\vault_curated")
obs_dir = vault / ".obsidian"
obs_dir.mkdir(parents=True, exist_ok=True)
snippets_dir = obs_dir / "snippets"
snippets_dir.mkdir(parents=True, exist_ok=True)

# 1. Configure graph.json with vibrant color groups & optimal physics
graph_cfg = {
    "collapse-filter": False,
    "search": "",
    "showTags": False,
    "showAttachments": False,
    "hideUnresolved": True,
    "showOrphans": False,
    "collapse-color-groups": False,
    "colorGroups": [
        {
            "query": "path:artists",
            "color": {"a": 1, "rgb": 11032055}  # Purple #A855F7 (Artists)
        },
        {
            "query": "path:artworks",
            "color": {"a": 1, "rgb": 16096779}  # Gold #F59E0B (Masterpieces)
        },
        {
            "query": "path:museums",
            "color": {"a": 1, "rgb": 1096065}   # Green #10B981 (Museums)
        },
        {
            "query": "path:galleries",
            "color": {"a": 1, "rgb": 959977}    # Sky Blue #0EA5E9 (Galleries)
        },
        {
            "query": "path:auction_houses",
            "color": {"a": 1, "rgb": 15680580}  # Red #EF4444 (Auction Houses)
        },
        {
            "query": "path:collectors",
            "color": {"a": 1, "rgb": 15485081}  # Pink #EC4899 (Collectors)
        },
        {
            "query": 'file:"00 대시보드"',
            "color": {"a": 1, "rgb": 3718648}   # Bright Cyan #38BDF8 (Dashboard)
        }
    ],
    "collapse-display": False,
    "showArrow": True,
    "textFadeMultiplier": 0.2,
    "nodeSizeMultiplier": 1.25,
    "lineSizeMultiplier": 1.1,
    "collapse-forces": False,
    "centerStrength": 0.45,
    "repelStrength": 14.0,
    "linkStrength": 1.0,
    "linkDistance": 110,
    "scale": 0.08,
    "close": False
}
(obs_dir / "graph.json").write_text(json.dumps(graph_cfg, indent=2, ensure_ascii=False), encoding="utf-8")
print("  -> graph.json (컬러 그룹 및 물리엔진) 설정 완료!")

# 2. Configure bookmarks.json (Left Sidebar Navigation)
bookmarks_cfg = {
    "items": [
        {"type": "file", "path": "00 대시보드.md", "title": "📊 종합 대시보드 (Artrend Graph)"},
        {"type": "group", "title": "📁 핵심 카테고리 바로가기", "items": [
            {"type": "folder", "path": "artists", "title": "🎨 작가 컬렉션 (2,500명)"},
            {"type": "folder", "path": "artworks", "title": "🖼️ 대표 명작 (1,200점)"},
            {"type": "folder", "path": "museums", "title": "🏛️ 글로벌 미술관 (400곳)"},
            {"type": "folder", "path": "galleries", "title": "🏢 리딩 갤러리 (250곳)"},
            {"type": "folder", "path": "auction_houses", "title": "🔨 주요 경매사 (250곳)"},
            {"type": "folder", "path": "collectors", "title": "📜 핵심 컬렉터 (500명)"}
        ]},
        {"type": "group", "title": "🏆 역대 최고가 랜드마크 명작", "items": [
            {"type": "file", "path": "artworks/Salvator Mundi (f78cac14).md", "title": "💎 Salvator Mundi ($450M)"},
            {"type": "file", "path": "artworks/The Dream (The Bed) (c32c8331).md", "title": "💎 Frida Kahlo - The Dream ($54M)"},
            {"type": "file", "path": "artworks/Fruit and Ginger Jar (d5d35d8f).md", "title": "💎 Paul Cézanne - Fruit Jar ($38M)"},
            {"type": "file", "path": "artworks/Tulips (6d2803a3).md", "title": "💎 Jeff Koons - Tulips ($33M)"}
        ]}
    ]
}
(obs_dir / "bookmarks.json").write_text(json.dumps(bookmarks_cfg, indent=2, ensure_ascii=False), encoding="utf-8")
print("  -> bookmarks.json (북마크 퀵 메뉴) 생성 완료!")

# 3. Configure app.json
app_cfg = {
    "spellcheck": False,
    "showLineNumber": True,
    "readableLineLength": True,
    "strictLineBreaks": False,
    "showRibbon": True,
    "defaultViewMode": "preview",
    "useMarkdownLinks": False,
    "newFileLocation": "root",
    "attachmentFolderPath": "attachments"
}
(obs_dir / "app.json").write_text(json.dumps(app_cfg, indent=2, ensure_ascii=False), encoding="utf-8")
print("  -> app.json (에디터 최적화) 설정 완료!")

# 4. Configure appearance.json & Custom CSS snippet
app_appearance = {
    "cssTheme": "",
    "theme": "obsidian",
    "baseFontSize": 16,
    "enabledCssSnippets": ["artgraph-style"]
}
(obs_dir / "appearance.json").write_text(json.dumps(app_appearance, indent=2, ensure_ascii=False), encoding="utf-8")

css_content = """/* Artrend ArtGraph Obsidian Premium Style */
:root {
  --art-purple: #a855f7;
  --art-gold: #f59e0b;
  --art-green: #10b981;
  --art-blue: #0ea5e9;
  --art-red: #ef4444;
  --art-pink: #ec4899;
}

/* Beautiful Table Styling */
.markdown-rendered table {
  width: 100%;
  border-collapse: separate;
  border-spacing: 0;
  border-radius: 8px;
  overflow: hidden;
  margin: 1.2em 0;
  font-size: 0.92em;
}

.markdown-rendered th {
  background: rgba(var(--mono-rgb-100), 0.08);
  font-weight: 600;
  padding: 8px 12px;
  text-align: left;
}

.markdown-rendered td {
  padding: 7px 12px;
  border-top: 1px solid rgba(var(--mono-rgb-100), 0.06);
}

.markdown-rendered tr:hover td {
  background: rgba(var(--mono-rgb-100), 0.04);
}

/* Category Badge Tags */
.tag[href*="#art/artist"] { background-color: rgba(168, 85, 247, 0.15); color: #c084fc; border: 1px solid rgba(168, 85, 247, 0.3); }
.tag[href*="#art/artwork"] { background-color: rgba(245, 158, 11, 0.15); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.3); }
.tag[href*="#art/museum"] { background-color: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.3); }
.tag[href*="#art/gallery"] { background-color: rgba(14, 165, 233, 0.15); color: #38bdf8; border: 1px solid rgba(14, 165, 233, 0.3); }
.tag[href*="#art/auction_house"] { background-color: rgba(239, 68, 68, 0.15); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.3); }
.tag[href*="#art/collector"] { background-color: rgba(236, 72, 153, 0.15); color: #f472b6; border: 1px solid rgba(236, 72, 153, 0.3); }
"""
(snippets_dir / "artgraph-style.css").write_text(css_content, encoding="utf-8")
print("  -> artgraph-style.css (커스텀 디자인 테마 스니펫) 생성 완료!")

# 5. Configure core-plugins.json
core_plugins = [
    "file-explorer",
    "global-search",
    "switcher",
    "graph",
    "backlink",
    "canvas",
    "outgoing-link",
    "tag-pane",
    "page-preview",
    "command-palette",
    "markdown-importer",
    "editor-status",
    "bookmarks",
    "outline",
    "word-count"
]
(obs_dir / "core-plugins.json").write_text(json.dumps(core_plugins, indent=2), encoding="utf-8")
print("  -> core-plugins.json (필수 코어 플러그인 활성화) 완료!")
