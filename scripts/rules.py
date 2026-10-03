"""Risk rules: turn raw data into a traffic light per factor per session.

Every function here is pure (no network), so it can be unit tested.
Levels: "green", "amber", "red", or "unknown" (data missing - check manually).
"""
import copy
import math
from datetime import date, datetime, timedelta, timezone

GREEN, AMBER, RED, UNKNOWN = "green", "amber", "red", "unknown"
_RANK = {GREEN: 0, UNKNOWN: 1, AMBER: 2, RED: 3}

# Row order on the dashboard.
FACTORS = [
    ("wind", "Wind"),
    ("temp", "Temperature"),
    ("rain", "Rain"),
    ("storm", "Storms"),
    ("visibility", "Fog / visibility"),
    ("darkness", "Darkness"),
    ("tide", "Tide"),
    ("flood", "River / flood"),
]

THUNDER_CODES = {95, 96, 99}
FOG_CODES = {45, 48}


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

def eval_wind(hours, th):
    vals = [h["wind"] for h in hours if h and h.get("wind") is not None]
    if not vals:
        return factor(UNKNOWN, "?", "No wind forecast available")
    w = max(vals)
    lv = _band(w, th["wind_kn"]["amber"], th["wind_kn"]["red"])
    gusts = [h["gust"] for h in hours if h and h.get("gust") is not None]
    gust_txt = f"gusts to {max(gusts):.0f} kn" if gusts else ""
    return factor(lv, f"{w:.0f} kn", f"Forecast wind up to {w:.0f} kn (amber ≥{th['wind_kn']['amber']}, red ≥{th['wind_kn']['red']})",
                  gust_txt.capitalize())


def eval_temp(hours, th):
    vals = [h["temp"] for h in hours if h and h.get("temp") is not None]
    if not vals:
        return factor(UNKNOWN, "?", "No temperature forecast available")
    hi, lo = max(vals), min(vals)
    lv = _band(hi, th["heat_c"]["amber"], th["heat_c"]["red"])
    reasons = []
    if lv != GREEN:
        reasons.append(f"Hot: up to {hi:.0f}°C (amber ≥{th['heat_c']['amber']}, red ≥{th['heat_c']['red']})")
    if lo < th["cold_c"]["amber"]:
        lv = worst(lv, AMBER)
        reasons.append(f"Cold: down to {lo:.0f}°C (amber below {th['cold_c']['amber']}) - dress for immersion")
    if not reasons:
        reasons.append(f"{lo:.0f}–{hi:.0f}°C")
    value = f"{hi:.0f}°C" if hi >= th["heat_c"]["amber"] else f"{lo:.0f}°C"
    return factor(lv, value, *reasons)


def eval_rain(hours, th):
    vals = [h["rain"] for h in hours if h and h.get("rain") is not None]
    if not vals:
        return factor(UNKNOWN, "?", "No rain forecast available")
    r = max(vals)
    lv = _band(r, th["rain_mm_per_hr"]["amber"], th["rain_mm_per_hr"].get("red"))
    if lv == GREEN:
        f = factor(GREEN, "Dry" if r < 0.1 else f"{r:.1f} mm", "No significant rain forecast" if r < 0.1 else f"Light rain, up to {r:.1f} mm/hr")
    else:
        f = factor(lv, f"{r:.1f} mm", f"Rain up to {r:.1f} mm/hr (amber ≥{th['rain_mm_per_hr']['amber']})")
    if r >= th["rain_mm_per_hr"]["combo_min"]:
        f["active"] = True  # enough rain to matter in combinations (dark + rain, rain + wind)
    return f


def eval_storm(hours, day_text, warnings, th, within_warning_window):
    lv, reasons = GREEN, []
    known = [h for h in hours if h]
    if any(h.get("code") in THUNDER_CODES for h in known):
        lv = AMBER
        reasons.append("Thunderstorm in hourly forecast")
    cape_hit = [h for h in known if (h.get("cape") or 0) >= th["storm"]["cape_amber"]
                and (h.get("rain") or 0) >= th["storm"]["cape_rain_mm"]]
    if cape_hit:
        lv = AMBER
        reasons.append(f"Unstable air with rain (CAPE {max(h['cape'] for h in cape_hit):.0f})")
    text = (day_text or "").lower()
    hits = [k for k in th["storm"]["text_keywords_amber"] if k in text]
    if hits:
        lv = AMBER
        reasons.append(f"BOM forecast mentions: {', '.join(hits)}")
    if within_warning_window:
        for w in warnings["storm"]:
            lv = RED
            reasons.append(f"Active BOM warning: {w['title']}")
    if not known and day_text is None:
        return factor(UNKNOWN, "?", "No storm forecast available")
    if not reasons:
        reasons.append("No storms forecast")
    return factor(lv, {GREEN: "None", AMBER: "Possible", RED: "Warning"}[lv], *reasons)


def eval_visibility(hours, day_text, is_morning, th):
    vals = [h["visibility"] for h in hours if h and h.get("visibility") is not None]
    lv, reasons = GREEN, []
    if vals:
        v = min(vals)
        lv = GREEN if v >= th["visibility_m"]["amber"] else (AMBER if v >= th["visibility_m"]["red"] else RED)
        if lv != GREEN:
            reasons.append(f"Forecast visibility down to {v/1000:.1f} km")
    if any(h and h.get("code") in FOG_CODES for h in hours):
        lv = worst(lv, AMBER)
        reasons.append("Fog in hourly forecast")
    if is_morning and any(k in (day_text or "").lower() for k in th["fog_keywords"]):
        lv = worst(lv, AMBER)
        reasons.append("BOM forecast mentions fog")
    if not vals and not reasons:
        return factor(UNKNOWN, "?", "No visibility forecast available")
    if not reasons:
        reasons.append(f"Visibility {min(vals)/1000:.0f} km+")
    value = f"{min(vals)/1000:.1f} km" if vals and min(vals) < 10000 else ("Fog" if lv != GREEN else "Good")
    return factor(lv, value, *reasons)


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
    """Dark = any part of the session before first light or after last light (civil twilight)."""
    day0 = start.replace(hour=0, minute=0, second=0, microsecond=0)
    angle = th["darkness"]["dark_below_deg"]
    first_light = sun_crossing(day0, lat, lon, angle, rising=True)
    last_light = sun_crossing(day0, lat, lon, angle, rising=False)
    if first_light is None or last_light is None:
        return factor(UNKNOWN, "?", "Could not calculate first/last light")
    reasons = []
    if start < first_light:
        reasons.append(f"Starts before first light ({first_light:%H:%M}) – lights needed "
                       f"{start:%H:%M}–{min(first_light, end):%H:%M}")
    if end > last_light:
        reasons.append(f"Runs past last light ({last_light:%H:%M}) – lights needed "
                       f"{max(last_light, start):%H:%M}–{end:%H:%M}")
    if reasons:
        f = factor(th["darkness"]["alone_level"], "Lights on", *reasons)
        f["active"] = True
        return f
    return factor(GREEN, "Light", f"First light {first_light:%H:%M}" if is_morning else f"Last light {last_light:%H:%M}")


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


def eval_tide(start, end, extremes, lag_minutes, th):
    if not extremes:
        return factor(UNKNOWN, "?", "No tide predictions available")
    lag = timedelta(minutes=lag_minutes)
    rates = []
    t = start
    while t <= end:
        _, r = tide_at(extremes, t - lag)
        if r is not None:
            rates.append(r)
        t += timedelta(minutes=15)
    if not rates:
        return factor(UNKNOWN, "?", "Session outside tide prediction range")
    max_ebb = -min(rates)
    course_note = f"Williamstown + {lag_minutes} min"
    direction = "Outgoing" if sum(rates) < 0 else "Incoming"
    if max_ebb < th["tide_ebb_m_per_hr"]["amber"]:
        detail = f"falling at most {max_ebb:.2f} m/hr" if max_ebb > 0 else "rising"
        return factor(GREEN, direction, f"{direction} tide ({detail}) at {course_note}")
    return factor(AMBER, "Outgoing", f"Outgoing tide falling up to {max_ebb:.2f} m/hr (amber ≥{th['tide_ebb_m_per_hr']['amber']})",
                  "Red if river flow is also high")


# ---------------------------------------------------------------- river / flood

def classify_warnings(warnings):
    """Split BOM warnings into those relevant to the Maribyrnong and Melbourne."""
    out = {"flood": [], "flood_watch": [], "storm": []}
    for w in warnings or []:
        t = w["title"]
        tl = t.lower()
        if "cancellation" in tl:
            continue
        if "maribyrnong" in tl and "flood warning" in tl and "final" not in tl:
            out["flood"].append(w)
        elif "flood watch" in tl and ("central" in tl or "maribyrnong" in tl):
            out["flood_watch"].append(w)
        elif ("severe thunderstorm" in tl or "severe weather" in tl) and ("central" in tl or "melbourne" in tl):
            out["storm"].append(w)
    return out


def keilor_normal(th, on: date):
    """Typical Keilor level for this time of year, blending between mid-month values."""
    by_month = th["flood"]["keilor_normal_by_month_m"]

    def mid(year, month):  # 15th of a month, allowing month 0 / 13 to step across the year end
        year, month = year + (month - 1) // 12, (month - 1) % 12 + 1
        return date(year, month, 15), by_month[str(month)]

    here, v_here = mid(on.year, on.month)
    there, v_there = mid(on.year, on.month + (1 if on >= here else -1))
    f = abs((on - here).days) / abs((there - here).days)
    return round(v_here * (1 - f) + v_there * f, 2)


def eval_flood(gauges, warnings, th, forecast_level=None, forecast_note="", on=None):
    """River state on date `on` (default today). Uses the live Keilor reading, or `forecast_level`
    (predicted Keilor height during a later session) when given."""
    ft = th["flood"]
    lv, reasons = GREEN, []
    keilor = next((g for g in gauges if g["role"] == "keilor"), None)
    above = None
    if keilor:
        normal = keilor_normal(th, on or date.today())
        band = ft["keilor_above_normal_m"]
        height = keilor["level_m"] if forecast_level is None else forecast_level
        above = round(height - normal, 2)  # judge on the same rounded value we display
        lv = _band(above, band["amber"], band["red"])
        what = "Keilor gauge" if forecast_level is None else "Forecast Keilor"
        reasons.append(f"{what} {height:.2f} m = {above:.2f} m above normal ({normal:.2f} m). "
                       f"Green under {normal + band['amber']:.2f} m, yellow under {normal + band['red']:.2f} m, "
                       f"red from {normal + band['red']:.2f} m (normal for {on or date.today():%d %b})")
        if forecast_level is not None:
            reasons.append(f"{forecast_note} (now {keilor['level_m']:.2f} m) - experimental forecast")
    for g in gauges:
        rise = g.get("rise_m_per_hr")
        if rise is None or g["role"] == "course":
            continue
        rlv = _band(rise, ft["upstream_rise_m_per_hr"]["amber"], ft["upstream_rise_m_per_hr"]["red"])
        if rlv != GREEN:
            reasons.append(f"{g['name']} rising {rise:.2f} m/hr")
        lv = worst(lv, rlv)
    for w in warnings["flood"]:
        lv = RED
        reasons.append(f"Active BOM warning: {w['title']}")
    for w in warnings["flood_watch"]:
        lv = worst(lv, AMBER)
        reasons.append(f"BOM: {w['title']}")
    if not keilor and not warnings["flood"]:
        lv = worst(lv, UNKNOWN)
        reasons.append("Keilor gauge unavailable - check river manually")
    value = (f"Keilor {keilor['level_m']:.2f} m" if forecast_level is None else f"{forecast_level:.2f} m") if keilor else "?"
    return factor(lv, value, *reasons)


# ---------------------------------------------------------------- session

def is_active(f):
    """A factor 'counts' towards a combination if it is amber/red, or flagged active (e.g. dark)."""
    return f.get("active") or f["level"] in (AMBER, RED)


def apply_combinations(factors, combos):
    """Raise factors to red when dangerous conditions occur together.

    Each combo lists groups like ["darkness", "rain"] or ["fog", "visibility|rain"];
    '|' means any of those factors satisfies that slot.
    """
    hits = []
    for combo in combos:
        matched = []
        for slot in combo["factors"]:
            found = [k for k in slot.split("|") if k in factors and is_active(factors[k])]
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


def evaluate_session(*, start, end, is_morning, hours, day_text, tides, warnings,
                     flood, lat, lon, th, tide_lag, now):
    within_warning_window = start - now < timedelta(hours=24)
    factors = {
        "wind": eval_wind(hours, th),
        "temp": eval_temp(hours, th),
        "rain": eval_rain(hours, th),
        "storm": eval_storm(hours, day_text, warnings, th, within_warning_window),
        "visibility": eval_visibility(hours, day_text, is_morning, th),
        "darkness": eval_darkness(start, end, lat, lon, th, is_morning),
        "tide": eval_tide(start, end, tides, tide_lag, th),
        "flood": copy.deepcopy(flood),
    }
    combos = apply_combinations(factors, th["combinations"])
    overall = worst(*(f["level"] for f in factors.values()))
    return {"overall": overall, "factors": factors, "combinations": combos,
            "drivers": drivers(factors, overall)}


def drivers(factors, overall):
    """Short labels for what set the overall light, e.g. ["Dark + fog"] or ["Darkness", "River / flood"]."""
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
