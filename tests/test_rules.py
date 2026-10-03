"""Run:  python3 -m unittest discover tests"""
import json
import sys
import unittest
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import rules  # noqa: E402

TH = json.loads((Path(__file__).resolve().parent.parent / "config" / "thresholds.json").read_text())
TZ = ZoneInfo("Australia/Melbourne")
LAT, LON = -37.775, 144.892
NO_WARNINGS = {"flood": [], "flood_watch": [], "storm": []}
CALM_RIVER = [{"role": "keilor", "name": "Keilor", "level_m": 0.4, "flow_m3s": 4, "rise_m_per_hr": 0.0}]
HIGH_RIVER = [{"role": "keilor", "name": "Keilor", "level_m": 0.9, "flow_m3s": 30, "rise_m_per_hr": 0.0}]  # +0.35 m = yellow


def hour(**kw):
    base = {"wind": 5, "gust": 8, "temp": 15, "rain": 0, "cape": 0, "visibility": 20000, "code": 1}
    return base | kw


# Falling all morning (ebb ~0.19 m/hr) / rising all morning.
EBB_TIDES = [
    {"time": "2026-10-10T00:00:00+11:00", "type": "High", "height": 1.5},
    {"time": "2026-10-10T12:30:00+11:00", "type": "Low", "height": 0.0},
    {"time": "2026-10-10T23:59:00+11:00", "type": "High", "height": 1.5},
]
RISING_TIDES = [
    {"time": "2026-10-10T00:00:00+11:00", "type": "Low", "height": 0.0},
    {"time": "2026-10-10T12:30:00+11:00", "type": "High", "height": 1.5},
    {"time": "2026-10-10T23:59:00+11:00", "type": "Low", "height": 0.0},
]


def session(hours, *, morning=True, tides=RISING_TIDES, gauges=CALM_RIVER, warnings=NO_WARNINGS, day_text=""):
    start = datetime(2026, 10, 10, 5, 30, tzinfo=TZ) if morning else datetime(2026, 10, 10, 18, 0, tzinfo=TZ)
    end = datetime(2026, 10, 10, 7, 0, tzinfo=TZ) if morning else datetime(2026, 10, 10, 20, 0, tzinfo=TZ)
    # Daytime variant (no darkness) for isolating other rules.
    if morning == "day":
        start, end = datetime(2026, 10, 10, 10, 0, tzinfo=TZ), datetime(2026, 10, 10, 11, 30, tzinfo=TZ)
    flood = rules.eval_flood(gauges, warnings, TH, on=start.date())
    return rules.evaluate_session(start=start, end=end, is_morning=bool(morning), hours=hours, day_text=day_text,
                                  tides=tides, warnings=warnings, flood=flood, lat=LAT, lon=LON, th=TH,
                                  tide_lag=0, now=start)


class Single(unittest.TestCase):
    def test_calm_daytime_is_green(self):
        r = session([hour()] * 3, morning="day", tides=RISING_TIDES)
        self.assertEqual(r["overall"], "green", r)

    def test_wind_bands(self):
        self.assertEqual(rules.eval_wind([hour(wind=9)], TH)["level"], "green")
        self.assertEqual(rules.eval_wind([hour(wind=12)], TH)["level"], "amber")
        self.assertEqual(rules.eval_wind([hour(wind=16)], TH)["level"], "red")

    def test_heat_and_cold(self):
        self.assertEqual(rules.eval_temp([hour(temp=36)], TH)["level"], "red")
        self.assertEqual(rules.eval_temp([hour(temp=31)], TH)["level"], "amber")
        self.assertEqual(rules.eval_temp([hour(temp=3)], TH)["level"], "amber")

    def test_dark_alone_is_amber(self):
        r = session([hour()] * 3, morning=True)
        self.assertTrue(r["factors"]["darkness"].get("active"))
        self.assertEqual(r["factors"]["darkness"]["level"], "amber")
        self.assertEqual(r["overall"], "amber", r)

    def test_outgoing_tide_alone_is_amber(self):
        r = session([hour()] * 3, morning="day", tides=EBB_TIDES)
        self.assertEqual(r["factors"]["tide"]["level"], "amber")
        self.assertEqual(r["overall"], "amber")

    def test_keilor_height_above_normal_bands(self):
        on = date(2026, 10, 15)
        def lv(level):
            return rules.eval_flood([{"role": "keilor", "name": "Keilor", "level_m": level}], NO_WARNINGS, TH, on=on)["level"]
        normal = rules.keilor_normal(TH, on)
        self.assertEqual(lv(normal + 0.05), "green")
        self.assertEqual(lv(normal + 0.3), "amber")
        self.assertEqual(lv(normal + 0.55), "amber")
        self.assertEqual(lv(normal + 0.65), "red")

    def test_seasonal_normal(self):
        self.assertEqual(rules.keilor_normal(TH, date(2026, 1, 15)), 0.28)
        self.assertEqual(rules.keilor_normal(TH, date(2026, 8, 15)), 0.46)
        mid = rules.keilor_normal(TH, date(2026, 8, 31))      # between Aug (0.46) and Sep (0.43)
        self.assertTrue(0.43 <= mid <= 0.46)
        self.assertTrue(0.28 <= rules.keilor_normal(TH, date(2026, 12, 31)) <= 0.33)  # Dec -> Jan
        self.assertTrue(0.28 <= rules.keilor_normal(TH, date(2026, 1, 2)) <= 0.33)

    def test_maribyrnong_flood_warning_is_red(self):
        w = rules.classify_warnings([{"title": "03/10:00 EST Minor Flood Warning for the Maribyrnong River", "link": ""}])
        self.assertEqual(rules.eval_flood(CALM_RIVER, w, TH)["level"], "red")

    def test_cancelled_and_other_river_warnings_ignored(self):
        w = rules.classify_warnings([
            {"title": "Cancellation of Flood Warning for the Maribyrnong River", "link": ""},
            {"title": "Moderate Flood Warning for the Werribee River", "link": ""},
        ])
        self.assertEqual(rules.eval_flood(CALM_RIVER, w, TH)["level"], "green")

    def test_missing_forecast_is_unknown_not_green(self):
        r = session([None] * 3, morning="day")
        self.assertEqual(r["factors"]["wind"]["level"], "unknown")
        self.assertNotEqual(r["overall"], "green")


    def test_evening_just_past_last_light_is_amber(self):
        # Mon 5 Oct: last light ~19:54, session ends 20:00.
        start = datetime(2026, 10, 5, 18, 0, tzinfo=TZ)
        end = datetime(2026, 10, 5, 20, 0, tzinfo=TZ)
        f = rules.eval_darkness(start, end, LAT, LON, TH, is_morning=False)
        self.assertEqual(f["level"], "amber")
        self.assertIn("last light (19:5", f["reasons"][0])

    def test_no_sunrise_sunset_wording(self):
        for morning in (True, False):
            r = session([hour()] * 3, morning=morning)
            text = " ".join(r["factors"]["darkness"]["reasons"])
            self.assertNotIn("Sunrise", text)
            self.assertNotIn("Sunset", text)

    def test_drivers_name_the_river(self):
        r = session([hour()] * 3, morning="day", tides=RISING_TIDES, gauges=HIGH_RIVER)
        self.assertEqual(r["drivers"], ["River / flood"])


class Combinations(unittest.TestCase):
    def test_dark_plus_fog_is_red(self):
        r = session([hour(visibility=1500, code=45)] * 3, morning=True)
        self.assertEqual(r["overall"], "red")
        self.assertIn("Dark + fog", r["combinations"])

    def test_dark_plus_light_rain_is_red(self):
        r = session([hour(rain=0.5)] * 3, morning=True)
        self.assertIn("Dark + rain", r["combinations"])
        self.assertEqual(r["overall"], "red")

    def test_rain_plus_wind_is_red(self):
        r = session([hour(rain=0.5, wind=12)] * 3, morning="day")
        self.assertIn("Rain + wind", r["combinations"])
        self.assertEqual(r["factors"]["wind"]["level"], "red")

    def test_light_rain_daytime_calm_is_green(self):
        r = session([hour(rain=0.5)] * 3, morning="day")
        self.assertEqual(r["overall"], "green", r)

    def test_outgoing_tide_plus_high_river_is_red(self):
        r = session([hour()] * 3, morning="day", tides=EBB_TIDES, gauges=HIGH_RIVER)
        self.assertEqual(r["factors"]["tide"]["level"], "red")
        self.assertIn("Outgoing tide + high river", r["combinations"])

    def test_high_river_with_incoming_tide_stays_amber(self):
        r = session([hour()] * 3, morning="day", tides=RISING_TIDES, gauges=HIGH_RIVER)
        self.assertEqual(r["overall"], "amber")


class Sun(unittest.TestCase):
    def test_sunrise_melbourne_after_dst(self):
        day = datetime(2026, 10, 10, tzinfo=TZ)
        sr = rules.sun_crossing(day, LAT, LON, -0.833, rising=True)
        self.assertEqual((sr.hour, sr.minute // 10), (6, 4))  # ~06:4x AEDT


if __name__ == "__main__":
    unittest.main()
