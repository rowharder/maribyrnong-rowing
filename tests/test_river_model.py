"""Run:  python3 -m unittest discover tests"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import river_model as rm  # noqa: E402

MODEL_PATH = ROOT / "config" / "river_model.json"


class Cleaning(unittest.TestCase):
    def test_despike_removes_glitch_keeps_flood(self):
        glitch = [0.8] * 30 + [1100.0] * 4 + [0.8] * 30
        self.assertTrue(all(v is None for v in rm.despike(glitch)[30:34]))
        flood = [0.8] * 30 + [5, 20, 80, 200, 400, 600, 700] + [600 - 20 * i for i in range(25)]
        self.assertEqual(rm.despike(flood), flood)

    def test_rainless_flood_is_dropped(self):
        flow = [0.5] * 200 + [400.0] + [0.5] * 10
        self.assertIsNone(rm.drop_rainless_floods(flow, [0.0] * 211)[200])
        wet = [0.0] * 150 + [3.0] * 20 + [0.0] * 41
        self.assertEqual(rm.drop_rainless_floods(flow, wet)[200], 400.0)

    def test_clean_rain_drops_impossible_values(self):
        self.assertEqual(rm.clean_rain([1.0, 216.0, None, -1]), [1.0, None, None, None])

    def test_rating_curve_monotonic(self):
        r = {"a": 0.2, "b": 0.25, "c": 0.5}
        levels = [rm.flow_to_level(q, r) for q in (0, 1, 5, 20, 100)]
        self.assertEqual(levels, sorted(levels))


class Windows(unittest.TestCase):
    def test_window_sums(self):
        past = [0.0] * 700 + [1.0] * 20          # 20 mm in the last 20 hours
        fut = [2.0] * 72
        p, wet7, wet30, f = rm.window_sums(past, fut, 12)
        self.assertEqual(p[:3], [6.0, 6.0, 8.0])
        self.assertEqual(wet7, 20.0)
        self.assertEqual(f, [12.0, 12.0, 0.0, 0.0, 0.0])


@unittest.skipUnless(MODEL_PATH.exists(), "model not fitted yet")
class FittedModel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = json.loads(MODEL_PATH.read_text())

    def test_forecast_starts_near_now(self):
        out = rm.forecast(self.model, 5.0, 5.0, [0.0] * 720, [0.0] * 72, 72)
        self.assertEqual(len(out), 72)
        self.assertLess(abs(out[0] - 5.0), 1.5)

    def test_more_forecast_rain_means_higher_river(self):
        past = [0.3] * 720
        dry = rm.forecast(self.model, 5.0, 5.0, past, [0.0] * 72, 72)
        wet = rm.forecast(self.model, 5.0, 5.0, past, [4.0] * 12 + [0.0] * 60, 72)
        self.assertGreater(max(wet), max(dry))

    def test_no_rain_high_river_falls(self):
        out = rm.forecast(self.model, 40.0, 45.0, [0.0] * 720, [0.0] * 72, 72)
        self.assertLess(out[-1], 40.0)


class SessionFlow(unittest.TestCase):
    """build.session_flow picks the forecast speed rows inside a session."""

    def setUp(self):
        import build
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo
        self.build, self.td = build, timedelta
        self.now = datetime(2026, 10, 4, 8, 0, tzinfo=ZoneInfo("Australia/Melbourne"))
        rows = [{"time": (self.now + timedelta(minutes=15 * i)).isoformat(timespec="minutes"), "speed_kmh": i / 100,
                 "held": i > 72 * 4} for i in range(100 * 4)]
        self.flow = {"forecast": rows, "notes": []}

    def test_rows_inside_session_only(self):
        start = self.now + self.td(hours=10)
        rows, note = self.build.session_flow(self.flow, start, start + self.td(hours=2))
        self.assertEqual(len(rows), 9)  # 15-minute steps, both ends included
        self.assertEqual(note, "")

    def test_past_forecast_says_flow_is_held(self):
        start = self.now + self.td(hours=80)
        rows, note = self.build.session_flow(self.flow, start, start + self.td(hours=2))
        self.assertTrue(rows)
        self.assertIn("held", note)

    def test_no_flow_estimate(self):
        self.assertEqual(self.build.session_flow(None, self.now, self.now), ([], ""))


if __name__ == "__main__":
    unittest.main()
