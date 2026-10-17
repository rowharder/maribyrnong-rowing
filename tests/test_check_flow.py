"""Run:  python3 -m unittest discover tests"""
import json
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import check_flow as cf  # noqa: E402

GEOM = {"width_m": 50, "depth_m": 2.0, "upstream_tidal_area_m2": 360000, "keilor_lag_hours": 2}
MODEL = {"mean_level_m": 0.0, "setup": {"k": 0.004, "p": 1.0}}


class CheckFlow(unittest.TestCase):
    def test_nearest_only_within_window(self):
        t0 = datetime(2026, 10, 17, 8, 0)
        pts = [(t0 - timedelta(hours=1), "a"), (t0 + timedelta(minutes=20), "b")]
        self.assertEqual(cf.nearest(pts, t0)[1], "b")
        self.assertIsNone(cf.nearest(pts, t0 + timedelta(hours=2)))

    def test_estimate_at_rising_tide_comes_in(self):
        t0 = datetime(2026, 10, 17, 0, 0)
        hours = [t0 + timedelta(hours=i) for i in range(12)]
        levels = [(t, 0.1 * i) for i, t in enumerate(hours)]  # rising 0.1 m/hr
        flows = [(t, 1.0) for t in hours]
        r = cf.estimate_at(levels, flows, datetime(2026, 10, 17, 6, 0), MODEL, GEOM)
        self.assertLess(r["speed_kmh"], 0)
        self.assertEqual(cf.direction(r["speed_kmh"]), "in")
        self.assertIsNone(cf.estimate_at(levels, flows, datetime(2026, 10, 18, 6, 0), MODEL, GEOM))

    def test_direction_dead_band(self):
        self.assertEqual(cf.direction(0.05), "still")
        self.assertEqual(cf.direction(0.3), "out")

    def test_log_is_valid(self):
        log = json.loads((ROOT / "config" / "flow_observations.json").read_text())
        for o in log["observations"]:
            cf.parse_time(o["time"])
            self.assertIn(o["seen"], ("out", "in", "still"))


if __name__ == "__main__":
    unittest.main()
