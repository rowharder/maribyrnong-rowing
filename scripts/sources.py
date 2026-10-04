"""Fetchers for each data source.

Each fetch_* function returns plain dicts/lists. Errors are raised; build.py
catches them per source so one broken website never stops the whole update.
"""
import json
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

USER_AGENT = "Mozilla/5.0 (compatible; MaribyrnongRowingDashboard/1.0)"
TIMEOUT = 30


def _get(url, params=None, attempts=2):
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except Exception:
            if attempt == attempts - 1:
                raise
            time.sleep(3)  # one retry for brief network hiccups


def fetch_forecast(src):
    """Hourly forecast from Open-Meteo. Returns {iso_local_hour: {...}}."""
    loc = src["location"]
    fields = ["wind_speed_10m", "wind_gusts_10m", "wind_direction_10m", "temperature_2m",
              "precipitation", "cape", "visibility", "weather_code"]
    raw = json.loads(_get(src["open_meteo_url"], {
        "latitude": loc["latitude"],
        "longitude": loc["longitude"],
        "hourly": ",".join(fields),
        "timezone": loc["timezone"],
        "wind_speed_unit": "kn",
        "forecast_days": src["days_to_show"] + 1,
    }))
    hourly = raw["hourly"]
    out = {}
    for i, t in enumerate(hourly["time"]):
        out[t] = {
            "wind": hourly["wind_speed_10m"][i],
            "gust": hourly["wind_gusts_10m"][i],
            "wind_dir": hourly["wind_direction_10m"][i],
            "temp": hourly["temperature_2m"][i],
            "rain": hourly["precipitation"][i],
            "cape": hourly["cape"][i],
            "visibility": hourly["visibility"][i],
            "code": hourly["weather_code"][i],
        }
    if all(v["wind"] is None for v in out.values()):
        raise ValueError("forecast returned no values")
    return out


def fetch_bom_text_forecast(src):
    """BOM daily text forecast for the Melbourne area. Returns {YYYY-MM-DD: text}."""
    root = ET.fromstring(_get(src["bom_forecast_ftp"]))
    for area in root.iter("area"):
        if area.get("description") != src["bom_forecast_area"]:
            continue
        days = {}
        for period in area.iter("forecast-period"):
            day = period.get("start-time-local")[:10]
            texts = [t.text for t in period if t.get("type") in ("forecast", "precis") and t.text]
            if texts:
                days[day] = " ".join(texts)
        if days:
            return days
    raise ValueError(f"area {src['bom_forecast_area']} not found")


def fetch_bom_observations(src):
    data = json.loads(_get(src["bom_obs_url"]))["observations"]["data"]
    latest = data[0]
    return {
        "station": src["bom_obs_name"],
        "time": latest["local_date_time_full"],
        "temp": latest["air_temp"],
        "wind_kn": latest.get("wind_spd_kt"),
        "gust_kn": latest.get("gust_kt"),
        "wind_dir": latest.get("wind_dir"),
        "rain_since_9am": latest.get("rain_trace"),
        "visibility_km": latest.get("vis_km"),
    }


def fetch_bom_warnings(src):
    """Current Victorian warnings. Returns [{title, link}]."""
    root = ET.fromstring(_get(src["bom_warnings_url"]))
    out = []
    for item in root.iter("item"):
        title = re.sub(r"\s+", " ", item.findtext("title") or "").strip()
        out.append({"title": title, "link": (item.findtext("link") or "").strip()})
    return out


def fetch_tides(src, start: date, days: int):
    """High/low tide predictions. Returns [{time: iso_local, type: High|Low, height}]."""
    tz = ZoneInfo(src["location"]["timezone"])
    page = _get(src["bom_tides_url"], {
        "aac": src["bom_tide_station"]["aac"],
        "type": "tide",
        "date": start.strftime("%d-%m-%Y"),
        "region": "VIC",
        "tz": src["location"]["timezone"],
        "days": days,
    })
    # Each entry: <th>High|Low</th> <td data-time-local="ISO">..</td> ... <td class="height">0.96 m</td>
    pattern = (r'class="instance[^"]*">(High|Low)</th>\s*<td[^>]*data-time-local="([^"]+)"'
               r'.*?class="height[^"]*">\s*([\d.]+)\s*m')
    out = [{"time": datetime.fromisoformat(t).astimezone(tz).isoformat(), "type": kind, "height": float(h)}
           for kind, t, h in re.findall(pattern, page, re.S)]
    if len(out) < 4:
        raise ValueError("could not parse tide table")
    return out


def fetch_gauge(src, gauge, now: datetime):
    """Recent hourly river level (and flow, where recorded) for one Melbourne Water gauge."""
    base = f"{src['melbourne_water_api']}/{gauge['id']}"
    params = {"fromDate": (now - timedelta(days=2)).strftime("%Y-%m-%d"),
              "toDate": now.strftime("%Y-%m-%d")}
    levels = json.loads(_get(f"{base}/river-level/hourly/range", params))["hourlyRiverLevelsData"]
    levels = sorted((r["dateTime"], r["meanRiverLevel"]) for r in levels if r["meanRiverLevel"] is not None)
    if not levels:
        raise ValueError("no level data")
    out = {
        "id": gauge["id"],
        "name": gauge["name"],
        "role": gauge["role"],
        "time": levels[-1][0],
        "level_m": levels[-1][1],
        "rise_m_per_hr": _rise_rate(levels),
        "history": [{"time": t, "level_m": v} for t, v in levels[-72:]],
    }
    if gauge["role"] == "course":
        # 6-minute readings: this gauge is tidal, so show the actual water level at the course.
        try:
            live = json.loads(_get(f"{base}/river-level/live"))["liveRiverLevelsData"]
            live = sorted((r["dateTime"], r["meanRiverLevel"]) for r in live if r["meanRiverLevel"] is not None)
            out["live"] = [{"time": t, "level_m": v} for t, v in live]
            if len(live) > 5:
                out["time"], out["level_m"] = live[-1]
                out["rise_m_per_hr"] = round((live[-1][1] - live[-6][1]) * 2, 3)  # last 30 min
        except Exception:
            pass
    if gauge["role"] == "keilor":
        try:
            flows = json.loads(_get(f"{base}/river-flow/hourly/range", params))["hourlyRiverFlowsData"]
            flows = sorted((r["dateTime"], r["meanRiverFlow_m3"]) for r in flows if r["meanRiverFlow_m3"] is not None)
            if flows:
                out["flow_m3s"] = flows[-1][1]
                out["flow_history"] = [{"time": t, "flow_m3s": v} for t, v in flows[-72:]]
        except Exception:
            pass
    return out


def _rise_rate(levels, hours=3):
    """Average change in level (m/hr) over the last few hourly readings."""
    if len(levels) <= hours:
        return None
    return round((levels[-1][1] - levels[-1 - hours][1]) / hours, 3)


def fetch_catchment_rain(src, now: datetime, days=30):
    """Hourly observed rain at each catchment gauge for the last `days`. Returns {gauge_id: {"YYYY-MM-DD HH": mm}}."""
    out = {}
    params = {"fromDate": (now - timedelta(days=days)).strftime("%Y-%m-%d"), "toDate": now.strftime("%Y-%m-%d")}
    for gid in src["river_forecast"]["rain_gauges"]:
        raw = json.loads(_get(f"{src['melbourne_water_api']}/{gid}/rain/hourly/range", params))
        key = next(k for k in raw if k.endswith("Data"))
        out[gid] = {r["dateTime"][:13]: r.get("currentRainfallLevel") for r in raw[key]}
    return out


def fetch_catchment_rain_forecast(src):
    """Hourly forecast rain averaged over the catchment points. Returns {"YYYY-MM-DDTHH:00": mm}."""
    pts = src["river_forecast"]["forecast_points"]
    raw = json.loads(_get(src["open_meteo_url"], {
        "latitude": ",".join(str(p["latitude"]) for p in pts),
        "longitude": ",".join(str(p["longitude"]) for p in pts),
        "hourly": "precipitation",
        "timezone": src["location"]["timezone"],
        "forecast_days": 4,
    }))
    raw = raw if isinstance(raw, list) else [raw]
    times = raw[0]["hourly"]["time"]
    out = {}
    for i, t in enumerate(times):
        vals = [r["hourly"]["precipitation"][i] for r in raw if r["hourly"]["precipitation"][i] is not None]
        out[t] = sum(vals) / len(vals) if vals else 0.0
    return out
