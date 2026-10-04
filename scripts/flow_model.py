"""Water speed at the course (Poyntons) from a volume balance.

The water passing Poyntons is the river's own flow plus the tide filling or emptying the tidal reach
upstream (from Poyntons up to the tidal limit near Solomon's Ford):

    Q = Q_river(t - lag) - upstream_area * (rate the water level is rising)
    speed = Q / (width * depth)          positive = downstream (going out)

Q_river is Keilor's flow (measured, then our rain-driven forecast). The tide comes from the BOM
Williamstown prediction, which runs in step with the course. Depth follows the water level.

River flow also lifts the water at Poyntons a little above the tide ("setup", fitted from history by
fit_flow_model.py). It only matters for the height chart and the depth.

Every function here is pure (no network), so it can be unit tested.
"""
import math

KMH = 3.6  # m/s -> km/h
MIN_DEPTH_M = 0.5


def speed_kmh(q_river, tide_rate_m_per_hr, height_above_mean_m, geom):
    """(total, river part, tide part) in km/h; positive = downstream."""
    area = geom["width_m"] * max(geom["depth_m"] + height_above_mean_m, MIN_DEPTH_M)
    tide_q = -geom["upstream_tidal_area_m2"] * tide_rate_m_per_hr / 3600
    river, tide = q_river / area * KMH, tide_q / area * KMH
    return river + tide, river, tide


def setup_m(q, fit):
    """How far river flow (m³/s) lifts the water at Poyntons above the tide."""
    return fit["k"] * max(q, 0.0) ** fit["p"]


def fit_setup(points):
    """Fit setup = k * Q^p by least squares in log space. points: [(flow, setup)] with both > 0."""
    xs = [math.log(q) for q, s in points]
    ys = [math.log(s) for q, s in points]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    p = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
    return {"k": round(math.exp(my - p * mx), 6), "p": round(p, 3)}


def interp(points, t):
    """Linear interpolation in a sorted [(t, v)] list; None outside it."""
    for (t0, v0), (t1, v1) in zip(points, points[1:]):
        if t0 <= t <= t1:
            f = (t - t0) / (t1 - t0) if t1 != t0 else 0.0
            return v0 + (v1 - v0) * f
    if points and t == points[-1][0]:
        return points[-1][1]
    return None


def row(t, q, level_m, rate_m_per_hr, mouth_m, model, geom):
    """One point of the series: speed split into river and tide, plus the water heights."""
    total, river, tide = speed_kmh(q, rate_m_per_hr, level_m - model["mean_level_m"], geom)
    return {"time": t.isoformat(timespec="minutes"), "speed_kmh": round(total, 2),
            "river_kmh": round(river, 2), "tide_kmh": round(tide, 2), "flow_m3s": round(q, 1),
            "poyntons_m": round(level_m, 3), "mouth_m": None if mouth_m is None else round(mouth_m, 3)}


def forecast_rows(times, q_at, tide_at, offset, model, geom):
    """Forecast from flow and the tide prediction. q_at(t) -> Keilor flow reaching the course at t;
    tide_at(t) -> (height, rate) from the prediction. offset puts the prediction on the gauge's datum."""
    out = []
    for t in times:
        q = q_at(t)
        h, rate = tide_at(t)
        if q is None or h is None:
            continue
        mouth = h + offset
        out.append(row(t, q, mouth + setup_m(q, model["setup"]), rate, mouth, model, geom))
    return out


def measured_rows(levels, q_at, model, geom):
    """Estimate from what was measured: Keilor flow and the course gauge. levels: sorted [(t, m)].
    The rate of rise is taken over about an hour, centred, to smooth the gauge's 6-minute steps."""
    out = []
    for i, (t, h) in enumerate(levels):
        q = q_at(t)
        a = next((j for j in range(i, -1, -1) if (t - levels[j][0]).total_seconds() >= 1800), 0)
        b = next((j for j in range(i, len(levels)) if (levels[j][0] - t).total_seconds() >= 1800), len(levels) - 1)
        hours = (levels[b][0] - levels[a][0]).total_seconds() / 3600
        if q is None or hours <= 0:
            continue
        out.append(row(t, q, h, (levels[b][1] - levels[a][1]) / hours, None, model, geom))
    return out
