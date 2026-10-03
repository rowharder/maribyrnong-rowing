"""Fetch every source, apply the rules, and write site/data/latest.json.

Run:  python3 scripts/build.py
"""
import json
import sys
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

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


def build_course_tide(gauges, tides, lag_minutes, now):
    """Observed water level at the course gauge plus the Williamstown prediction lined up against it.

    The prediction is shifted to the gauge's datum using the average gap between observed and
    predicted over the last day - this also absorbs extra height from river flow.
    """
    course = next((g for g in gauges if g["role"] == "course"), None)
    if not course or not tides:
        return None
    tz = now.tzinfo
    parse = lambda t: datetime.fromisoformat(t).replace(tzinfo=tz)
    live = [(parse(r["time"]), r["level_m"]) for r in course.get("live", [])]
    first_live = live[0][0] if live else now
    hourly = [(parse(r["time"]), r["level_m"]) for r in course["history"] if parse(r["time"]) < first_live]
    observed = [(t, v) for t, v in hourly + live if t >= now - timedelta(hours=24)]
    lag = timedelta(minutes=lag_minutes)
    gaps = [v - h for t, v in observed[-60:] if (h := rules.tide_at(tides, t - lag)[0]) is not None]
    if not gaps:
        return None
    offset = sorted(gaps)[len(gaps) // 2]
    predicted = []
    t = (now - timedelta(hours=24)).replace(minute=0, second=0, microsecond=0)
    while t <= now + timedelta(hours=30):
        h = rules.tide_at(tides, t - lag)[0]
        if h is not None:
            predicted.append({"time": t.isoformat(timespec="minutes"), "level_m": round(h + offset, 3)})
        t += timedelta(minutes=15)
    rate = course.get("rise_m_per_hr")
    return {
        "gauge": course["name"],
        "time": course["time"],
        "level_m": course["level_m"],
        "rate_m_per_hr": rate,
        "state": None if rate is None else ("Outgoing" if rate < -0.02 else "Incoming" if rate > 0.02 else "Slack"),
        "observed": [{"time": t.isoformat(timespec="minutes"), "level_m": v} for t, v in observed[::2]],
        "predicted": predicted,
    }


def build_river_forecast(src, th, gauges, now, status):
    """Our experimental Keilor forecast: observed, 'with forecast rain' and 'if no more rain'."""
    cfg = src.get("river_forecast")
    model_path = ROOT / "config" / "river_model.json"
    keilor = next((g for g in gauges if g["role"] == "keilor"), None)
    if not cfg or not model_path.exists() or not keilor or keilor.get("flow_m3s") is None:
        return None
    model = json.loads(model_path.read_text())
    past = attempt(status, "Melbourne Water catchment rain", sources.fetch_catchment_rain, src, now, 30)
    future = attempt(status, "Catchment rain forecast (Open-Meteo)", sources.fetch_catchment_rain_forecast, src)
    if past is None:
        return None
    tz = now.tzinfo
    t0 = now.replace(minute=0, second=0, microsecond=0)
    past_hours = [t0 - timedelta(hours=h) for h in range(river_model.HISTORY_HOURS - 1, -1, -1)]
    past_rain = river_model.catchment_rain(
        [river_model.clean_rain([past[g].get(t.strftime("%Y-%m-%d %H")) for t in past_hours]) for g in past])
    horizon = cfg["hours_ahead"]
    future_hours = [t0 + timedelta(hours=h) for h in range(1, horizon + 1)]
    future_rain = [(future or {}).get(t.strftime("%Y-%m-%dT%H:00"), 0.0) or 0.0 for t in future_hours]
    rating = model["rating"]
    level = lambda q: round(river_model.flow_to_level(q, rating), 3)
    q_now = keilor["flow_m3s"]
    hist = keilor.get("flow_history") or [q_now]
    q_3h = hist[-4] if len(hist) >= 4 else None
    wet = river_model.forecast(model, q_now, q_3h, past_rain, future_rain, horizon)
    dry = river_model.forecast(model, q_now, q_3h, past_rain, [0.0] * horizon, horizon)
    iso = lambda t: t.isoformat(timespec="minutes")
    normal = th["flood"]["keilor_normal_m"]
    band = th["flood"]["keilor_above_normal_m"]
    # Shift so the forecast starts exactly at the measured level (rating curve isn't perfect).
    offset = keilor["level_m"] - level(keilor["flow_m3s"])
    return {
        "issued": iso(now),
        "use_for_lights": cfg["use_for_lights"],
        "observed": [{"time": iso(datetime.strptime(r["time"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz)), "level_m": r["level_m"]}
                     for r in keilor["history"]],
        "with_rain": [{"time": iso(t), "level_m": round(level(q) + offset, 3)} for t, q in zip(future_hours, wet)],
        "no_rain": [{"time": iso(t), "level_m": round(level(q) + offset, 3)} for t, q in zip(future_hours, dry)],
        "rain_past_72h_mm": round(sum(past_rain[-72:]), 1),
        "rain_next_72h_mm": round(sum(future_rain), 1) if future is not None else None,
        "thresholds": {"yellow": round(normal + band["amber"], 2), "red": round(normal + band["red"], 2)},
        "typical_error_m": model.get("validation_2025_2026", {}).get("rain", {}).get("typical_error_m"),
        "typical_error_high_river_m": model.get("validation_2025_2026", {}).get("rain", {}).get("typical_error_high_river_m"),
        "fitted": model.get("fitted"),
    }


def forecast_level_for(river_fc, start, end, now):
    """Highest forecast Keilor level during a session, if the session is >3 h away and within the forecast."""
    if not river_fc or not river_fc["use_for_lights"] or start - now < timedelta(hours=3):
        return None
    vals = [r["level_m"] for r in river_fc["with_rain"]
            if start - timedelta(minutes=30) <= datetime.fromisoformat(r["time"]) <= end + timedelta(minutes=30)]
    return max(vals) if vals else None


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
    flood = rules.eval_flood(gauges, warnings, th)
    river_fc = build_river_forecast(src, th, gauges, now, status)

    columns = []
    for d in range(src["days_to_show"]):
        day = today + timedelta(days=d)
        for s in src["sessions"]:
            if day.weekday() >= 5 and "weekend" in s:
                s = s | s["weekend"]
            start, end = at(day, s["start"], tz), at(day, s["end"], tz)
            if end < now:
                continue
            fc_level = forecast_level_for(river_fc, start, end, now)
            session_flood = flood if fc_level is None else rules.eval_flood(
                gauges, warnings, th, fc_level, f"Highest forecast level during this session ~{fc_level:.2f} m")
            result = rules.evaluate_session(
                start=start, end=end, is_morning=s["id"] == "am",
                hours=session_hours(forecast, start, end),
                day_text=day_text.get(day.isoformat()),
                tides=tides, warnings=warnings, flood=session_flood,
                lat=loc["latitude"], lon=loc["longitude"], th=th,
                tide_lag=src["tide_lag_minutes"], now=now,
            )
            columns.append({
                "date": day.isoformat(),
                "day_label": "Today" if d == 0 else ("Tomorrow" if d == 1 else f"{day:%a}"),
                "date_label": f"{day:%a} {day.day} {day:%b}",
                "session": s["id"],
                "session_label": s["label"],
                "time_label": f"{s['start']}–{s['end']}",
                "start": start.isoformat(timespec="minutes"),
                "end": end.isoformat(timespec="minutes"),
                "bom_text": day_text.get(day.isoformat()),
                **result,
            })

    course_tide = build_course_tide(gauges, tides, src["tide_lag_minutes"], now)
    next_tides = [t for t in tides if datetime.fromisoformat(t["time"]) > now][:4]
    out = {
        "generated_at": now.isoformat(timespec="minutes"),
        "site_version": site_version(),
        "location": loc["name"],
        "factors": [{"id": k, "label": v, "links": src.get("verify_links", {}).get(k, [])} for k, v in rules.FACTORS],
        "columns": columns,
        "now": {
            "observations": obs,
            "gauges": [{k: v for k, v in g.items() if k not in ("history", "live")} for g in gauges],
            "tides": next_tides,
            "tide_station": src["bom_tide_station"]["name"],
            "tide_lag_minutes": src["tide_lag_minutes"],
            "course_tide": course_tide,
            "river_forecast": river_fc,
            "warnings": warnings["flood"] + warnings["flood_watch"] + warnings["storm"],
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
