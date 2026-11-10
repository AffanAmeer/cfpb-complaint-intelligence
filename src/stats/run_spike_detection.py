"""
Find complaint spikes: unusual weeks for the whole market, each product group and
the biggest companies. Saves the results as CSVs in reports/stats/.

Steps
    1. Read weekly counts from the warehouse (sql/stats/weekly_counts.sql), read-only.
    2. Build the series to test:
         overall   all non-bureau companies, and the three credit bureaus together
         product   each product group, non-bureau companies only
         company   the 25 biggest non-bureau companies (last 104 weeks) and each bureau
       The bureaus are kept apart for the same reason as in the KPIs: they are about
       88% of complaints and would hide everything else.
    3. Score every week with the robust rolling z-score and flag spikes (spikes.py).
    4. Check each spike with seasonal decomposition (STL): is it still unusual once
       the yearly pattern is removed?
    5. Join neighbouring spike weeks into episodes and name what drove each one.
    6. Save the checks that justify the method: overdispersion (why not Poisson),
       threshold sensitivity, and the January 2025 validation.

How to run it on the Mac (project folder, venv active)
    python src/stats/run_spike_detection.py
"""

import argparse
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from scipy import stats

import spikes

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "data" / "warehouse" / "complaints.duckdb"
SQL_PATH = PROJECT_ROOT / "sql" / "stats" / "weekly_counts.sql"
OUT_DIR = PROJECT_ROOT / "reports" / "stats"

TOP_COMPANIES = 25
RECENT_WEEKS = 104
STL_CONFIRM_Z = 3.0          # lower bar than detection: this only confirms a flag
VALIDATION_WEEKS = ("2024-12-30", "2025-02-24")


def weekly_series(df):
    """Add rows up to one count per week, with weeks that had no complaints as 0."""
    counts = df.groupby("week_start")["complaints"].sum()
    return counts.asfreq("W-MON", fill_value=0)


def build_series(weekly):
    """Return a list of (level, name, filter_mask) for every series we test."""
    other = ~weekly["is_credit_bureau"]
    series = [
        ("overall", "All non-bureau companies", other),
        ("overall", "All credit bureaus", weekly["is_credit_bureau"]),
    ]
    for group in sorted(weekly["product_group"].unique()):
        series.append(("product", group, other & (weekly["product_group"] == group)))

    recent_start = weekly["week_start"].max() - pd.Timedelta(weeks=RECENT_WEEKS - 1)
    recent = weekly[other & (weekly["week_start"] >= recent_start)]
    top = recent.groupby("company_name")["complaints"].sum().nlargest(TOP_COMPANIES).index
    bureaus = sorted(weekly.loc[weekly["is_credit_bureau"], "company_name"].unique())
    for company in list(top) + bureaus:
        series.append(("company", company, weekly["company_name"] == company))
    return series


def score_all(weekly):
    """Score every week of every series. One row per series x week."""
    frames = []
    for level, name, mask in build_series(weekly):
        counts = weekly_series(weekly[mask])
        scored = spikes.flag_spikes(counts)
        parts, strength = spikes.stl_residual_z(counts)
        scored["stl_z"] = parts["stl_z"]
        scored["plain_z"] = spikes.plain_rolling_z(counts)
        scored["poisson_p"] = stats.poisson.sf(counts - 1, scored["baseline"])
        scored.insert(0, "series", name)
        scored.insert(0, "level", level)
        scored["seasonal_strength"] = strength
        frames.append(scored.rename_axis("week_start").reset_index())
    return pd.concat(frames, ignore_index=True)


def top_driver(weekly, level, name, week):
    """What added the most complaints in a spike week, compared with its own
    12-week median: a company for overall/product series, a product for a company."""
    if level == "overall":
        mask = weekly["is_credit_bureau"] == (name == "All credit bureaus")
        by = "company_name"
    elif level == "product":
        mask = ~weekly["is_credit_bureau"] & (weekly["product_group"] == name)
        by = "company_name"
    else:
        mask = weekly["company_name"] == name
        by = "product_group"

    start = week - pd.Timedelta(weeks=spikes.BASELINE_WEEKS)
    part = weekly[mask & (weekly["week_start"] >= start) & (weekly["week_start"] <= week)]
    table = part.pivot_table(index="week_start", columns=by, values="complaints",
                             aggfunc="sum", fill_value=0)
    table = table.reindex(pd.date_range(start, week, freq="W-MON"), fill_value=0)
    excess = table.loc[week] - table.loc[:week - pd.Timedelta(weeks=1)].median()
    best = excess.idxmax()
    return best, float(excess[best])


def episodes(scores, weekly):
    rows = []
    for (level, name), s in scores.groupby(["level", "series"], sort=False):
        s = s.set_index("week_start")
        flagged = s.index[s["is_spike"]]
        for first, last in spikes.group_episodes(flagged):
            ep = s.loc[first:last]
            ep = ep[ep["is_spike"]]
            peak_week = ep["excess"].idxmax()
            peak = ep.loc[peak_week]
            driver, driver_excess = top_driver(weekly, level, name, peak_week)
            rows.append({
                "level": level,
                "series": name,
                "first_week": first.date(),
                "last_week": last.date(),
                "weeks_flagged": len(ep),
                "peak_week": peak_week.date(),
                "peak_complaints": int(peak["complaints"]),
                "peak_baseline": round(peak["baseline"]),
                "peak_ratio": round(peak["ratio"], 2),
                "peak_z": round(peak["z"], 1),
                "excess_complaints": round(ep["excess"].sum()),
                "peak_stl_z": round(ep["stl_z"].max(), 1),
                "stl_confirmed": bool(ep["stl_z"].max() >= STL_CONFIRM_Z),
                "top_driver": driver,
                "driver_share_of_peak_excess": round(driver_excess / peak["excess"], 2),
            })
    return pd.DataFrame(rows)


def method_checks(scores):
    """Per series: how overdispersed it is, how many weeks a Poisson test would
    flag, how many spikes the robust z flags, and how seasonal it is."""
    tested = scores.dropna(subset=["z"])
    rows = []
    for (level, name), s in tested.groupby(["level", "series"], sort=False):
        counts = s.set_index("week_start")["complaints"]
        rows.append({
            "level": level,
            "series": name,
            "weeks_tested": len(s),
            "dispersion_ratio": round(spikes.dispersion_ratio(counts), 1),
            "poisson_weeks_p_below_0_001": int((s["poisson_p"] < 0.001).sum()),
            "plain_z_weeks_at_least_4": int((s["plain_z"] >= 4).sum()),
            "robust_spike_weeks": int(s["is_spike"].sum()),
            "seasonal_strength": round(s["seasonal_strength"].iloc[0], 2),
        })
    return pd.DataFrame(rows)


def threshold_sensitivity(scores):
    """How the number of spikes changes with the z threshold (the other two rules
    stay fixed). A good threshold sits where the count stops falling quickly."""
    rows = []
    for threshold in (3, 4, 5, 6, 8):
        flag = ((scores["z"] >= threshold) & (scores["ratio"] >= spikes.MIN_RATIO)
                & (scores["excess"] >= spikes.MIN_EXCESS))
        n_episodes = confirmed = 0
        for _, s in scores[flag].groupby("series"):
            s = s.set_index("week_start")
            for first, last in spikes.group_episodes(s.index):
                n_episodes += 1
                confirmed += s.loc[first:last, "stl_z"].max() >= STL_CONFIRM_Z
        rows.append({"z_threshold": threshold, "spike_weeks": int(flag.sum()),
                     "episodes": n_episodes, "episodes_stl_confirmed": int(confirmed)})
    return pd.DataFrame(rows)


def main():
    parser = argparse.ArgumentParser(description="Detect weekly complaint spikes.")
    parser.add_argument("--db", default=str(DB_PATH), help="path to the DuckDB warehouse")
    args = parser.parse_args()
    if not Path(args.db).exists():
        raise SystemExit(f"No warehouse at {args.db}. Run the ingestion and dbt steps first.")

    con = duckdb.connect(args.db, read_only=True)
    weekly = con.sql(SQL_PATH.read_text()).df()
    con.close()
    weekly["week_start"] = pd.to_datetime(weekly["week_start"])
    print(f"Weeks {weekly.week_start.min():%Y-%m-%d} to {weekly.week_start.max():%Y-%m-%d}, "
          f"{weekly.complaints.sum():,} complaints.\n")

    scores = score_all(weekly)
    eps = episodes(scores, weekly)
    checks = method_checks(scores)

    sens = threshold_sensitivity(scores)

    lo, hi = VALIDATION_WEEKS
    validation = scores[(scores["week_start"] >= lo) & (scores["week_start"] <= hi)]
    validation = validation[validation.groupby("series")["is_spike"].transform("any")]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    keep = ["level", "series", "week_start", "complaints", "baseline", "spread", "z",
            "ratio", "excess", "is_spike", "stl_z", "plain_z"]
    rounded = scores[keep].round({"baseline": 1, "spread": 1, "z": 2, "ratio": 3,
                                  "excess": 1, "stl_z": 2, "plain_z": 2})
    outputs = {
        "weekly_scores.csv": rounded,
        "spike_episodes.csv": eps,
        "method_checks.csv": checks,
        "threshold_sensitivity.csv": sens,
        "jan2025_validation.csv": validation[keep].round({"baseline": 1, "spread": 1, "z": 1,
                                                          "ratio": 2, "excess": 0,
                                                          "stl_z": 1, "plain_z": 1}),
    }
    for file, table in outputs.items():
        table.to_csv(OUT_DIR / file, index=False)
        print(f"== {file}: {len(table):,} rows")

    pd.set_option("display.width", 220)
    pd.set_option("display.max_columns", 20)
    print("\nEpisodes per level:", eps.groupby("level").size().to_dict(),
          "| STL-confirmed:", int(eps["stl_confirmed"].sum()), "of", len(eps))
    print("\nBiggest episodes by excess complaints:")
    print(eps.nlargest(12, "excess_complaints")[
        ["series", "first_week", "last_week", "peak_complaints", "peak_baseline",
         "peak_z", "excess_complaints", "stl_confirmed", "top_driver"]].to_string(index=False))
    print("\nThreshold sensitivity:")
    print(sens.to_string(index=False))


if __name__ == "__main__":
    main()
