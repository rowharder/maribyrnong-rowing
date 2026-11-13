"""Run:  python3 -m unittest discover tests"""
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import build  # noqa: E402

TZ = ZoneInfo("Australia/Melbourne")
NOW = datetime(2026, 11, 14, 12, 0, tzinfo=TZ)
SRC = {"forecast_fallback_hours": 24, "published_data_url": "https://example.invalid/latest.json"}


def ok(*_):
    return {"2026-11-14T18:00": {"wind": 10}}


def fail(*_):
    raise TimeoutError("handshake timed out")


def saved(hours_ago):
    t = (NOW - timedelta(hours=hours_ago)).isoformat(timespec="minutes")
    return {"hourly": {"fetched_at": t, "data": {"old": True}}}


class ForecastFallback(unittest.TestCase):
    def get(self, fn, previous):
        cache = build.ForecastCache(SRC, NOW)
        status = {}
        with mock.patch.object(build, "previous_forecasts", return_value=previous) as prev:
            data = cache.get(status, "Hourly forecast", "hourly", fn)
        return data, status["Hourly forecast"], cache, prev

    def test_fresh_fetch_is_used_and_saved(self):
        data, status, cache, prev = self.get(ok, saved(3))
        self.assertEqual(data, ok())
        self.assertEqual(status, "ok")
        self.assertEqual(cache.saved["hourly"]["fetched_at"], NOW.isoformat(timespec="minutes"))
        self.assertEqual(cache.fallbacks, {})
        prev.assert_not_called()  # no extra download when the fetch works

    def test_failed_fetch_uses_last_good_forecast(self):
        data, status, cache, _ = self.get(fail, saved(3))
        self.assertEqual(data, {"old": True})
        self.assertTrue(status.startswith("using forecast from Sat 9am"))
        self.assertIn("handshake timed out", status)
        self.assertEqual(cache.fallbacks["hourly"], saved(3)["hourly"]["fetched_at"])
        self.assertEqual(cache.saved["hourly"], saved(3)["hourly"])  # carried forward with its original time

    def test_forecast_older_than_a_day_is_not_used(self):
        data, status, cache, _ = self.get(fail, saved(25))
        self.assertIsNone(data)
        self.assertTrue(status.startswith("error:"))
        self.assertEqual(cache.saved, {})

    def test_nothing_saved_before(self):
        data, status, _, _ = self.get(fail, {})
        self.assertIsNone(data)
        self.assertTrue(status.startswith("error:"))

    def test_newest_saved_forecast_wins(self):
        local, published = saved(10), saved(2)
        with mock.patch.object(build, "OUT") as out, \
                mock.patch.object(build.sources, "_get", return_value=build.json.dumps({"forecast_cache": published})):
            out.exists.return_value = True
            out.read_text.return_value = build.json.dumps({"forecast_cache": local})
            best = build.previous_forecasts(SRC)
        self.assertEqual(best["hourly"], published["hourly"])


if __name__ == "__main__":
    unittest.main()
