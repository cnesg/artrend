"""R5-통계 — K-ARTMARKET 연도별 시장 통계 raw HTML -> market_stats_kr.

crawlers/kams_stats.py가 저장한 `crawlers/raw/kams_stats/market_size_progress.html`
(서버 렌더링 테이블)에서 화랑/경매사/아트페어 연도별 판매금액·낙찰률 표만
뽑는다. 이 페이지는 JSON이 아니라 HTML이라 `raw_iter.iter_records`(json 전용)를
쓰지 않고 파일을 직접 읽는다.

메인 지시(2026-09-15 R5-통계 규칙) 준수:
- metric 명 5개 고정: auction_total_krw, auction_sell_through_rate,
  gallery_sales_krw, artfair_sales_krw, market_total_krw.
- 수치는 원 단위 환산 없이 원문 그대로, unit에 원문 단위 표기.
- 추정·보간 금지 — 원문에 없는 연도는 비워 둠.
- market_total_krw는 원문에 "미술시장 전체 규모" 합계 항목이 없어(화랑/경매/
  아트페어 개별 표만 존재) 세 지표의 단순 합으로 계산한 파생값이다. 원문이
  직접 제공한 수치가 아니므로 note에 "[산출값] 화랑+경매+아트페어 판매금액
  합산(원문에 합계 항목 없음)"이라고 명시하고, 세 지표가 모두 있는 연도만 채운다.

2026-09-17 갱신잡 정리 후속 수정: `crawlers/kams_stats.py`가 이제 매달 새 raw
파일(`market_size_progress_YYYYMM.html`)을 저장하므로, 여기서는 **가장 최신
raw 파일**을 읽는다. DB 반영은 `(year, metric)` 기준 upsert로 바꿔 원문 값이
바뀌면 갱신되게 했다(기존엔 `on conflict do nothing`이라 최초 1회 값에서 영원히
안 바뀌는 결함이 있었음) — 값이 실제로 달라진 행만 리포트에 diff로 남긴다.

사용법:
    python pipeline/kams_stats_load.py            # 리포트만
    python pipeline/kams_stats_load.py --apply     # 실제 반영
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8")
load_dotenv(Path(__file__).parent / ".env")

sys.path.insert(0, str(Path(__file__).parent))
from db import get_connection  # noqa: E402

DOCS_DIR = Path(__file__).resolve().parent.parent / "docs" / "logs"
RAW_DIR = Path(__file__).resolve().parent.parent / "crawlers" / "raw" / "kams_stats"
SOURCE_URL = "https://k-artmarket.kr/member/stats/timeseries/MarketSizeProgress.do"


def latest_raw_html() -> Path | None:
    candidates = sorted(RAW_DIR.glob("market_size_progress*.html"))
    return candidates[-1] if candidates else None

# (h5 섹션 제목, 표 안 행 라벨) -> (metric, unit)
METRIC_MAP = {
    ("연간 화랑 작품거래 추이", "판매 금액(백만 원)"): ("gallery_sales_krw", "백만원"),
    ("연간 경매사 작품거래 추이", "판매 금액(백만 원)"): ("auction_total_krw", "백만원"),
    ("연간 경매사 작품거래 추이", "낙찰률(%)"): ("auction_sell_through_rate", "%"),
    ("연간 아트페어 작품거래 추이", "판매 금액(백만 원)"): ("artfair_sales_krw", "백만원"),
}

NUM_RE = re.compile(r"^-?[\d,]+(\.\d+)?$")


def parse_number(s: str) -> float | None:
    s = s.strip().replace(",", "")
    if not NUM_RE.match(s.replace(",", "") if "," not in s else s):
        pass
    try:
        return float(s)
    except ValueError:
        return None


def extract_year_series(raw_html: Path) -> dict[tuple[str, int], tuple[float, str]]:
    """(metric, year) -> (value, unit)"""
    html = raw_html.read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")

    result: dict[tuple[str, int], tuple[float, str]] = {}
    for t in tables:
        h5 = t.find_previous("h5")
        section = h5.get_text(strip=True) if h5 else None
        rows = t.find_all("tr")
        if not rows:
            continue
        header_cells = [c.get_text(strip=True) for c in rows[0].find_all(["th", "td"])]
        if not header_cells or header_cells[0] != "구분":
            continue
        years = header_cells[1:]
        for tr in rows[1:]:
            cells = [c.get_text(strip=True) for c in tr.find_all(["th", "td"])]
            if not cells:
                continue
            label = cells[0]
            key = (section, label)
            if key not in METRIC_MAP:
                continue
            metric, unit = METRIC_MAP[key]
            for year_str, val_str in zip(years, cells[1:]):
                if not re.fullmatch(r"\d{4}", year_str):
                    continue
                val = parse_number(val_str)
                if val is None:
                    continue
                result[(metric, int(year_str))] = (val, unit)
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    raw_html = latest_raw_html()
    if raw_html is None:
        print(f"[kams_stats_load] raw 파일 없음: {RAW_DIR} — crawlers/kams_stats.py 먼저 실행")
        return
    print(f"[kams_stats_load] raw 파일: {raw_html.name}")

    series = extract_year_series(raw_html)

    rows = []
    for (metric, year), (value, unit) in series.items():
        rows.append(
            {
                "year": year,
                "metric": metric,
                "value": value,
                "unit": unit,
                "source_url": SOURCE_URL,
                "note": f"원문 표기 그대로(K-ARTMARKET 시장조사 통계, {year}년)",
            }
        )

    # market_total_krw = gallery + auction + artfair (세 지표 모두 있는 연도만, 파생값 명시)
    years_all = {y for (_, y) in series.keys()}
    for year in sorted(years_all):
        g = series.get(("gallery_sales_krw", year))
        a = series.get(("auction_total_krw", year))
        f = series.get(("artfair_sales_krw", year))
        if g and a and f:
            total = g[0] + a[0] + f[0]
            rows.append(
                {
                    "year": year,
                    "metric": "market_total_krw",
                    "value": total,
                    "unit": "백만원",
                    "source_url": SOURCE_URL,
                    "note": "[산출값] 화랑+경매+아트페어 판매금액 합산(원문에 합계 항목 없음, 추정 아님 — 세 원문 수치의 단순 합)",
                }
            )

    rows.sort(key=lambda r: (r["metric"], r["year"]))

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_rows": len(rows),
        "metrics": sorted({r["metric"] for r in rows}),
        "years": sorted({r["year"] for r in rows}),
        "rows": rows,
    }
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = DOCS_DIR / f"kams_통계_리포트_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[kams_stats_load] 행 {len(rows)}건 (지표: {report['metrics']})")
    print(f"[kams_stats_load] 리포트: {report_path}")

    if not args.apply:
        print("[kams_stats_load] dry-run — --apply로 실제 반영")
        return

    conn = get_connection()
    cur = conn.cursor()
    inserted = 0
    updated = 0
    unchanged = 0
    diffs = []
    for r in rows:
        cur.execute(
            "select value from market_stats_kr where year=%s and metric=%s and coalesce(source_url,'')=coalesce(%s,'')",
            (r["year"], r["metric"], r["source_url"]),
        )
        existing = cur.fetchone()
        cur.execute(
            """
            insert into market_stats_kr (year, metric, value, unit, source_url, note)
            values (%s, %s, %s, %s, %s, %s)
            on conflict (year, metric, coalesce(source_url,'')) do update
              set value = excluded.value, unit = excluded.unit, note = excluded.note
              where market_stats_kr.value is distinct from excluded.value
            returning id
            """,
            (r["year"], r["metric"], r["value"], r["unit"], r["source_url"], r["note"]),
        )
        touched = cur.fetchone() is not None
        if existing is None:
            if touched:
                inserted += 1
        elif touched:
            updated += 1
            diffs.append({"year": r["year"], "metric": r["metric"], "old": float(existing[0]) if existing[0] is not None else None, "new": r["value"]})
        else:
            unchanged += 1
    conn.commit()
    print(f"[kams_stats_load] 적용 완료 — 신규 {inserted}건 / 갱신 {updated}건 / 변동없음 {unchanged}건")
    if diffs:
        print("[kams_stats_load] 값 변경 상세:")
        for d in diffs:
            print(f"  {d['year']} {d['metric']}: {d['old']} -> {d['new']}")


if __name__ == "__main__":
    main()
