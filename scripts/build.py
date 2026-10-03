"""Fetch every source, apply the rules, and write site/data/latest.json.

Run:  python3 scripts/build.py
"""
import json
import sys
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

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

    columns = []
    for d in range(src["days_to_show"]):
        day = today + timedelta(days=d)
        for s in src["sessions"]:
            if day.weekday() >= 5 and "weekend" in s:
                s = s | s["weekend"]
            start, end = at(day, s["start"], tz), at(day, s["end"], tz)
            if end < now:
                continue
            result = rules.evaluate_session(
                start=start, end=end, is_morning=s["id"] == "am",
                hours=session_hours(forecast, start, end),
                day_text=day_text.get(day.isoformat()),
                tides=tides, warnings=warnings, flood=flood,
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
