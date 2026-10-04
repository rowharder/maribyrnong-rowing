"""Run:  python3 -m unittest discover tests"""
import json
import sys
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import rules  # noqa: E402

TH = json.loads((Path(__file__).resolve().parent.parent / "config" / "thresholds.json").read_text())
TZ = ZoneInfo("Australia/Melbourne")
LAT, LON = -37.775, 144.892
NO_WARNINGS = {"flood": [], "flood_watch": [], "thunderstorm": [], "severe_weather": []}
QUIET_GAUGES = [{"role": "keilor", "name": "Keilor", "level_m": 0.4, "rise_m_per_hr": 0.0}]


def hour(**kw):
    base = {"wind": 5, "gust": 8, "temp": 15, "rain": 0, "cape": 0, "visibility": 20000, "code": 1}
    return base | kw


def speed(kmh, river=None):
    """One flow_model row with the given speed (km/h, positive = out)."""
    river = kmh if river is None else river
    return {"speed_kmh": kmh, "river_kmh": river, "tide_kmh": kmh - river, "flow_m3s": 20.0}


CALM_FLOW = [speed(0.4), speed(0.6)]
FAST_FLOW = [speed(2.5)]  # yellow


def flow(rows=CALM_FLOW, gauges=QUIET_GAUGES, warnings=NO_WARNINGS, watch_applies=True):
    return rules.eval_flow(rows, gauges, warnings, TH, watch_applies)


def session(hours, *, morning=True, flow_rows=CALM_FLOW, warnings=NO_WARNINGS, day_text=""):
    start = datetime(2026, 10, 10, 5, 30, tzinfo=TZ) if morning else datetime(2026, 10, 10, 18, 0, tzinfo=TZ)
    end = datetime(2026, 10, 10, 7, 0, tzinfo=TZ) if morning else datetime(2026, 10, 10, 20, 0, tzinfo=TZ)
    # Daytime variant (no darkness) for isolating other rules.
    if morning == "day":
        start, end = datetime(2026, 10, 10, 10, 0, tzinfo=TZ), datetime(2026, 10, 10, 11, 30, tzinfo=TZ)
    return rules.evaluate_session(start=start, end=end, is_morning=bool(morning), hours=hours, day_text=day_text,
                                  warnings=warnings, flow=flow(flow_rows, warnings=warnings), lat=LAT, lon=LON,
                                  th=TH, now=start)


class Single(unittest.TestCase):
    def test_calm_daytime_is_green(self):
        r = session([hour()] * 3, morning="day")
        self.assertEqual(r["overall"], "green", r)

    def test_wind_bands(self):
        self.assertEqual(rules.eval_wind([hour(wind=9)], TH)["level"], "green")
        self.assertEqual(rules.eval_wind([hour(wind=12)], TH)["level"], "amber")
        self.assertEqual(rules.eval_wind([hour(wind=16)], TH)["level"], "red")

    def test_visibility_bands(self):
        lv = lambda m: rules.eval_visibility([hour(visibility=m)], "", False, TH)
        self.assertEqual(lv(1600)["level"], "green")
        self.assertEqual(lv(1590)["level"], "amber")
        self.assertEqual(lv(500)["level"], "amber")
        self.assertEqual(lv(490)["level"], "red")
        self.assertEqual(lv(1594)["value"], "1,590 m")
        self.assertEqual(lv(4300)["value"], "4.3 km")

    def test_heat_and_cold(self):
        self.assertEqual(rules.eval_temp([hour(temp=36)], TH)["level"], "red")
        self.assertEqual(rules.eval_temp([hour(temp=31)], TH)["level"], "amber")
        self.assertEqual(rules.eval_temp([hour(temp=9)], TH)["level"], "amber")
        self.assertEqual(rules.eval_temp([hour(temp=10)], TH)["level"], "green")

    def test_dark_alone_is_just_a_lights_note(self):
        r = session([hour()] * 3, morning=True)
        self.assertNotIn("darkness", r["factors"])
        self.assertEqual(r["overall"], "green", r)
        self.assertTrue(r["lights"]["needed"])
        self.assertRegex(r["lights"]["short"], r"^Lights to 6:\d\dam$")

    def test_daylight_session_needs_no_lights(self):
        r = session([hour()] * 3, morning="day")
        self.assertFalse(r["lights"]["needed"])
        self.assertEqual(r["lights"]["short"], "")

    def test_flow_speed_bands(self):
        self.assertEqual(flow([speed(1.94)])["level"], "green")   # shows 1.9 km/h
        self.assertEqual(flow([speed(1.96)])["level"], "amber")   # shows 2.0 km/h
        self.assertEqual(flow([speed(3.9)])["level"], "amber")
        self.assertEqual(flow([speed(4.0)])["level"], "red")

    def test_flow_judged_on_fastest_either_way(self):
        f = flow([speed(0.5), speed(-2.2, river=0.3), speed(1.0)])
        self.assertEqual(f["level"], "amber")
        self.assertEqual(f["value"], "2.2 km/h")
        self.assertIn("2.2 km/h in", f["reasons"][0])
        self.assertEqual(f["direction"], "in")
        self.assertEqual(flow([speed(0.4)])["direction"], "out")
        self.assertIsNone(flow([])["direction"])

    def test_flow_reason_splits_river_and_tide(self):
        f = flow([speed(1.3, river=0.9)])
        self.assertIn("river 0.9 + tide +0.4", f["reasons"][0])

    def test_no_flow_estimate_is_unknown(self):
        self.assertEqual(flow([])["level"], "unknown")

    def test_upstream_gauge_rising_fast(self):
        rising = [{"role": "upstream", "name": "Darraweit Guim", "level_m": 1.5, "rise_m_per_hr": 0.6}]
        self.assertEqual(flow(gauges=rising)["level"], "red")

    def test_flood_watch_only_counts_when_it_applies(self):
        w = rules.classify_warnings([{"title": "Flood Watch for parts of Central Victoria", "link": ""}])
        self.assertEqual(flow(warnings=w)["level"], "amber")
        self.assertEqual(flow(warnings=w, watch_applies=False)["level"], "green")

    def test_maribyrnong_flood_warning_is_red(self):
        w = rules.classify_warnings([{"title": "03/10:00 EST Minor Flood Warning for the Maribyrnong River", "link": ""}])
        self.assertEqual(flow(warnings=w)["level"], "red")
        self.assertEqual(flow([], warnings=w)["level"], "red")

    def test_cancelled_and_other_river_warnings_ignored(self):
        w = rules.classify_warnings([
            {"title": "Cancellation of Flood Warning for the Maribyrnong River", "link": ""},
            {"title": "Moderate Flood Warning for the Werribee River", "link": ""},
            {"title": "Final Flood Watch for parts of Gippsland, North East, Central, South West and North West Victoria", "link": ""},
            {"title": "03/10:00 EST Final Flood Warning for the Maribyrnong River", "link": ""},
        ])
        self.assertEqual(w["flood_watch"] + w["flood"], [])
        self.assertEqual(flow(warnings=w)["level"], "green")

    def test_missing_forecast_is_unknown_not_green(self):
        r = session([None] * 3, morning="day")
        self.assertEqual(r["factors"]["wind"]["level"], "unknown")
        self.assertNotEqual(r["overall"], "green")


    def test_evening_after_sunset_needs_lights(self):
        # Mon 5 Oct: sunset ~19:28, session ends 20:00.
        start = datetime(2026, 10, 5, 18, 0, tzinfo=TZ)
        end = datetime(2026, 10, 5, 20, 0, tzinfo=TZ)
        f = rules.eval_darkness(start, end, LAT, LON, TH, is_morning=False)
        self.assertTrue(f["active"])
        self.assertRegex(f["lights"]["short"], r"^Lights from 7:2\dpm$")
        self.assertIn("sunset 7:2", f["lights"]["detail"])

    def test_weekend_morning_after_sunrise_needs_no_lights(self):
        # Sat 9 Jan 2027: sunrise ~06:05, weekend session 06:30-08:00.
        start = datetime(2027, 1, 9, 6, 30, tzinfo=TZ)
        f = rules.eval_darkness(start, start.replace(hour=8), LAT, LON, TH, is_morning=True)
        self.assertFalse(f["active"])

    def test_drivers_name_the_flow(self):
        r = session([hour()] * 3, morning="day", flow_rows=FAST_FLOW)
        self.assertEqual(r["drivers"], ["Flow"])


    def test_thunderstorm_in_session_is_red(self):
        r = session([hour(), hour(code=95), hour()], morning="day")
        self.assertEqual(r["factors"]["lightning"]["level"], "red")
        self.assertIn("Lightning", r["drivers"])

    def test_thunder_in_day_text_is_amber(self):
        r = session([hour()] * 3, morning="day", day_text="Possible thunderstorm in the afternoon.")
        self.assertEqual(r["factors"]["lightning"]["level"], "amber")

    def test_damaging_winds_text_does_not_affect_lightning(self):
        r = session([hour()] * 3, morning="day", day_text="Damaging winds possible.")
        self.assertEqual(r["factors"]["lightning"]["level"], "green")

    def test_warnings_split_between_lightning_and_wind(self):
        w = rules.classify_warnings([
            {"title": "Severe Thunderstorm Warning for Central Forecast District", "link": ""},
            {"title": "Severe Weather Warning for Central Forecast District", "link": ""},
        ])
        self.assertEqual(len(w["thunderstorm"]), 1)
        self.assertEqual(len(w["severe_weather"]), 1)
        r = session([hour()] * 3, morning="day", warnings=w)
        self.assertEqual(r["factors"]["lightning"]["level"], "red")
        self.assertEqual(r["factors"]["wind"]["level"], "red")


class Combinations(unittest.TestCase):
    def test_dark_plus_thin_fog_stays_amber(self):
        r = session([hour(visibility=1040, code=45)] * 3, morning=True)
        self.assertEqual(r["factors"]["visibility"]["level"], "amber")
        self.assertNotIn("Dark + fog", r["combinations"])
        r = session([hour(code=45)] * 3, morning=True)  # fog forecast, visibility still good
        self.assertNotIn("Dark + fog", r["combinations"])

    def test_dark_plus_fog_is_red(self):
        r = session([hour(visibility=990, code=45)] * 3, morning=True)
        self.assertEqual(r["overall"], "red")
        self.assertIn("Dark + fog", r["combinations"])
        self.assertEqual(r["factors"]["visibility"]["level"], "red")
        self.assertEqual(r["drivers"], ["Dark + fog"])

    def test_dark_plus_light_rain_is_red(self):
        r = session([hour(rain=0.5)] * 3, morning=True)
        self.assertIn("Dark + rain", r["combinations"])
        self.assertEqual(r["overall"], "red")
        self.assertEqual(r["factors"]["rain"]["level"], "red")

    def test_rain_plus_wind_is_red(self):
        r = session([hour(rain=0.5, wind=12)] * 3, morning="day")
        self.assertIn("Rain + wind", r["combinations"])
        self.assertEqual(r["factors"]["wind"]["level"], "red")

    def test_light_rain_daytime_calm_is_green(self):
        r = session([hour(rain=0.5)] * 3, morning="day")
        self.assertEqual(r["overall"], "green", r)

    def test_fast_flow_is_not_part_of_a_combination(self):
        r = session([hour()] * 3, morning="day", flow_rows=FAST_FLOW)
        self.assertEqual(r["overall"], "amber")
        self.assertEqual(r["combinations"], [])


class Sun(unittest.TestCase):
    def test_sunrise_melbourne_after_dst(self):
        day = datetime(2026, 10, 10, tzinfo=TZ)
        sr = rules.sun_crossing(day, LAT, LON, -0.833, rising=True)
        self.assertEqual((sr.hour, sr.minute // 10), (6, 4))  # ~06:4x AEDT


if __name__ == "__main__":
    unittest.main()
