"""리움미술관 원본(JSON) -> museums/artists/artworks/museum_holdings 적재.

createDate 필드가 "시대/연도<br>재료기법"으로 결합돼 있어 <br> 기준으로
분리(앞쪽=연도, 뒤쪽=medium) — 고미술은 창작자가 대부분 공백(무명작 다수),
현대미술은 creater(국문)+creater2(영문/생몰년 괄호) 형태.
"""
from __future__ import annotations

import html
import re

from raw_iter import iter_records

MUSEUM_NAME = "리움미술관 (Leeum Museum of Art)"
MUSEUM_NAME_EN = "Leeum Museum of Art"

TAG_RE = re.compile(r"<[^>]+>")


def _clean(text: str | None) -> str | None:
    if not text:
        return None
    text = TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def load(store) -> int:
    museum_id = store.get_or_create_museum(MUSEUM_NAME, MUSEUM_NAME_EN)
    loaded = 0

    for _record_id, data, meta in iter_records("leeum"):
        if store.source_already_loaded(meta["raw_path"]):
            continue

        source_id = store.insert_source(meta)

        artist_name = (data.get("creater") or "").strip() or None
        artist_id = store.get_or_create_artist(artist_name, source_id=source_id)

        create_date = data.get("createDate") or ""
        parts = create_date.split("<br>", 1)
        year_created = _clean(parts[0]) if parts else None
        medium = _clean(parts[1]) if len(parts) > 1 else None

        title = data.get("title1") or data.get("title2") or "(제목 없음)"
        title_en = data.get("title2") if data.get("title1") else None

        artwork_id = store.insert_artwork(
            artist_id=artist_id,
            title=_clean(title) or "(제목 없음)",
            title_en=_clean(title_en),
            year_created=year_created,
            medium=medium,
            dimensions=(data.get("psize") or None),
            description=_clean(data.get("content")),
            source_id=source_id,
        )

        store.insert_museum_holding(
            museum_id=museum_id,
            artwork_id=artwork_id,
            source_id=source_id,
        )
        loaded += 1

    store.commit()
    print(f"[pipeline:leeum] {loaded}건 적재")
    return loaded
