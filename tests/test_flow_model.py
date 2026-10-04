"""Run:  python3 -m unittest discover tests"""
import json
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import flow_model as fm  # noqa: E402

GEOM = {"width_m": 50, "depth_m": 2.0, "upstream_tidal_area_m2": 360000}
MODEL = {"mean_level_m": 0.0, "setup": {"k": 0.004, "p": 1.0}}


class Speed(unittest.TestCase):
    def test_river_only_is_flow_over_area(self):
        total, river, tide = fm.speed_kmh(100, 0.0, 0.0, GEOM)
        self.assertAlmostEqual(river, 100 / (50 * 2.0) * 3.6)
        self.assertEqual(tide, 0.0)
        self.assertAlmostEqual(total, 3.6)

    def test_falling_tide_adds_downstream_speed_rising_subtracts(self):
        calm = fm.speed_kmh(20, 0.0, 0.0, GEOM)[0]
        self.assertGreater(fm.speed_kmh(20, -0.2, 0.0, GEOM)[0], calm)
        self.assertLess(fm.speed_kmh(20, 0.2, 0.0, GEOM)[0], calm)
        # 0.2 m/hr over 360,000 m² is 20 m³/s; against 20 m³/s of river the water stands still.
        self.assertAlmostEqual(fm.speed_kmh(20, 0.2, 0.0, GEOM)[0], 0.0)

    def test_higher_water_is_slower(self):
        self.assertLess(fm.speed_kmh(50, 0.0, 0.5, GEOM)[0], fm.speed_kmh(50, 0.0, 0.0, GEOM)[0])

    def test_depth_never_goes_to_zero(self):
        self.assertTrue(fm.speed_kmh(10, 0.0, -5.0, GEOM)[0] < 10)


class Setup(unittest.TestCase):
    def test_zero_without_flow_and_rises_with_it(self):
        fit = {"k": 0.0033, "p": 1.08}
        self.assertEqual(fm.setup_m(0, fit), 0.0)
        self.assertLess(fm.setup_m(10, fit), fm.setup_m(100, fit))

    def test_fit_recovers_power_law(self):
        fit = fm.fit_setup([(q, 0.002 * q ** 1.2) for q in (5, 20, 80, 300)])
        self.assertAlmostEqual(fit["k"], 0.002, places=5)
        self.assertAlmostEqual(fit["p"], 1.2, places=3)

    def test_fitted_model_is_present_and_sensible(self):
        model = json.loads((ROOT / "config" / "flow_model.json").read_text())
        self.assertLess(fm.setup_m(10, model["setup"]), 0.1)
        self.assertGreater(fm.setup_m(500, model["setup"]), 1.0)


class Series(unittest.TestCase):
    def test_forecast_rows_combine_flow_tide_and_setup(self):
        t0 = datetime(2026, 10, 5, 6, 0)
        rows = fm.forecast_rows([t0], lambda t: 50.0, lambda t: (0.5, -0.1), 0.1, MODEL, GEOM)
        r = rows[0]
        self.assertAlmostEqual(r["mouth_m"], 0.6)
        self.assertAlmostEqual(r["poyntons_m"], 0.8)          # mouth + 0.004 * 50
        self.assertGreater(r["tide_kmh"], 0)                   # falling tide pushes water out
        self.assertAlmostEqual(r["speed_kmh"], r["river_kmh"] + r["tide_kmh"], places=1)

    def test_measured_rows_use_rate_from_gauge(self):
        t0 = datetime(2026, 10, 5, 6, 0)
        levels = [(t0 + timedelta(minutes=6 * i), 0.3 * i / 10) for i in range(21)]  # rising 0.3 m/hr
        rows = fm.measured_rows(levels, lambda t: 0.0, MODEL, GEOM)
        mid = rows[10]
        self.assertLess(mid["speed_kmh"], 0)  # rising tide, no river: water comes in

    def test_interp(self):
        pts = [(0, 0.0), (10, 10.0)]
        self.assertEqual(fm.interp(pts, 5), 5.0)
        self.assertIsNone(fm.interp(pts, 11))


if __name__ == "__main__":
    unittest.main()
