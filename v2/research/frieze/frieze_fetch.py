"""Polite, cached fetch helpers for the Frieze research crawl.

Cache layout (all paths relative to research/frieze/):
    raw/<host>/<md5(requested_url)>.<ext>     raw response bytes, exactly as served
    raw/index.tsv                             one line per cached URL (see INDEX_COLS)
    requests.log                              one line per network request (incl. failures)

Rules: Wayback (web.archive.org / archive.org) >= 5.5 s between requests, other hosts >= 1.5 s.
Only HTTP 200 responses are cached. get(..., allow_network=False) never touches the network.
No bot-challenge circumvention: a Cloudflare 403 is simply recorded as a failure.
"""
from __future__ import annotations

import csv
import hashlib
import os
import re
import sys
import time
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(BASE, "raw")
INDEX = os.path.join(RAW, "index.tsv")
LOG = os.path.join(BASE, "requests.log")
UA = "artgraph-research-bot/1.0 (https://github.com/cnesg/artrend)"
INDEX_COLS = ["md5", "requested_url", "final_url", "status", "content_type", "fetched_at_utc", "rel_path", "sha256", "bytes"]
WAYBACK_DELAY = 5.5
OTHER_DELAY = 1.5

_last: dict[str, float] = {}
_session = None
_index_cache: dict[str, dict] | None = None


class NotCached(Exception):
    pass


def _host(url: str) -> str:
    return re.sub(r"^https?://([^/]+).*$", r"\1", url).lower()


def _ext(url: str, content_type: str) -> str:
    ct = (content_type or "").lower()
    if "pdf" in ct or url.lower().split("?")[0].endswith(".pdf"):
        return ".pdf"
    if "json" in ct or "/cdx/search/cdx" in url:
        return ".json"
    if url.endswith("robots.txt") or ct.startswith("text/plain"):
        return ".txt"
    return ".html"


def load_index() -> dict[str, dict]:
    global _index_cache
    if _index_cache is None:
        _index_cache = {}
        if os.path.exists(INDEX):
            with open(INDEX, encoding="utf-8", newline="") as f:
                for row in csv.DictReader(f, delimiter="\t"):
                    _index_cache[row["requested_url"]] = row
    return _index_cache


def _append_index(row: dict):
    os.makedirs(RAW, exist_ok=True)
    new = not os.path.exists(INDEX)
    with open(INDEX, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=INDEX_COLS, delimiter="\t")
        if new:
            w.writeheader()
        w.writerow(row)
    load_index()[row["requested_url"]] = row


def _log(status, url, note=""):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}\t{status}\t{url}\t{note}\n")


def _sleep_for(host: str):
    d = WAYBACK_DELAY if "archive.org" in host else OTHER_DELAY
    w = d - (time.time() - _last.get(host, 0))
    if w > 0:
        time.sleep(w)
    _last[host] = time.time()


def wayback_ts(url: str | None) -> str | None:
    m = re.search(r"/web/(\d{4,14})(?:id_)?/", url or "")
    return m.group(1) if m else None


def cached_meta(url: str) -> dict | None:
    return load_index().get(url)


def get(url: str, allow_network: bool = False, binary: bool = False, timeout: int = 180):
    """Return (content, meta). content is bytes if binary else str (utf-8, replacement on errors)."""
    meta = cached_meta(url)
    if meta is None:
        if not allow_network:
            raise NotCached(url)
        meta = _download(url, timeout)
        if meta is None:
            raise NotCached(url)
    path = os.path.join(BASE, meta["rel_path"])
    data = open(path, "rb").read()
    if binary:
        return data, meta
    return data.decode("utf-8", errors="replace"), meta


def _download(url: str, timeout: int):
    global _session
    import requests
    if _session is None:
        _session = requests.Session()
        _session.headers["User-Agent"] = UA
    host = _host(url)
    for attempt in range(4):
        _sleep_for(host)
        try:
            r = _session.get(url, timeout=timeout, allow_redirects=True)
        except Exception as e:  # connection refused = Wayback rate-limit block
            _log("ERR", url, type(e).__name__)
            time.sleep(60 * (attempt + 1))
            continue
        _log(r.status_code, url, "" if r.url == url else f"-> {r.url}")
        if r.status_code in (429, 502, 503, 504):
            time.sleep(30 * (attempt + 1))
            continue
        if r.status_code != 200:
            return None
        md5 = hashlib.md5(url.encode()).hexdigest()
        ext = _ext(url, r.headers.get("content-type", ""))
        rel = os.path.join("raw", host.replace(":", "_"), md5 + ext).replace("\\", "/")
        os.makedirs(os.path.join(BASE, os.path.dirname(rel)), exist_ok=True)
        with open(os.path.join(BASE, rel), "wb") as f:
            f.write(r.content)
        row = {"md5": md5, "requested_url": url, "final_url": r.url, "status": r.status_code,
               "content_type": r.headers.get("content-type", ""),
               "fetched_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
               "rel_path": rel, "sha256": hashlib.sha256(r.content).hexdigest(), "bytes": len(r.content)}
        _append_index(row)
        return row
    return None


def try_get(url: str, allow_network: bool, binary: bool = False):
    """Like get() but returns (None, None) on any failure (used for non-essential pages)."""
    try:
        return get(url, allow_network=allow_network, binary=binary)
    except NotCached:
        return None, None


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    for u in sys.argv[1:]:
        c, m = get(u, allow_network=True, binary=True)
        print(m["status"], m["rel_path"], len(c), m["final_url"])
