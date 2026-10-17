"""Check the Flow estimate against what people have seen on the water (config/flow_observations.json).

Add a sighting. Do it within 3 days, while Essendon's wind for that time is still on BOM's site:
    python3 scripts/check_flow.py add "2026-10-17 08:00" out --note "very slightly downstream"
    python3 scripts/check_flow.py add "2026-10-20 06:30" in --kmh 0.5

Compare every sighting with the model, using the settings in config/sources.json as they are now
(so after changing depth_m or ungauged_factor, run it again to see whether the fit got better):
    python3 scripts/check_flow.py

seen is out (downstream), in (upstream) or still.
"""
import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path

import flow_model
import sources

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "config" / "flow_observations.json"
STILL_KMH = 0.1  # model speeds under this count as still water


def parse_time(s):
    return datetime.fromisoformat(s.replace("T", " ")[:16])


def nearest(points, t, within=timedelta(minutes=30)):
    """The (time, value) in points closest to t, if it's within `within`; else None."""
    best = min(points, key=lambda p: abs(p[0] - t), default=None)
    return best if best and abs(best[0] - t) <= within else None


def estimate_at(levels, flows, t, model, geom):
    """The model's speed row at t from measured Poyntons levels [(time, m)] and Keilor flows [(time, m³/s)]."""
    epoch = [(ft.timestamp(), q) for ft, q in flows]
    lag = timedelta(hours=geom["keilor_lag_hours"])
    rows = flow_model.measured_rows(levels, lambda x: flow_model.interp(epoch, (x - lag).timestamp()), model, geom)
    hit = nearest([(datetime.fromisoformat(r["time"]), r) for r in rows], t)
    return hit[1] if hit else None


def direction(kmh):
    return "still" if abs(kmh) < STILL_KMH else "out" if kmh > 0 else "in"


def fetch_series(src, gauge_id, kind, t):
    """Hourly Melbourne Water readings from the day before t to the day after."""
    field, value = {"river-level": ("hourlyRiverLevelsData", "meanRiverLevel"),
                    "river-flow": ("hourlyRiverFlowsData", "meanRiverFlow_m3")}[kind]
    params = {"fromDate": f"{t - timedelta(days=1):%Y-%m-%d}", "toDate": f"{t + timedelta(days=1):%Y-%m-%d}"}
    data = json.loads(sources._get(f"{src['melbourne_water_api']}/{gauge_id}/{kind}/hourly/range", params))[field]
    return sorted((parse_time(r["dateTime"]), r[value]) for r in data if r[value] is not None)


def fetch_wind(src, t):
    """Essendon Airport wind nearest t (BOM keeps about 3 days), or None."""
    data = json.loads(sources._get(src["bom_obs_url"]))["observations"]["data"]
    hit = nearest([(datetime.strptime(r["local_date_time_full"], "%Y%m%d%H%M%S"), r) for r in data], t)
    return None if not hit else {"dir": hit[1]["wind_dir"], "kmh": hit[1]["wind_spd_kmh"], "gust_kmh": hit[1]["gust_kmh"]}


def load_log():
    return json.loads(LOG.read_text())


def add(args, src):
    t = parse_time(args.time)
    log = load_log()
    wind = None
    try:
        wind = fetch_wind(src, t)
    except Exception as e:
        print(f"Couldn't get the wind: {e}")
    if wind is None:
        print("No Essendon wind for that time (BOM keeps about 3 days) - saved without it.")
    entry = {"time": f"{t:%Y-%m-%d %H:%M}", "seen": args.seen, "kmh": args.kmh, "note": args.note, "wind": wind}
    log["observations"] = sorted(log["observations"] + [entry], key=lambda o: o["time"])
    LOG.write_text(json.dumps(log, indent=1, ensure_ascii=False) + "\n")
    print(f"Added {entry['time']} {args.seen}.")


def report(src):
    model = json.loads((ROOT / "config" / "flow_model.json").read_text())
    geom = src["flow"]
    ids = {g["role"]: g["id"] for g in src["gauges"]}
    print(f"Settings: depth {geom['depth_m']} m, width {geom['width_m']} m, "
          f"ungauged factor {geom.get('ungauged_factor', 1.0)}")
    print(f"{'time':16}  {'seen':12}  {'model':>6}  {'river':>5}  {'tide':>5}  {'Keilor':>6}  {'wind':10}  agrees")
    for o in load_log()["observations"]:
        t = parse_time(o["time"])
        seen = o["seen"] + (f" {o['kmh']}" if o.get("kmh") is not None else "")
        w = o.get("wind")
        wind = f"{w['dir']} {w['kmh']}" if w else "-"
        try:
            r = estimate_at(fetch_series(src, ids["course"], "river-level", t),
                            fetch_series(src, ids["keilor"], "river-flow", t), t, model, geom)
        except Exception as e:
            print(f"{o['time']:16}  {seen:12}  couldn't fetch gauge data: {e}")
            continue
        if r is None:
            print(f"{o['time']:16}  {seen:12}  no gauge data at that time")
            continue
        agrees = "yes" if direction(r["speed_kmh"]) == o["seen"] else "NO"
        print(f"{o['time']:16}  {seen:12}  {r['speed_kmh']:+6.2f}  {r['river_kmh']:5.2f}  {r['tide_kmh']:+5.2f}  "
              f"{r['flow_m3s']:6.1f}  {wind:10}  {agrees}")
    print("model/river/tide in km/h (positive = downstream); Keilor in m³/s; wind at Essendon Airport in km/h.")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd")
    a = sub.add_parser("add", help="add a sighting")
    a.add_argument("time", help='local time, e.g. "2026-10-17 08:00"')
    a.add_argument("seen", choices=["out", "in", "still"])
    a.add_argument("--kmh", type=float, help="rough speed seen, if known")
    a.add_argument("--note", default="")
    args = p.parse_args()
    src = json.loads((ROOT / "config" / "sources.json").read_text())
    add(args, src) if args.cmd == "add" else report(src)


if __name__ == "__main__":
    main()
