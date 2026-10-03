"""Keilor river forecast from two things only: Keilor's current flow and catchment rainfall.

How it works:
  For each look-ahead (3, 6, 12 ... 72 hours) we learned from 2018–2024 history how much Keilor's
  flow changes, given:
    - the flow now and how it changed over the last 3 hours,
    - rain in recent windows (last 6 h, 6–12 h ago, 12–24 h, 24–48 h, 48–96 h),
    - how wet the catchment is (rain over the last 7 and 30 days),
    - rain still to come (forecast) in windows up to the look-ahead.
  Rain counts for more when the catchment is already wet. Flow is then converted to the Keilor
  gauge height with a rating curve fitted from the same history.

Fitting lives in fit_river_model.py; this file holds the pure functions used by both.
"""
import math

PAST_WINDOWS = [(0, 6), (6, 12), (12, 24), (24, 48), (48, 96)]   # hours before now
FUTURE_WINDOWS = [(0, 6), (6, 12), (12, 24), (24, 48), (48, 72)]  # hours after now
LEADS = [3, 6, 12, 18, 24, 36, 48, 72]
HISTORY_HOURS = 720  # past rain needed (30 days)


# ---------------------------------------------------------------- cleaning

def clean_rain(values, cap=50.0):
    """Hourly rain per gauge; implausible values (> cap mm/hr) become missing."""
    return [None if v is None or v < 0 or v > cap else v for v in values]


def catchment_rain(gauge_series):
    """Average across gauges per hour, ignoring missing gauges (0 where all missing)."""
    out = []
    for vals in zip(*gauge_series):
        got = [v for v in vals if v is not None]
        out.append(sum(got) / len(got) if got else 0.0)
    return out


def despike(values, window=18, factor=4.0):
    """Remove short spikes (sensor glitches) that jump far above both sides and come straight back."""
    out = list(values)
    for i, v in enumerate(values):
        if v is None:
            continue
        before = [x for x in values[max(0, i - window):i] if x is not None]
        after = [x for x in values[i + 1:i + 1 + window] if x is not None]
        if not before or not after:
            continue
        # A real flood stays high afterwards (slow recession); a glitch drops straight back.
        ref = max(min(before), min(after))
        if v > factor * ref + 5:
            out[i] = None
    return out


def drop_rainless_floods(flow, rain, min_flow=15.0, min_rain_mm=5.0, hours=168):
    """A flood-sized flow with almost no catchment rain in the week before is a sensor fault."""
    cum = [0.0]
    for r in rain:
        cum.append(cum[-1] + r)
    return [None if q is not None and q > min_flow and cum[i + 1] - cum[max(0, i - hours + 1)] < min_rain_mm else q
            for i, q in enumerate(flow)]


# ---------------------------------------------------------------- features & prediction

def _lq(q):
    return math.log(max(q, 0.0) + 0.3)


def features(q_now, q_3h_ago, past_sums, wet7, wet30, future_sums):
    """past_sums / future_sums: rain (mm) in PAST_WINDOWS / FUTURE_WINDOWS (future cut at the lead)."""
    q = _lq(q_now)
    dq = q - _lq(q_3h_ago) if q_3h_ago is not None else 0.0
    wet = math.log1p(wet30)
    x = [1.0, q, dq, wet, math.log1p(wet7)]
    for v in list(past_sums) + list(future_sums):
        lv = math.log1p(v)
        x += [lv, lv * wet, lv * q]
    return x


def window_sums(past_rain, future_rain, lead):
    """Rain totals for the feature windows. past_rain ends at the current hour; future_rain starts next hour."""
    n = len(past_rain)
    past = [sum(past_rain[max(0, n - b):max(0, n - a)]) for a, b in PAST_WINDOWS]
    fut = [sum(future_rain[a:min(b, lead)]) if a < lead else 0.0 for a, b in FUTURE_WINDOWS]
    return past, sum(past_rain[-168:]), sum(past_rain[-HISTORY_HOURS:]), fut


def predict_flow(coefs, q_now, x):
    return max(math.exp(_lq(q_now) + sum(a * b for a, b in zip(coefs, x))) - 0.3, 0.0)


def forecast(model, q_now, q_3h_ago, past_rain, future_rain, hours):
    """Hourly flow forecast for hours 1..`hours` (interpolating between fitted look-aheads)."""
    at_lead = {0: q_now}
    for lead in LEADS:
        past, wet7, wet30, fut = window_sums(past_rain, future_rain, lead)
        x = features(q_now, q_3h_ago, past, wet7, wet30, fut)
        at_lead[lead] = predict_flow(model["coefs"][str(lead)], q_now, x)
    leads = sorted(at_lead)
    out = []
    for h in range(1, hours + 1):
        hi = next((l for l in leads if l >= h), leads[-1])
        lo = max(l for l in leads if l <= min(h, hi))
        if hi == lo:
            out.append(at_lead[hi])
            continue
        f = (h - lo) / (hi - lo)  # interpolate in log space
        out.append(math.exp(_lq(at_lead[lo]) * (1 - f) + _lq(at_lead[hi]) * f) - 0.3)
    return [max(q, 0.0) for q in out]


# ---------------------------------------------------------------- rating curve

def flow_to_level(q, rating):
    return rating["a"] + rating["b"] * max(q, 0.0) ** rating["c"]


def fit_rating(pairs):
    """Fit level = a + b * flow^c by least squares (grid over c)."""
    best = None
    for c100 in range(15, 91):
        c = c100 / 100
        xs = [q ** c for q, _ in pairs]
        ys = [l for _, l in pairs]
        n = len(xs)
        mx, my = sum(xs) / n, sum(ys) / n
        sxx = sum((x - mx) ** 2 for x in xs)
        b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
        a = my - b * mx
        err = sum((a + b * x - y) ** 2 for x, y in zip(xs, ys)) / n
        if best is None or err < best[0]:
            best = (err, {"a": round(a, 4), "b": round(b, 4), "c": c})
    return best[1], math.sqrt(best[0])
