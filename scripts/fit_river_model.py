"""Fit the Keilor forecast to history and report how well it does.

Run:  python3 scripts/fetch_history.py      (downloads history/ - not committed)
      python3 scripts/fit_river_model.py    (fits, backtests, writes config/river_model.json)

Takes several minutes (pure Python).
"""
import glob
import json
import math
from datetime import date, datetime, timedelta
from pathlib import Path

import river_model as rm

ROOT = Path(__file__).resolve().parent.parent
RAIN_GAUGES = ["230105A", "230100A", "230104A", "587014"]
START = datetime(2018, 10, 1)
TRAIN_END = datetime(2025, 1, 1)
RIDGE = 1.0


def load(site, kind):
    d = {}
    for f in sorted(glob.glob(str(ROOT / "history" / f"{site}_{kind}_*.json"))):
        d.update(json.loads(Path(f).read_text()))
    return d


def build_series():
    flow_raw, level_raw = load("230105A", "river-flow"), load("230105A", "river-level")
    rains = {g: load(g, "rain") for g in RAIN_GAUGES}
    times, t = [], START
    end = datetime.strptime(max(flow_raw), "%Y-%m-%d %H")
    while t <= end:
        times.append(t)
        t += timedelta(hours=1)
    key = lambda t: t.strftime("%Y-%m-%d %H")
    rain = rm.catchment_rain([rm.clean_rain([rains[g].get(key(t)) for t in times]) for g in RAIN_GAUGES])
    flow = rm.drop_rainless_floods(rm.despike([flow_raw.get(key(t)) for t in times]), rain)
    level = [level_raw.get(key(t)) if flow[i] is not None else None for i, t in enumerate(times)]
    return times, flow, level, rain


class Rain:
    """Fast window sums over the full history (same windows as river_model.window_sums)."""

    def __init__(self, rain):
        self.cum = [0.0]
        for r in rain:
            self.cum.append(self.cum[-1] + r)

    def s(self, a, b):  # rain in hours [a, b)
        n = len(self.cum) - 1
        a, b = max(0, min(a, n)), max(0, min(b, n))
        return self.cum[b] - self.cum[a]

    def sums(self, i, lead):
        e = i + 1  # past ends at hour i inclusive
        past = [self.s(e - b, e - a) for a, b in rm.PAST_WINDOWS]
        fut = [self.s(e + a, e + min(b, lead)) if a < lead else 0.0 for a, b in rm.FUTURE_WINDOWS]
        return past, self.s(e - 168, e), self.s(e - rm.HISTORY_HOURS, e), fut


def x_at(R, flow, i, lead, future_rain=True):
    past, wet7, wet30, fut = R.sums(i, lead)
    if not future_rain:
        fut = [0.0] * len(fut)
    return rm.features(flow[i], flow[i - 3], past, wet7, wet30, fut)


def solve(A, b):
    n = len(b)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for c in range(n):
        piv = max(range(c, n), key=lambda r: abs(M[r][c]))
        M[c], M[piv] = M[piv], M[c]
        for r in range(n):
            if r != c and M[c][c]:
                fac = M[r][c] / M[c][c]
                for k in range(c, n + 1):
                    M[r][k] -= fac * M[c][k]
    return [M[i][n] / M[i][i] if M[i][i] else 0.0 for i in range(n)]


def fit_lead(R, flow, lead, start, end, step=2):
    """Weighted ridge regression of the change in log-flow over `lead` hours."""
    A = b = None
    for i in range(start, end - lead, step):
        if flow[i] is None or flow[i + lead] is None or flow[i - 3] is None:
            continue
        x = x_at(R, flow, i, lead)
        y = math.log(flow[i + lead] + 0.3) - math.log(flow[i] + 0.3)
        # Most hours the river does nothing - give rises and wet spells more say.
        w = 5.0 if (flow[i + lead] > 2 or flow[i] > 2 or R.s(i - 23, i + 1 + lead) > 5) else 1.0
        if A is None:
            A, b = [[0.0] * len(x) for _ in x], [0.0] * len(x)
        for r, xr in enumerate(x):
            wx = w * xr
            b[r] += wx * y
            row = A[r]
            for c, xc in enumerate(x):
                row[c] += wx * xc
    for r in range(len(A)):
        A[r][r] += RIDGE
    return [round(v, 6) for v in solve(A, b)]


def backtest(times, flow, level, R, model, start, end, every=6):
    """Forecast every few hours over a period not used for fitting. 'rain' uses the rain that actually
    fell (a perfect rain forecast); 'no_rain' assumes none."""
    rating = model["rating"]
    out = {}
    for name, fr in (("rain", True), ("no_rain", False)):
        allerr, higherr = {}, {}
        for lead in rm.LEADS:
            e_all, e_hi = [], []
            for i in range(start, end - lead, every):
                if flow[i] is None or flow[i - 3] is None or level[i + lead] is None:
                    continue
                q = rm.predict_flow(model["coefs"][str(lead)], flow[i], x_at(R, flow, i, lead, fr))
                err = rm.flow_to_level(q, rating) - level[i + lead]
                e_all.append(abs(err))
                if level[i + lead] >= 0.8 or (level[i] or 0) >= 0.8:
                    e_hi.append(abs(err))
            allerr[f"+{lead}h"] = round(sum(e_all) / len(e_all), 3) if e_all else None
            higherr[f"+{lead}h"] = round(sum(e_hi) / len(e_hi), 3) if e_hi else None
        out[name] = {"typical_error_m": allerr, "typical_error_high_river_m": higherr}
    return out


def event_check(times, flow, level, R, model, peak, before):
    i = times.index(peak) - before
    rating = model["rating"]
    preds = {lead: round(rm.flow_to_level(rm.predict_flow(model["coefs"][str(lead)], flow[i], x_at(R, flow, i, lead)), rating), 2)
             for lead in rm.LEADS if lead <= before + 12}
    return {"peak": f"{peak:%Y-%m-%d %H:00}", "actual_peak_m": level[times.index(peak)],
            "forecast_from": f"{times[i]:%Y-%m-%d %H:00}", "level_then_m": level[i],
            f"forecast_for_peak_time_m": preds.get(before), "highest_forecast_m": max(preds.values())}


def main():
    times, flow, level, rain = build_series()
    R = Rain(rain)
    print(f"{len(times)} hours, {times[0]:%Y-%m-%d} to {times[-1]:%Y-%m-%d}")
    pairs = [(q, l) for q, l in zip(flow, level) if q is not None and l is not None]
    rating, rating_err = rm.fit_rating(pairs)
    print("rating curve", rating, f"typical error {rating_err:.3f} m")

    te = times.index(TRAIN_END)
    model = {"rating": rating, "coefs": {}}
    for lead in rm.LEADS:
        model["coefs"][str(lead)] = fit_lead(R, flow, lead, rm.HISTORY_HOURS, te)
        print(f"fitted +{lead}h", flush=True)

    valid = backtest(times, flow, level, R, model, te, len(times))
    print(json.dumps(valid, indent=1))
    checks = []
    for peak in [datetime(2022, 10, 14, 8), datetime(2024, 1, 9, 3), datetime(2026, 7, 4, 7)]:
        for before in (24, 12):
            if peak in times:
                checks.append(event_check(times, flow, level, R, model, peak, before))
    recent = max(range(len(times) - 24 * 10, len(times) - 24), key=lambda k: level[k] or 0)
    checks.append(event_check(times, flow, level, R, model, times[recent], 24))
    for c in checks:
        print(c)

    out = {
        "_comment": "Fitted by scripts/fit_river_model.py from Keilor flow + catchment rain only. "
                    "Errors are typical Keilor level errors (m) on 2025-26 data not used for fitting, "
                    "assuming the rain forecast was right.",
        "fitted": date.today().isoformat(),
        "training_period": f"{times[0]:%Y-%m-%d} to {TRAIN_END:%Y-%m-%d}",
        "rain_gauges": RAIN_GAUGES,
        "leads_hours": rm.LEADS,
        "rating": rating,
        "coefs": model["coefs"],
        "validation_2025_2026": valid,
        "event_checks": checks,
    }
    (ROOT / "config" / "river_model.json").write_text(json.dumps(out, indent=1))
    print("wrote config/river_model.json")


if __name__ == "__main__":
    main()
