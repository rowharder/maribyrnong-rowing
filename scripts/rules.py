"""Risk rules: turn raw data into a traffic light per factor per session.

Every function here is pure (no network), so it can be unit tested.
Levels: "green", "amber", "red", or "unknown" (data missing - check manually).
"""
import copy
import math
import re
from datetime import datetime, timedelta, timezone

GREEN, AMBER, RED, UNKNOWN = "green", "amber", "red", "unknown"
_RANK = {GREEN: 0, UNKNOWN: 1, AMBER: 2, RED: 3}

# Row order on the dashboard.
FACTORS = [
    ("wind", "Wind"),
    ("temp", "Temperature"),
    ("rain", "Rain"),
    ("lightning", "Lightning"),
    ("visibility", "Fog"),
    ("flow", "Flow"),
]

THUNDER_CODES = {95, 96, 99}
FOG_CODES = {45, 48}


def clock(t):
    """12-hour time as shown on the page: 6:50am, 7pm."""
    h12 = t.hour % 12 or 12
    return f"{h12}{f':{t.minute:02d}' if t.minute else ''}{'am' if t.hour < 12 else 'pm'}"


def clock_range(a, b):
    """5:30–7am, 6–8pm, 11:30am–1pm."""
    ca, cb = clock(a), clock(b)
    return f"{ca[:-2]}–{cb}" if ca[-2:] == cb[-2:] else f"{ca}–{cb}"


def worst(*levels):
    return max(levels, key=lambda lv: _RANK[lv]) if levels else UNKNOWN


def factor(level, value, *reasons):
    return {"level": level, "value": value, "reasons": [r for r in reasons if r]}


def _band(x, amber, red=None):
    if red is not None and x >= red:
        return RED
    if x >= amber:
        return AMBER
    return GREEN


# ---------------------------------------------------------------- weather

def eval_wind(hours, th, warnings=None, within_warning_window=False):
    vals = [h["wind"] for h in hours if h and h.get("wind") is not None]
    if not vals:
        return factor(UNKNOWN, "?", "No wind forecast available")
    w = max(vals)
    lv = _band(w, th["wind_kn"]["amber"], th["wind_kn"]["red"])
    gusts = [h["gust"] for h in hours if h and h.get("gust") is not None]
    gust_txt = f"Gusts to {max(gusts):.0f} kn" if gusts else ""
    reasons = [f"Wind up to {w:.0f} kn (yellow from {th['wind_kn']['amber']}, red from {th['wind_kn']['red']})",
               gust_txt]
    if warnings and within_warning_window:
        for warn in warnings["severe_weather"]:
            lv = RED
            reasons.insert(0, f"BOM warning: {warning_title(warn)}")
    return factor(lv, f"{w:.0f} kn", *reasons)


def eval_temp(hours, th):
    vals = [h["temp"] for h in hours if h and h.get("temp") is not None]
    if not vals:
        return factor(UNKNOWN, "?", "No temperature forecast available")
    hi, lo = round(max(vals)), round(min(vals))  # judge on the same whole degrees we display
    lv = _band(hi, th["heat_c"]["amber"], th["heat_c"]["red"])
    reasons = []
    if lv != GREEN:
        reasons.append(f"Hot: up to {hi}°C (yellow from {th['heat_c']['amber']}, red from {th['heat_c']['red']})")
    if lo < th["cold_c"]["amber"]:
        lv = worst(lv, AMBER)
        reasons.append(f"Cold: down to {lo}°C (yellow under {th['cold_c']['amber']}) – dress for a swim")
    if not reasons:
        reasons.append(f"{lo}°C" if lo == hi else f"{lo}–{hi}°C")
    value = f"{hi:.0f}°C" if hi >= th["heat_c"]["amber"] else f"{lo:.0f}°C"
    return factor(lv, value, *reasons)


def eval_rain(hours, th):
    vals = [h["rain"] for h in hours if h and h.get("rain") is not None]
    if not vals:
        return factor(UNKNOWN, "?", "No rain forecast available")
    r = max(vals)
    lv = _band(r, th["rain_mm_per_hr"]["amber"], th["rain_mm_per_hr"].get("red"))
    if lv == GREEN:
        f = factor(GREEN, "Dry" if r < 0.1 else f"{r:.1f} mm", "No rain forecast" if r < 0.1 else f"Light rain, up to {r:.1f} mm/hr")
    else:
        f = factor(lv, f"{r:.1f} mm", f"Rain up to {r:.1f} mm/hr (yellow from {th['rain_mm_per_hr']['amber']})")
    if r >= th["rain_mm_per_hr"]["combo_min"]:
        f["active"] = True  # enough rain to matter in combinations (dark + rain, rain + wind)
    return f


def eval_lightning(hours, day_text, warnings, th, within_warning_window):
    """Lightning in the area is a definite no-go."""
    lt = th["lightning"]
    lv, reasons = GREEN, []
    known = [h for h in hours if h]
    if any(h.get("code") in THUNDER_CODES for h in known):
        lv = RED
        reasons.append("Thunderstorm forecast during the session")
    if within_warning_window:
        for w in warnings["thunderstorm"]:
            lv = RED
            reasons.append(f"BOM warning: {warning_title(w)}")
    cape_hit = [h for h in known if (h.get("cape") or 0) >= lt["cape_amber"] and (h.get("rain") or 0) >= lt["cape_rain_mm"]]
    if cape_hit:
        lv = worst(lv, AMBER)
        reasons.append("Unstable air with rain – storms could develop")
    text = (day_text or "").lower()
    hits = [k for k in lt["text_keywords_amber"] if k in text]
    if hits:
        lv = worst(lv, AMBER)
        reasons.append(f"BOM forecast for the day mentions {', '.join(hits)}")
    if not known and day_text is None:
        return factor(UNKNOWN, "?", "No forecast available")
    if not reasons:
        reasons.append("No thunderstorms forecast")
    reasons.append("See lightning or hear thunder? Off the water; wait 30 min after the last thunder.")
    return factor(lv, {GREEN: "None", AMBER: "Possible", RED: "No go"}[lv], *reasons)


def _vis_text(m):
    """Visibility as shown on the page: metres (to 10 m) under 2 km, otherwise km."""
    return f"{m:,.0f} m" if m < 2000 else f"{m / 1000:.1f} km"


def eval_visibility(hours, day_text, is_morning, th):
    vt = th["visibility_m"]
    vals = [h["visibility"] for h in hours if h and h.get("visibility") is not None]
    lv, reasons = GREEN, []
    v = None
    if vals:
        v = round(min(vals), -1)  # judge on the same rounded value we display
        lv = GREEN if v >= vt["amber"] else (AMBER if v >= vt["red"] else RED)
        if lv != GREEN:
            reasons.append(f"Visibility down to {_vis_text(v)} "
                           f"(yellow under {vt['amber']:,} m, red under {vt['red']:,} m)")
    if any(h and h.get("code") in FOG_CODES for h in hours):
        lv = worst(lv, AMBER)
        reasons.append("Fog forecast")
    if is_morning and any(k in (day_text or "").lower() for k in th["fog_keywords"]):
        lv = worst(lv, AMBER)
        reasons.append("BOM forecast mentions fog")
    if v is None and not reasons:
        return factor(UNKNOWN, "?", "No forecast available")
    if not reasons:
        reasons.append(f"Visibility {_vis_text(v)}" if v < 10000 else "Visibility 10 km+")
    value = (_vis_text(v) if v < 10000 else "Good") if v is not None else "Fog"
    f = factor(lv, value, *reasons)
    f["thick"] = v is not None and v < vt["dark_red"]  # thick enough for the dark + fog combination
    return f


# ---------------------------------------------------------------- darkness

def sun_elevation(when: datetime, lat, lon):
    """Approximate solar elevation in degrees (accurate to ~0.1°)."""
    n = when.astimezone(timezone.utc).timestamp() / 86400 + 2440587.5 - 2451545.0
    L = (280.460 + 0.9856474 * n) % 360
    g = math.radians((357.528 + 0.9856003 * n) % 360)
    lam = math.radians(L + 1.915 * math.sin(g) + 0.020 * math.sin(2 * g))
    eps = math.radians(23.439 - 0.0000004 * n)
    ra = math.atan2(math.cos(eps) * math.sin(lam), math.cos(lam))
    dec = math.asin(math.sin(eps) * math.sin(lam))
    gmst = (18.697374558 + 24.06570982441908 * n) % 24
    ha = math.radians(gmst * 15 + lon) - ra
    la = math.radians(lat)
    return math.degrees(math.asin(math.sin(la) * math.sin(dec) + math.cos(la) * math.cos(dec) * math.cos(ha)))


def sun_crossing(day_start: datetime, lat, lon, angle, rising):
    """Local time the sun crosses `angle` degrees (rising=morning, else evening), to the minute."""
    noon = day_start.replace(hour=13, minute=0)
    lo, hi = (day_start, noon) if rising else (noon, day_start + timedelta(hours=23, minutes=59))
    f = lambda t: sun_elevation(t, lat, lon) - angle
    if (f(lo) > 0) == (f(hi) > 0):
        return None
    for _ in range(25):
        mid = lo + (hi - lo) / 2
        if (f(mid) > 0) == (f(lo) > 0):
            lo = mid
        else:
            hi = mid
    return lo.replace(second=0, microsecond=0)


def eval_darkness(start, end, lat, lon, th, is_morning):
    """When boat lights are needed: any part of the session before sunrise or after sunset.
    Not a traffic light on its own - it only matters in combinations (dark + fog, dark + rain).
    Returns a factor flagged `active` when dark, plus a `lights` note for the page."""
    day0 = start.replace(hour=0, minute=0, second=0, microsecond=0)
    angle = th["darkness"]["dark_below_deg"]
    sunrise = sun_crossing(day0, lat, lon, angle, rising=True)
    sunset = sun_crossing(day0, lat, lon, angle, rising=False)
    if sunrise is None or sunset is None:
        f = factor(UNKNOWN, "?", "Could not work out sunrise/sunset")
        f["lights"] = None
        return f
    short, detail = [], []
    if start < sunrise:
        short.append(f"Lights to {clock(min(sunrise, end))}")
        detail.append(f"Lights needed {clock_range(start, min(sunrise, end))} (sunrise {clock(sunrise)})")
    if end > sunset:
        short.append(f"Lights from {clock(max(sunset, start))}")
        detail.append(f"Lights needed {clock_range(max(sunset, start), end)} (sunset {clock(sunset)})")
    f = factor(GREEN, "Dark" if short else "Light", *detail)
    f["active"] = bool(short)
    f["lights"] = {"needed": bool(short), "short": " · ".join(short), "detail": "; ".join(detail)} if short else \
        {"needed": False, "short": "", "detail": f"No lights needed (sunrise {clock(sunrise)}, sunset {clock(sunset)})"}
    return f


# ---------------------------------------------------------------- tide

def tide_at(extremes, when: datetime):
    """(height_m, rate_m_per_hr) by cosine interpolation between high/low predictions."""
    pts = sorted((datetime.fromisoformat(e["time"]), e["height"]) for e in extremes)
    for (t0, h0), (t1, h1) in zip(pts, pts[1:]):
        if t0 <= when <= t1:
            span = (t1 - t0).total_seconds() / 3600
            f = (when - t0).total_seconds() / 3600 / span
            height = h0 + (h1 - h0) * (1 - math.cos(math.pi * f)) / 2
            rate = (h1 - h0) * math.pi / (2 * span) * math.sin(math.pi * f)
            return height, rate
    return None, None


# ---------------------------------------------------------------- river flow

def warning_title(w):
    """BOM titles start with an issue stamp like '03/12:58 EST' - drop it."""
    return re.sub(r"^\d{2}/\d{2}:\d{2} \w+ ", "", w["title"])


def classify_warnings(warnings):
    """Split BOM warnings into those relevant to the Maribyrnong and Melbourne."""
    out = {"flood": [], "flood_watch": [], "thunderstorm": [], "severe_weather": []}
    for w in warnings or []:
        t = w["title"]
        tl = t.lower()
        if "cancellation" in tl or tl.startswith("final ") or " final " in tl:
            continue  # "Final ..." means the warning or watch has ended
        if "maribyrnong" in tl and "flood warning" in tl:
            out["flood"].append(w)
        elif "flood watch" in tl and ("central" in tl or "maribyrnong" in tl):
            out["flood_watch"].append(w)
        elif "severe thunderstorm" in tl and ("central" in tl or "melbourne" in tl):
            out["thunderstorm"].append(w)
        elif "severe weather" in tl and ("central" in tl or "melbourne" in tl):
            out["severe_weather"].append(w)
    return out


def _kmh(v):
    return f"{abs(v):.1f} km/h {'out' if v >= 0 else 'in'}"


def eval_flow(rows, gauges, warnings, th, watch_applies=True, note=""):
    """Water speed at the course during a session (flow_model rows: speed_kmh = river + tide, positive = out).
    Also red for a BOM Maribyrnong Flood Warning, yellow for a Flood Watch if `watch_applies` (sessions in
    the next 24 hours), and yellow/red for an upstream gauge rising fast (a pulse the forecast can't see)."""
    ft = th["flow"]
    band = ft["speed_kmh"]
    lv, reasons, value, direction = GREEN, [], "?", None
    if rows:
        fast = max(rows, key=lambda r: abs(r["speed_kmh"]))
        speed = round(abs(fast["speed_kmh"]), 1)  # judge on the same rounded number we display
        lv = _band(speed, band["amber"], band["red"])
        value = f"{speed:.1f} km/h"
        direction = "out" if fast["speed_kmh"] >= 0 else "in"
        reasons.append(f"Up to {_kmh(fast['speed_kmh'])} (river {fast['river_kmh']:.1f} + tide {fast['tide_kmh']:+.1f}; "
                       f"yellow from {band['amber']}, red from {band['red']})")
        reasons.append(f"Keilor flow {fast['flow_m3s']:.0f} m³/s{f'. {note}' if note else ''}")
    for g in gauges:
        rise = g.get("rise_m_per_hr")
        if rise is None or g["role"] == "course":
            continue
        rlv = _band(rise, ft["upstream_rise_m_per_hr"]["amber"], ft["upstream_rise_m_per_hr"]["red"])
        if rlv != GREEN:
            reasons.append(f"Upstream: {g['name']} rising {rise:.2f} m/hr")
        lv = worst(lv, rlv)
    for w in warnings["flood"]:
        lv = RED
        reasons.append(f"BOM warning: {warning_title(w)}")
    for w in (warnings["flood_watch"] if watch_applies else []):
        lv = worst(lv, AMBER)
        reasons.append(f"BOM: {warning_title(w)}")
    if not rows and not warnings["flood"]:
        lv = worst(lv, UNKNOWN)
        reasons.append("No water speed estimate (Keilor flow or tide missing) – check the river yourself")
    f = factor(lv, value, *reasons)
    f["direction"] = direction  # "out" (downstream), "in" (upstream) or None; drawn as an arrow
    return f


# ---------------------------------------------------------------- session

def is_active(f):
    """A factor 'counts' towards a combination if it is amber/red, or flagged active (e.g. dark)."""
    return f.get("active") or f["level"] in (AMBER, RED)


def apply_combinations(factors, combos):
    """Raise factors to red when dangerous conditions occur together.

    Each combo lists groups like ["darkness", "rain"] or ["rain", "wind|lightning"];
    '|' means any of those factors satisfies that slot. "requires": {"visibility": "thick"} means that
    factor only counts when it also carries that flag (e.g. visibility under 1,000 m).
    """
    hits = []
    for combo in combos:
        need = combo.get("requires", {})
        counts = lambda k: k in factors and is_active(factors[k]) and (k not in need or factors[k].get(need[k]))
        matched = []
        for slot in combo["factors"]:
            found = [k for k in slot.split("|") if counts(k)]
            if not found:
                break
            matched += found
        else:
            hits.append(combo["label"])
            for k in matched:
                factors[k]["level"] = combo.get("level", RED)
                factors[k]["reasons"].insert(0, f"{combo['label']}: {combo['why']}")
                factors[k]["combo"] = combo["label"]
    return hits


def evaluate_session(*, start, end, is_morning, hours, day_text, warnings, flow, lat, lon, th, now):
    within_warning_window = start - now < timedelta(hours=24)
    factors = {
        "wind": eval_wind(hours, th, warnings, within_warning_window),
        "temp": eval_temp(hours, th),
        "rain": eval_rain(hours, th),
        "lightning": eval_lightning(hours, day_text, warnings, th, within_warning_window),
        "visibility": eval_visibility(hours, day_text, is_morning, th),
        "flow": copy.deepcopy(flow),
    }
    # Darkness isn't a light of its own, but takes part in combinations (dark + fog, dark + rain).
    dark = eval_darkness(start, end, lat, lon, th, is_morning)
    combos = apply_combinations({**factors, "darkness": dark}, th["combinations"])
    overall = worst(*(f["level"] for f in factors.values()))
    return {"overall": overall, "factors": factors, "combinations": combos,
            "drivers": drivers(factors, overall), "lights": dark["lights"]}


def drivers(factors, overall):
    """Short labels for what set the overall light, e.g. ["Dark + fog"] or ["Wind", "Flow"]."""
    if overall == GREEN:
        return []
    labels = dict(FACTORS)
    out = []
    for k, f in factors.items():
        if f["level"] != overall:
            continue
        name = f.get("combo") or labels[k]
        if name not in out:
            out.append(name)
    return out
