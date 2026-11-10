"""
Spike detection methods. Pure functions: they take pandas Series of weekly counts
and return numbers, so they can be tested without the warehouse
(tests/test_spikes.py) and reused later (monthly brief, Databricks).

The main detector is a ROBUST ROLLING Z-SCORE:

    baseline = median of the previous 12 weeks (not including this week)
    spread   = MAD of the previous 12 weeks x 1.4826
    z        = (this week - baseline) / spread

Why each choice:
    * Previous weeks only: the score uses nothing from the future, so it could run
      every week as an alert. (STL, below, uses the whole series, so it can only
      check spikes after the fact.)
    * Median and MAD instead of mean and standard deviation: one huge week pulls a
      mean and a standard deviation up for the next 12 weeks, which hides the
      weeks right after a spike ("masking"). A median and MAD barely move.
    * 1.4826: makes the MAD the same size as a standard deviation when the data is
      normal, so z = 4 means roughly "4 standard deviations".
    * Spread never goes below sqrt(baseline): that is the noise a Poisson count
      would have, so a very smooth baseline can't make a small bump look huge.

A week is a SPIKE when all three hold:
    z >= 4                     statistically unusual for this series
    count >= 1.5 x baseline    big enough to matter (practical significance)
    count - baseline >= 100    ignores tiny series where 1.5x is a handful of complaints
"""

import numpy as np
import pandas as pd
from statsmodels.tsa.seasonal import STL

BASELINE_WEEKS = 12
MAD_TO_SD = 1.4826
Z_THRESHOLD = 4.0
MIN_RATIO = 1.5
MIN_EXCESS = 100


def _mad(values):
    """Median absolute deviation: the median distance from the median."""
    return np.median(np.abs(values - np.median(values)))


def robust_rolling_z(counts, weeks=BASELINE_WEEKS):
    """Robust z-score of each week against the previous `weeks` weeks.

    Returns a DataFrame with columns baseline, spread, z. The first `weeks` rows are
    NaN because they have no full baseline yet.
    """
    past = counts.shift(1).rolling(weeks)              # shift(1) = leave this week out
    baseline = past.median()
    mad = past.apply(_mad, raw=True) * MAD_TO_SD
    spread = np.maximum(mad, np.sqrt(baseline.clip(lower=1)))
    z = (counts - baseline) / spread
    return pd.DataFrame({"baseline": baseline, "spread": spread, "z": z})


def plain_rolling_z(counts, weeks=BASELINE_WEEKS):
    """The textbook version (mean and standard deviation). Kept only to show
    why the robust version is used: see the masking check in the docs."""
    past = counts.shift(1).rolling(weeks)
    return (counts - past.mean()) / past.std()


def flag_spikes(counts, z_threshold=Z_THRESHOLD, min_ratio=MIN_RATIO, min_excess=MIN_EXCESS):
    """Score every week and mark the spikes. Returns one row per week."""
    scored = robust_rolling_z(counts)
    scored.insert(0, "complaints", counts)
    scored["ratio"] = counts / scored["baseline"]
    scored["excess"] = counts - scored["baseline"]
    scored["is_spike"] = (
        (scored["z"] >= z_threshold)
        & (scored["ratio"] >= min_ratio)
        & (scored["excess"] >= min_excess)
    )
    return scored


def group_episodes(spike_weeks, max_gap_weeks=1):
    """Join spike weeks that are close together into episodes.

    A spike often lasts more than one week (a burst and then a tail), and it is one
    event, not three. Weeks at most `max_gap_weeks` quiet weeks apart are joined.
    Takes a sorted DatetimeIndex of spike weeks and returns a list of
    (first_week, last_week) pairs.
    """
    episodes = []
    for week in spike_weeks:
        if episodes and (week - episodes[-1][1]).days <= 7 * (max_gap_weeks + 1):
            episodes[-1][1] = week
        else:
            episodes.append([week, week])
    return [tuple(e) for e in episodes]


def stl_residual_z(counts, period=52):
    """Seasonal decomposition (STL) of log weekly counts.

    log(count) = trend + seasonal + residual
        trend     the slow level (here: years of growth)
        seasonal  the pattern that repeats every 52 weeks (busy Jan to Mar, quiet Dec)
        residual  what is left: spikes show up here

    Logs, because the series grew several times over: on a log scale a +20% January
    means the same in 2015 and in 2025. robust=True stops spikes from bending the
    trend and seasonal parts. The residual is turned into a robust z with one MAD
    for the whole series.

    Limits worth knowing: STL looks at weeks on both sides, so it can only check a
    spike after the fact. It needs several years of data (on 4 years a one-off
    spike can leak into the seasonal part; see tests). And the result moves with
    the seasonal smoothing window: statsmodels' default (7) is used; with 13, 13 of
    the 101 episodes change between confirmed and not. So STL is a second opinion,
    not a verdict.

    Returns (DataFrame with trend, seasonal, residual, stl_z; seasonal_strength).
    Seasonal strength is 1 - var(residual) / var(seasonal + residual): 0 means no
    seasonality, 1 means the residual is tiny next to the seasonal pattern.
    """
    y = np.log(counts.clip(lower=1))
    fit = STL(y, period=period, robust=True).fit()
    resid = fit.resid
    stl_z = (resid - resid.median()) / (_mad(resid.to_numpy()) * MAD_TO_SD)
    strength = max(0.0, 1 - np.var(resid) / np.var(fit.seasonal + resid))
    parts = pd.DataFrame({
        "trend": fit.trend,
        "seasonal": fit.seasonal,
        "residual": resid,
        "stl_z": stl_z,
    })
    return parts, strength


def dispersion_ratio(counts, weeks=BASELINE_WEEKS):
    """Median over all baselines of variance / mean.

    A Poisson count has variance = mean, so this would be about 1. Much bigger than 1
    ("overdispersion") means a Poisson test will call far too many weeks significant.
    """
    past = counts.shift(1).rolling(weeks)
    return float((past.var() / past.mean()).median())


def log_ratio_se(before, after):
    """Compare two windows of weekly counts.

    Works on log counts, so the result is a ratio: 1.30 means "30% higher after".
    Uses Welch's t-interval (no equal-variance assumption) on the weekly values, so
    the uncertainty comes from how much the weeks really vary, not from a Poisson
    formula that would be far too narrow here.

    Returns (log_diff, standard_error, degrees_of_freedom).
    """
    lb, la = np.log(before), np.log(after)
    vb, va = lb.var(ddof=1) / len(lb), la.var(ddof=1) / len(la)
    se = np.sqrt(vb + va)
    dof = (vb + va) ** 2 / (vb**2 / (len(lb) - 1) + va**2 / (len(la) - 1))
    return la.mean() - lb.mean(), se, dof
