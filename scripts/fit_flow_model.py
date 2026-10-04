"""Fit the Poyntons water-level setup and check the Flow light against history.

Run:  python3 scripts/fetch_history.py      (downloads history/ - not committed)
      python3 scripts/fit_flow_model.py     (writes config/flow_model.json)

Setup: daily means of the Poyntons gauge take the tide out. Subtracting the typical low-flow daily mean
(within a month either side) takes most of the weather out too. What is left grows with Keilor's flow;
we fit setup = k * flow^p to the median in each flow band.

Then it estimates the water speed every hour from what was measured (Keilor flow and the Poyntons gauge)
and prints a few known events, plus how often old and new rules would have flagged sessions.
"""
import json
import statistics as st
from datetime import date, datetime, timedelta
from pathlib import Path

import fit_river_model as frm
import flow_model as fm

ROOT = Path(__file__).resolve().parent.parent
FLOW_BANDS = [5, 10, 20, 40, 80, 160, 320, 1000]
LOW_FLOW = 5.0
COMPARE_FROM = datetime(2025, 1, 1)
OLD_KEILOR_M = {"amber": 0.6, "red": 1.0}  # the Flood light's Keilor bands before Flow replaced it


def daily_setup(times, flow, poyntons):
    days = {}
    for t, q in zip(times, flow):
        v = poyntons.get(t.strftime("%Y-%m-%d %H"))
        if v is not None and q is not None:
            days.setdefault(t.date(), []).append((v, q))
    daily = sorted((d, st.mean(x[0] for x in r), st.mean(x[1] for x in r)) for d, r in days.items() if len(r) >= 20)
    low = [(d.toordinal(), lv) for d, lv, q in daily if q < LOW_FLOW]

    def base(d):
        near = [lv for t, lv in low if abs(t - d.toordinal()) <= 30]
        return st.median(near) if len(near) >= 5 else None

    rows = [(d, lv - b, q) for d, lv, q in daily if (b := base(d)) is not None]
    return rows, st.median(lv for _, lv in low)


def band_medians(rows):
    out = []
    for a, b in zip(FLOW_BANDS, FLOW_BANDS[1:]):
        band = [(q, s) for _, s, q in rows if a <= q < b]
        if band:
            out.append({"flow_m3s": f"{a}-{b}", "days": len(band), "median_flow": round(st.median(q for q, _ in band), 1),
                        "median_setup_m": round(st.median(s for _, s in band), 3)})
    return out


def hourly_speeds(times, flow, poyntons, model, geom):
    """Speed each hour from measured Keilor flow (lagged) and the Poyntons gauge (centred 2-hour rate)."""
    lag = geom["keilor_lag_hours"]
    key = lambda t: t.strftime("%Y-%m-%d %H")
    out = {}
    for i in range(lag + 1, len(times) - 1):
        q = flow[i - lag]
        h, before, after = (poyntons.get(key(times[j])) for j in (i, i - 1, i + 1))
        if q is None or h is None or before is None or after is None:
            continue
        out[times[i]] = fm.speed_kmh(q, (after - before) / 2, h - model["mean_level_m"], geom)
    return out


def session_hours(day, sessions):
    """The whole hours touching each session, as in build.session_hours."""
    for s in sessions:
        if day.weekday() >= 5 and "weekend" in s:
            s = s | s["weekend"]
        yield s["id"], [datetime(day.year, day.month, day.day, h) for h in range(int(s["start"][:2]), int(s["end"][:2]) + 1)]


def main():
    src = json.loads((ROOT / "config" / "sources.json").read_text())
    th = json.loads((ROOT / "config" / "thresholds.json").read_text())
    geom = src["flow"]
    times, flow, keilor_level, _ = frm.build_series()
    poyntons = frm.load("230106A", "river-level")
    rows, mean_level = daily_setup(times, flow, poyntons)
    bands = band_medians(rows)
    setup = fm.fit_setup([(b["median_flow"], b["median_setup_m"]) for b in bands if b["median_setup_m"] > 0])
    model = {"mean_level_m": round(mean_level, 3), "setup": setup}
    print(f"mean level at Poyntons (low flow) {mean_level:.3f} m; setup = {setup['k']} * flow^{setup['p']}")
    for b in bands:
        fitted = fm.setup_m(b["median_flow"], setup)
        print(f"  flow {b['flow_m3s']:>9} m³/s: {b['days']:4} days, setup {b['median_setup_m']:+.3f} m (fit {fitted:+.3f})")

    speeds = hourly_speeds(times, flow, poyntons, model, geom)
    events = {}
    for name, a, b in [("Oct 2022 flood", "2022-10-13", "2022-10-16"), ("Jan 2024 flood", "2024-01-08", "2024-01-11"),
                       ("Dry week, Feb 2025", "2025-02-01", "2025-02-08"), ("Last 3 days", None, None)]:
        a = datetime.fromisoformat(a) if a else times[-1] - timedelta(days=3)
        b = datetime.fromisoformat(b) if b else times[-1]
        got = [(t, v) for t, v in speeds.items() if a <= t <= b]
        if not got:
            continue
        t_out, v_out = max(got, key=lambda x: x[1][0])
        t_in, v_in = min(got, key=lambda x: x[1][0])
        events[name] = {"fastest_out_kmh": round(v_out[0], 2), "at": f"{t_out:%Y-%m-%d %H:00}",
                        "river_kmh": round(v_out[1], 2), "tide_kmh": round(v_out[2], 2),
                        "fastest_in_kmh": round(-v_in[0], 2)}
        print(f"{name}: fastest out {v_out[0]:.1f} km/h at {t_out:%d %b %Y %H:00} "
              f"(river {v_out[1]:.1f}, tide {v_out[2]:+.1f}); fastest in {-v_in[0]:.1f} km/h")
    for t in sorted(t for t in speeds if t >= times[-1] - timedelta(hours=30) and t.hour in (5, 6, 7, 8)):
        v = speeds[t]
        print(f"  {t:%a %d %b %H:00}: {v[0]:+.2f} km/h (river {v[1]:.2f}, tide {v[2]:+.2f})")

    # How often the old Keilor rule and the new speed rule would have flagged sessions.
    old_band, new_band = OLD_KEILOR_M, th["flow"]["speed_kmh"]
    by_time = dict(zip(times, keilor_level))
    counts = {"old_keilor_level": {"green": 0, "amber": 0, "red": 0}, "new_speed": {"green": 0, "amber": 0, "red": 0}}
    d = COMPARE_FROM.date()
    while d <= times[-1].date():
        for _, hours in session_hours(d, src["sessions"]):
            lv = [by_time[h] for h in hours if by_time.get(h) is not None]
            sp = [abs(speeds[h][0]) for h in hours if h in speeds]
            if not lv or not sp:
                continue
            band = lambda x, b: "red" if x >= b["red"] else "amber" if x >= b["amber"] else "green"
            counts["old_keilor_level"][band(round(max(lv), 2), old_band)] += 1
            counts["new_speed"][band(round(max(sp), 1), new_band)] += 1
        d += timedelta(days=1)
    print(f"Sessions since {COMPARE_FROM:%b %Y}:", json.dumps(counts))

    out = {
        "_comment": "Fitted by scripts/fit_flow_model.py. mean_level_m: typical Poyntons gauge level at low flow "
                    "(gauge datum). setup: how far river flow lifts Poyntons above the tide, k * flow^p.",
        "fitted": date.today().isoformat(),
        **model,
        "setup_by_flow": bands,
        "events": events,
        "sessions_since_2025": counts,
    }
    (ROOT / "config" / "flow_model.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print("wrote config/flow_model.json")


if __name__ == "__main__":
    main()
