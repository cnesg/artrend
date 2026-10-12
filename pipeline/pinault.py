"""Pinault Collection 원본(raw/pinault/*.json, artwork 상세 HTML) -> DB 적재.

crawlers/pinault.py가 저장한 raw HTML(japan_museums와 동일하게 .json 확장자로
저장되지만 내용은 HTML)에서 BeautifulSoup으로 필드를 파싱한다.
"""
from __future__ import annotations

import json
import re

from bs4 import BeautifulSoup

from raw_iter import RAW_ROOT

PINAULT_DIR = RAW_ROOT / "pinault"
MUSEUM_NAME = "Pinault Collection"
MUSEUM_NAME_EN = "Pinault Collection (Bourse de Commerce / Palazzo Grassi / Punta della Dogana)"

YEAR_RE = re.compile(r"(\d{4})")


def _field_text(article, field_name: str) -> str | None:
    node = article.select_one(f".field--name-{field_name} .field__item")
    if node is None:
        return None
    text = node.get_text(" ", strip=True)
    return text or None


def _parse_html(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    article = soup.select_one("article.type-artwork.as-full")
    if article is None:
        return {}

    title_node = article.select_one("h1 .field--name-title")
    title = title_node.get_text(strip=True) if title_node else None

    artist_node = article.select_one(".field--name-field-artist a")
    artist_name = artist_node.get_text(strip=True) if artist_node else None

    return {
        "title": title,
        "artist_name": artist_name,
        "year_created": _field_text(article, "field-prod-year"),
        "medium": _field_text(article, "field-desc"),
        "dimensions": _field_text(article, "field-dimensions"),
        "description": _field_text(article, "field-note"),
    }


def load(store) -> int:
    museum_id = store.get_or_create_museum(MUSEUM_NAME, MUSEUM_NAME_EN)
    loaded = 0

    for html_path in sorted(PINAULT_DIR.glob("*.json")):
        if html_path.name.endswith(".meta.json"):
            continue
        record_id = html_path.stem
        meta_path = html_path.with_name(f"{record_id}.meta.json")
        if not meta_path.exists():
            continue

        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if store.source_already_loaded(meta["raw_path"]):
            continue

        content = html_path.read_text(encoding="utf-8", errors="replace")
        parsed = _parse_html(content)
        if not parsed.get("title"):
            continue

        source_id = store.insert_source(meta)

        artist_id = store.get_or_create_artist(parsed.get("artist_name"), source_id=source_id)

        year_m = YEAR_RE.search(parsed.get("year_created") or "")
        year_created = year_m.group(1) if year_m else parsed.get("year_created")

        artwork_id = store.insert_artwork(
            artist_id=artist_id,
            title=parsed["title"],
            year_created=year_created,
            medium=parsed.get("medium"),
            dimensions=parsed.get("dimensions"),
            description=parsed.get("description"),
            source_id=source_id,
        )

        store.insert_museum_holding(
            museum_id=museum_id,
            artwork_id=artwork_id,
            accession_number=record_id,
            source_id=source_id,
        )
        loaded += 1

    store.commit()
    print(f"[pipeline:pinault] {loaded}건 적재")
    return loaded
