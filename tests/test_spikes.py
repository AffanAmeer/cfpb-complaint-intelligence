"""
Unit tests for src/stats/spikes.py, on small made-up series where we know the
right answer. No warehouse needed.

Run from the project folder:
    python -m unittest discover tests
"""

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "stats"))
import spikes  # noqa: E402


def weekly(values, start="2024-01-01"):
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="W-MON"), dtype=float)


class RobustZTest(unittest.TestCase):

    def test_first_weeks_have_no_score(self):
        scored = spikes.robust_rolling_z(weekly([100] * 20))
        self.assertTrue(scored["z"].iloc[:12].isna().all())
        self.assertFalse(scored["z"].iloc[12:].isna().any())

    def test_current_week_is_not_in_its_own_baseline(self):
        counts = weekly([100] * 12 + [5000])
        scored = spikes.robust_rolling_z(counts)
        self.assertEqual(scored["baseline"].iloc[-1], 100)

    def test_spread_never_below_poisson_noise(self):
        # A perfectly flat baseline has MAD = 0. The floor is sqrt(400) = 20.
        scored = spikes.robust_rolling_z(weekly([400] * 12 + [460]))
        self.assertEqual(scored["spread"].iloc[-1], 20)
        self.assertAlmostEqual(scored["z"].iloc[-1], 3.0)

    def test_median_resists_masking(self):
        # One huge week, then a week that is still 3x normal.
        rng = np.random.default_rng(0)
        normal = list(rng.normal(1000, 30, 12).round())
        counts = weekly(normal + [20000, 3000])
        robust = spikes.robust_rolling_z(counts)["z"].iloc[-1]
        plain = spikes.plain_rolling_z(counts).iloc[-1]
        self.assertGreater(robust, 4)   # still caught
        self.assertLess(plain, 4)       # hidden by the inflated standard deviation


class FlagTest(unittest.TestCase):

    def test_all_three_rules_needed(self):
        base = [1000, 1010, 990, 1005, 995, 1000, 1002, 998, 1001, 999, 1003, 997]
        # +150 is z >= 4 but only 1.15x the baseline: not a spike.
        self.assertFalse(spikes.flag_spikes(weekly(base + [1150]))["is_spike"].iloc[-1])
        # 2x the baseline: a spike.
        self.assertTrue(spikes.flag_spikes(weekly(base + [2000]))["is_spike"].iloc[-1])
        # Tiny series: 3x but only +40 complaints: not a spike.
        self.assertFalse(spikes.flag_spikes(weekly([20] * 12 + [60]))["is_spike"].iloc[-1])


class EpisodeTest(unittest.TestCase):

    def test_grouping(self):
        weeks = pd.to_datetime(["2025-01-06", "2025-01-13", "2025-01-27", "2025-03-03"])
        self.assertEqual(spikes.group_episodes(weeks), [
            (pd.Timestamp("2025-01-06"), pd.Timestamp("2025-01-27")),   # one quiet week in between
            (pd.Timestamp("2025-03-03"), pd.Timestamp("2025-03-03")),
        ])

    def test_empty(self):
        self.assertEqual(spikes.group_episodes(pd.DatetimeIndex([])), [])


class StlTest(unittest.TestCase):

    def test_finds_seasonality_and_a_spike(self):
        weeks = 52 * 8
        t = np.arange(weeks)
        seasonal = 1 + 0.2 * np.sin(2 * np.pi * t / 52)
        rng = np.random.default_rng(1)
        counts = weekly(1000 * seasonal * rng.normal(1, 0.01, weeks), start="2016-01-04")
        counts.iloc[150] *= 2
        parts, strength = spikes.stl_residual_z(counts)
        self.assertGreater(strength, 0.8)
        self.assertEqual(parts["stl_z"].idxmax(), counts.index[150])


class LogRatioTest(unittest.TestCase):

    def test_doubling(self):
        diff, se, dof = spikes.log_ratio_se(np.array([100, 110, 90, 100.0]), np.array([200, 220, 180, 200.0]))
        self.assertAlmostEqual(np.exp(diff), 2.0, places=6)
        self.assertGreater(se, 0)


if __name__ == "__main__":
    unittest.main()
