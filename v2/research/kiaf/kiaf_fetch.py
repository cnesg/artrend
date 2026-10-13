"""Polite, cached fetch helpers for the Kiaf research (research/kiaf/).

* cache:   _cache/<sanitised-url-tail>__<sha1[:16]>  + .meta (JSON: url, status, ctype, final_url, ts, ...)
           (same key scheme as the 2026-10-12 run, so the surviving cache files are reused as-is)
* PDFs:    _pdf/<name>  + _pdf/<name>.meta   (streamed download)
* log:     request_log.jsonl  (one line per network request)
* polite:  UA "artgraph-research-bot/1.0 (https://github.com/cnesg/artrend)"; >=1.2 s between non-Wayback
           requests, >=2 s between Wayback requests (state shared via .ratelimit.json)
* offline: set_offline(True) -> any cache miss raises CacheMiss instead of touching the network
"""
import hashlib
import json
import os
import re
import time

BASE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(BASE, "_cache")
PDFDIR = os.path.join(BASE, "_pdf")
LOG = os.path.join(BASE, "request_log.jsonl")
STAMP = os.path.join(BASE, ".ratelimit.json")
UA = "artgraph-research-bot/1.0 (https://github.com/cnesg/artrend)"
OFFLINE = False


class CacheMiss(RuntimeError):
    pass


def set_offline(flag=True):
    global OFFLINE
    OFFLINE = flag


def rel(path):
    return os.path.relpath(path, BASE).replace("\\", "/")


def _key(url):
    h = hashlib.sha1(url.encode()).hexdigest()[:16]
    safe = re.sub(r"[^A-Za-z0-9]+", "_", url)[-80:]
    return os.path.join(CACHE, f"{safe}__{h}")


def _wait(url):
    gap = 2.0 if "archive.org" in url else 1.2
    try:
        last = json.load(open(STAMP))
    except Exception:
        last = {}
    host = "wb" if "archive.org" in url else "other"
    d = time.time() - last.get(host, 0)
    if d < gap:
        time.sleep(gap - d)
    last[host] = time.time()
    json.dump(last, open(STAMP, "w"))


def _log(meta):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(meta, ensure_ascii=False) + "\n")


def _session():
    import requests
    s = requests.Session()
    s.headers["User-Agent"] = UA
    return s


_S = None


def fetch(url, timeout=90):
    """-> (path, status). Cached bodies with status <500 and !=429 are reused."""
    global _S
    os.makedirs(CACHE, exist_ok=True)
    p = _key(url)
    if os.path.exists(p) and os.path.exists(p + ".meta"):
        meta = json.load(open(p + ".meta"))
        if meta["status"] < 500 and meta["status"] != 429:
            return p, meta["status"]
    if OFFLINE:
        raise CacheMiss(url)
    _S = _S or _session()
    _wait(url)
    for attempt in range(3):
        try:
            r = _S.get(url, timeout=timeout)
            break
        except Exception:
            if attempt == 2:
                raise
            time.sleep(5)
    with open(p, "wb") as f:
        f.write(r.content)
    meta = {"url": url, "status": r.status_code, "ctype": r.headers.get("content-type"), "final_url": r.url,
            "ts": time.time(), "wp_total": r.headers.get("X-WP-Total"), "wp_pages": r.headers.get("X-WP-TotalPages"),
            "bytes": len(r.content), "cache_file": rel(p)}
    json.dump(meta, open(p + ".meta", "w"))
    _log(meta)
    return p, r.status_code


def fetch_text(url, **kw):
    p, st = fetch(url, **kw)
    return open(p, encoding="utf-8", errors="replace").read(), p, st


def fetch_pdf(url, name):
    """stream a PDF to _pdf/<name>; -> path"""
    global _S
    os.makedirs(PDFDIR, exist_ok=True)
    dst = os.path.join(PDFDIR, name)
    if os.path.exists(dst) and os.path.exists(dst + ".meta"):
        return dst
    if OFFLINE:
        raise CacheMiss(url)
    _S = _S or _session()
    _wait(url)
    with _S.get(url, stream=True, timeout=300) as r:
        r.raise_for_status()
        with open(dst + ".part", "wb") as f:
            for ch in r.iter_content(1 << 20):
                f.write(ch)
        meta = {"url": url, "status": r.status_code, "ctype": r.headers.get("content-type"), "final_url": r.url,
                "ts": time.time(), "bytes": os.path.getsize(dst + ".part"), "cache_file": rel(dst)}
    os.replace(dst + ".part", dst)
    json.dump(meta, open(dst + ".meta", "w"))
    _log(meta)
    return dst


def wayback_url(ts, url):
    return f"https://web.archive.org/web/{ts}id_/{url}"


def wb(ts, url, tries=5):
    """raw Wayback snapshot (id_); retries on 5xx/429 (Wayback was intermittently 'Temporarily Offline')"""
    u = wayback_url(ts, url)
    for i in range(tries):
        p, st = fetch(u, timeout=120)
        if st in (200, 404):
            return p, st, u
        if OFFLINE:
            break
        time.sleep(8 + 6 * i)
    return p, st, u


def cdx(pattern, extra="", tries=3):
    url = (f"http://web.archive.org/cdx/search/cdx?url={pattern}&output=json&filter=statuscode:200"
           f"&collapse=urlkey&fl=timestamp,original,mimetype{extra}")
    for i in range(tries):
        p, st = fetch(url, timeout=120)
        if st == 200:
            s = open(p, "rb").read().decode("utf-8", "replace")
            return json.loads(s)[1:] if s.strip() else []
        if OFFLINE:
            break
        time.sleep(10)
    return None


def restore_log_from_cache():
    """append request_log entries for cache files that survived the 2026-10-13 temp wipe (fetched 2026-10-12)"""
    done = set()
    if os.path.exists(LOG):
        for line in open(LOG, encoding="utf-8"):
            try:
                done.add(json.loads(line)["url"])
            except Exception:
                pass
    n = 0
    for f in sorted(os.listdir(CACHE)):
        if not f.endswith(".meta"):
            continue
        m = json.load(open(os.path.join(CACHE, f)))
        if m["url"] in done:
            continue
        m = dict(m, restored_from_surviving_cache=True, cache_file=rel(os.path.join(CACHE, f[:-5])),
                 body_present=os.path.exists(os.path.join(CACHE, f[:-5])))
        _log(m); n += 1
    return n
