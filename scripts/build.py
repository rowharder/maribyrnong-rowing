"""Fetch every source, apply the rules, and write site/data/latest.json.

Run:  python3 scripts/build.py
"""
import json
import sys
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import flow_model
import river_model
import rules
import sources

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "site" / "data" / "latest.json"


def load(name):
    return json.loads((ROOT / "config" / name).read_text())


def attempt(status, name, fn, *args):
    try:
        result = fn(*args)
        status[name] = "ok"
        return result
    except Exception as e:  # one broken source must never stop the update
        status[name] = f"error: {e}"
        traceback.print_exc(file=sys.stderr)
        return None


def at(day, hhmm, tz):
    h, m = map(int, hhmm.split(":"))
    return datetime(day.year, day.month, day.day, h, m, tzinfo=tz)


def session_hours(forecast, start, end):
    """Forecast rows for each whole hour touching the session (missing hours = None)."""
    if not forecast:
        return []
    t = start.replace(minute=0)
    rows = []
    while t <= end:
        rows.append(forecast.get(t.strftime("%Y-%m-%dT%H:00")))
        t += timedelta(hours=1)
    return rows


def course_levels(course, now):
    """Measured water level at the course for the last day: hourly history, then the 6-minute live readings."""
    tz = now.tzinfo
    parse = lambda t: datetime.fromisoformat(t).replace(tzinfo=tz)
    live = [(parse(r["time"]), r["level_m"]) for r in course.get("live", [])]
    first_live = live[0][0] if live else now
    hourly = [(parse(r["time"]), r["level_m"]) for r in course["history"] if parse(r["time"]) < first_live]
    return [(t, v) for t, v in hourly + live if t >= now - timedelta(hours=24)]


def course_now(gauges):
    """Water level at the course right now and whether the tide is coming in or going out."""
    course = next((g for g in gauges if g["role"] == "course"), None)
    if not course:
        return None
    rate = course.get("rise_m_per_hr")
    return {
        "gauge": course["name"],
        "time": course["time"],
        "level_m": course["level_m"],
        "rate_m_per_hr": rate,
        "state": None if rate is None else ("Outgoing" if rate < -0.02 else "Incoming" if rate > 0.02 else "Slack"),
    }


def keilor_flow_forecast(src, keilor, now, status):
    """Keilor flow: measured, then our forecast from catchment rain. Returns ([(time, m³/s)], notes, rain totals)."""
    tz = now.tzinfo
    measured = [(datetime.strptime(r["time"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz), r["flow_m3s"])
                for r in keilor.get("flow_history") or []]
    cfg = src["river_forecast"]
    model_path = ROOT / "config" / "river_model.json"
    past = attempt(status, "Melbourne Water catchment rain", sources.fetch_catchment_rain, src, now, 30)
    future = attempt(status, "Catchment rain forecast (Open-Meteo)", sources.fetch_catchment_rain_forecast, src)
    if past is None or not model_path.exists():
        return measured, ["Rain data unavailable – river flow held at its current value."], {}
    model = json.loads(model_path.read_text())
    t0 = now.replace(minute=0, second=0, microsecond=0)
    past_hours = [t0 - timedelta(hours=h) for h in range(river_model.HISTORY_HOURS - 1, -1, -1)]
    past_rain = river_model.catchment_rain(
        [river_model.clean_rain([past[g].get(t.strftime("%Y-%m-%d %H")) for t in past_hours]) for g in past])
    horizon = cfg["hours_ahead"]
    future_hours = [t0 + timedelta(hours=h) for h in range(1, horizon + 1)]
    future_rain = [(future or {}).get(t.strftime("%Y-%m-%dT%H:00"), 0.0) or 0.0 for t in future_hours]
    q_now = keilor["flow_m3s"]
    hist = [q for _, q in measured] or [q_now]
    q_3h = hist[-4] if len(hist) >= 4 else None
    flows = river_model.forecast(model, q_now, q_3h, past_rain, future_rain, horizon)
    last = measured[-1][0] if measured else now
    notes = [] if future is not None else ["Rain forecast unavailable – river forecast assumes no more rain."]
    rain = {"past_72h_mm": round(sum(past_rain[-72:]), 1),
            "next_72h_mm": round(sum(future_rain), 1) if future is not None else None}
    return measured + [(t, q) for t, q in zip(future_hours, flows) if t > last], notes, rain


def build_flow(src, th, gauges, tides, now, last_session_end, status):
    """Water speed at the course (flow_model.py): estimated from measurements for the last day, then
    forecast from Keilor's flow forecast and the tide prediction. Also the water heights at Poyntons and
    at the river mouth (Williamstown), on the course gauge's datum."""
    keilor = next((g for g in gauges if g["role"] == "keilor"), None)
    course = next((g for g in gauges if g["role"] == "course"), None)
    model_path = ROOT / "config" / "flow_model.json"
    if not keilor or keilor.get("flow_m3s") is None or not tides or not model_path.exists():
        return None
    model = json.loads(model_path.read_text())
    geom = src["flow"]
    flows, notes, rain = keilor_flow_forecast(src, keilor, now, status)
    lag = timedelta(hours=geom["keilor_lag_hours"])
    flow_end = flows[-1][0] + lag
    epoch = [(t.timestamp(), q) for t, q in flows]

    def q_at(t):  # Keilor's flow reaching the course at t; held at its last value past the forecast
        x = (t - lag).timestamp()
        return flows[-1][1] if x > epoch[-1][0] else flow_model.interp(epoch, x)

    tide_lag = timedelta(minutes=src["tide_lag_minutes"])
    tide = lambda t: rules.tide_at(tides, t - tide_lag)
    observed = course_levels(course, now) if course else []
    gaps = [v - h - flow_model.setup_m(q, model["setup"]) for t, v in observed[-60:]
            if (h := tide(t)[0]) is not None and (q := q_at(t)) is not None]
    offset = sorted(gaps)[len(gaps) // 2] if gaps else 0.0
    times, t = [], now.replace(minute=now.minute // 15 * 15, second=0, microsecond=0)
    while t <= max(now + timedelta(hours=src["river_forecast"]["hours_ahead"]), last_session_end):
        times.append(t)
        t += timedelta(minutes=15)
    forecast = flow_model.forecast_rows(times, q_at, tide, offset, model, geom)
    for r in forecast:
        r["held"] = datetime.fromisoformat(r["time"]) > flow_end
    past_mouth = []
    t = (now - timedelta(hours=24)).replace(minute=0, second=0, microsecond=0)
    while t < now:
        if (h := tide(t)[0]) is not None:
            past_mouth.append({"time": t.isoformat(timespec="minutes"), "level_m": round(h + offset, 3)})
        t += timedelta(minutes=15)
    iso = lambda t: t.isoformat(timespec="minutes")
    return {
        "issued": iso(now),
        "estimated": flow_model.measured_rows(observed, q_at, model, geom)[::2],
        "forecast": forecast,
        "observed_levels": [{"time": iso(t), "level_m": v} for t, v in observed[::2]],
        "mouth_past": past_mouth,
        "flow_forecast_end": iso(flow_end),
        "thresholds": {"yellow": th["flow"]["speed_kmh"]["amber"], "red": th["flow"]["speed_kmh"]["red"]},
        "geometry": {k: v for k, v in geom.items() if not k.startswith("_")},
        "rain": rain,
        "notes": notes,
    }


def session_flow(flow, start, end):
    """Forecast speed rows during a session, and a note if they go past the river forecast."""
    if not flow:
        return [], ""
    rows = [r for r in flow["forecast"] if start <= datetime.fromisoformat(r["time"]) <= end]
    held = any(r["held"] for r in rows)
    return rows, "Past the 3-day river forecast – Keilor flow held at its last value." if held else " ".join(flow["notes"])


def site_version():
    """Short fingerprint of the page code, so open pages can tell when it changed."""
    import hashlib
    h = hashlib.sha1()
    for name in ("index.html", "app.js", "styles.css", "config.js"):
        h.update((ROOT / "site" / name).read_bytes())
    return h.hexdigest()[:10]


def main():
    src, th = load("sources.json"), load("thresholds.json")
    loc = src["location"]
    tz = ZoneInfo(loc["timezone"])
    now = datetime.now(tz)
    today = now.date()
    status = {}

    forecast = attempt(status, "Hourly forecast (Open-Meteo)", sources.fetch_forecast, src)
    day_text = attempt(status, "BOM text forecast", sources.fetch_bom_text_forecast, src) or {}
    obs = attempt(status, "BOM observations", sources.fetch_bom_observations, src)
    raw_warnings = attempt(status, "BOM warnings", sources.fetch_bom_warnings, src)
    tides = attempt(status, "BOM tide predictions", sources.fetch_tides, src,
                    today - timedelta(days=1), src["days_to_show"] + 2) or []
    gauges = []
    for g in src["gauges"]:
        r = attempt(status, f"Melbourne Water gauge: {g['name']}", sources.fetch_gauge, src, g, now)
        if r:
            gauges.append(r)

    warnings = rules.classify_warnings(raw_warnings)
    if raw_warnings is None:
        # Can't see warnings: flag it rather than silently assuming none.
        warnings["flood_watch"].append({"title": "BOM warnings feed unavailable - check bom.gov.au", "link": ""})
    sessions = []
    for d in range(src["days_to_show"]):
        day = today + timedelta(days=d)
        for sess in src["sessions"]:
            if day.weekday() >= 5 and "weekend" in sess:
                sess = sess | sess["weekend"]
            start, end = at(day, sess["start"], tz), at(day, sess["end"], tz)
            if end >= now:
                sessions.append((d, day, sess, start, end))
    last_end = max((e for *_, e in sessions), default=now)
    flow = attempt(status, "Flow estimate", build_flow, src, th, gauges, tides, now, last_end, status)

    columns = []
    for d, day, s, start, end in sessions:
        rows, note = session_flow(flow, start, end)
        soon = start - now < timedelta(hours=24)  # BOM Flood Watch only counts for the next 24 h
        result = rules.evaluate_session(
            start=start, end=end, is_morning=s["id"] == "am",
            hours=session_hours(forecast, start, end),
            day_text=day_text.get(day.isoformat()),
            warnings=warnings, flow=rules.eval_flow(rows, gauges, warnings, th, soon, note),
            lat=loc["latitude"], lon=loc["longitude"], th=th, now=now,
        )
        columns.append({
            "date": day.isoformat(),
            "day_label": "Today" if d == 0 else ("Tomorrow" if d == 1 else f"{day:%a}"),
            "date_label": f"{day:%a} {day.day} {day:%b}",
            "session": s["id"],
            "session_label": s["label"],
            "time_label": rules.clock_range(start, end),
            "start": start.isoformat(timespec="minutes"),
            "end": end.isoformat(timespec="minutes"),
            "bom_text": day_text.get(day.isoformat()),
            **result,
        })

    next_tides = [t for t in tides if datetime.fromisoformat(t["time"]) > now][:4]
    out = {
        "generated_at": now.isoformat(timespec="minutes"),
        "site_version": site_version(),
        "location": loc["name"],
        "factors": [{"id": k, "label": v, "links": src.get("verify_links", {}).get(k, [])} for k, v in rules.FACTORS],
        "lights_link": src.get("lights_link"),
        "columns": columns,
        "now": {
            "observations": obs,
            "gauges": [{k: v for k, v in g.items() if k not in ("history", "live", "flow_history")} for g in gauges],
            "tides": next_tides,
            "tide_station": src["bom_tide_station"]["name"],
            "tide_lag_minutes": src["tide_lag_minutes"],
            "course_tide": course_now(gauges),
            "flow": flow,
            "warnings": [{"title": rules.warning_title(w), "link": w["link"]}
                         for w in warnings["flood"] + warnings["flood_watch"] + warnings["thunderstorm"] + warnings["severe_weather"]],
        },
        "sources": status,
        "stale_after_hours": th["stale_after_hours"],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False))
    failed = [k for k, v in status.items() if v != "ok"]
    print(f"Wrote {OUT.relative_to(ROOT)}: {len(columns)} sessions. Sources failed: {failed or 'none'}")


if __name__ == "__main__":
    main()
