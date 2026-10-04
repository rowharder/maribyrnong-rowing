"""Download hourly Melbourne Water history used to fit the river and flow models.

Run:  python3 scripts/fetch_history.py [first_year]
Saves one JSON per series per year in history/ (not committed). Re-running only fetches missing years
(plus the current year, which is always refreshed).
"""
import json
import sys
import time
from datetime import date
from pathlib import Path

import sources

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "history"
API = "https://api.melbournewater.com.au/rainfall-river-level"

SERIES = [
    ("230105A", "river-flow", "meanRiverFlow_m3"),
    ("230105A", "river-level", "meanRiverLevel"),
    ("230105A", "rain", "currentRainfallLevel"),
    ("230106A", "river-level", "meanRiverLevel"),   # tidal gauge near Poyntons (flow model)
    ("230100A", "rain", "currentRainfallLevel"),
    ("230104A", "rain", "currentRainfallLevel"),
    ("587014", "rain", "currentRainfallLevel"),
]


def fetch_year(site, kind, field, year):
    path = OUT / f"{site}_{kind}_{year}.json"
    if path.exists() and year != date.today().year:
        return path
    raw = json.loads(sources._get(f"{API}/{site}/{kind}/hourly/range",
                                  {"fromDate": f"{year}-01-01", "toDate": f"{year}-12-31"}))
    key = next(k for k in raw if k.endswith("Data"))
    rows = {r["dateTime"][:13]: r.get(field) for r in raw[key]}
    path.write_text(json.dumps(rows))
    time.sleep(0.3)
    return path


def main():
    first = int(sys.argv[1]) if len(sys.argv) > 1 else 2014
    OUT.mkdir(exist_ok=True)
    for year in range(first, date.today().year + 1):
        for site, kind, field in SERIES:
            try:
                p = fetch_year(site, kind, field, year)
                n = sum(v is not None for v in json.loads(p.read_text()).values())
                print(f"{year} {site} {kind}: {n} hours")
            except Exception as e:
                print(f"{year} {site} {kind}: FAILED {e}")


if __name__ == "__main__":
    main()
