"""
Two significance tests with confidence intervals. Run run_spike_detection.py first.

1. Before/after: did the January 2025 spike leave complaints higher for good?
   A spike is a short burst. The business question afterwards is whether the level
   went back to normal. We compare 12 normal weeks before the spike with 12 weeks
   after it ended.

   Problem: complaints were rising anyway, and the "after" weeks (March to May) are
   a busier time of year than the "before" weeks (late October to early January).
   So we also measure a CONTROL series that the spike did not touch: non-bureau
   complaints outside money transfer and checking/savings. The spike's lasting
   effect is the series' change MINUS the control's change (on a log scale, a
   ratio of ratios). This is a difference-in-differences.

2. Relief rates inside one product: is Bank of America really more likely than
   Capital One to give money back? Phase 5 compared all products together, which
   mixes in product differences. Here we compare credit card complaints only, with
   a 95% Wilson interval for each bank and a two-proportion z-test for the gap.

Saves reports/stats/before_after_jan2025.csv and reports/stats/relief_credit_card.csv.

How to run it on the Mac (project folder, venv active)
    python src/stats/significance_tests.py
"""

import argparse
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.proportion import proportion_confint, proportions_ztest

import spikes

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "data" / "warehouse" / "complaints.duckdb"
STATS_DIR = PROJECT_ROOT / "reports" / "stats"
WINDOW_SQL = PROJECT_ROOT / "sql" / "analysis" / "_window.sql"
RELIEF_SQL = PROJECT_ROOT / "sql" / "stats" / "relief_by_company_product.sql"

SPIKE_START = pd.Timestamp("2025-01-13")      # first spike week (see jan2025_validation.csv)
WINDOW_WEEKS = 12
BEFORE_AFTER_SERIES = [
    "All non-bureau companies",
    "Money transfer",
    "Checking/savings",
    "Block, Inc.",
    "Early Warning Services, LLC",
    "NAVY FEDERAL CREDIT UNION",
    "CAPITAL ONE FINANCIAL CORPORATION",
]
CONTROL = "Control: non-bureau, excluding money transfer and checking/savings"

RELIEF_PRODUCT = "Credit card"
RELIEF_MIN_CLOSED = 1000
RELIEF_PAIR = ("BANK OF AMERICA, NATIONAL ASSOCIATION", "CAPITAL ONE FINANCIAL CORPORATION")


def ci_from_log(diff, se, dof, level=0.95):
    t = stats.t.ppf(0.5 + level / 2, dof)
    p = 2 * stats.t.sf(abs(diff / se), dof)
    return np.exp(diff), np.exp(diff - t * se), np.exp(diff + t * se), p


def before_after():
    scores = pd.read_csv(STATS_DIR / "weekly_scores.csv", parse_dates=["week_start"])
    episodes = pd.read_csv(STATS_DIR / "spike_episodes.csv", parse_dates=["first_week", "last_week"])
    counts = scores.pivot_table(index="week_start", columns="series", values="complaints")
    counts[CONTROL] = (counts["All non-bureau companies"]
                       - counts["Money transfer"] - counts["Checking/savings"])

    # The "after" window starts once every tested series is back below the spike
    # rule, plus one more quiet week.
    jan = episodes[(episodes["series"].isin(BEFORE_AFTER_SERIES))
                   & (episodes["first_week"] >= SPIKE_START)
                   & (episodes["first_week"] <= SPIKE_START + pd.Timedelta(weeks=2))]
    after_start = jan["last_week"].max() + pd.Timedelta(weeks=2)
    before_weeks = pd.date_range(end=SPIKE_START - pd.Timedelta(weeks=1), periods=WINDOW_WEEKS, freq="W-MON")
    after_weeks = pd.date_range(start=after_start, periods=WINDOW_WEEKS, freq="W-MON")

    def windows(name):
        return counts.loc[before_weeks, name].to_numpy(), counts.loc[after_weeks, name].to_numpy()

    cb, ca = windows(CONTROL)
    c_diff, c_se, c_dof = spikes.log_ratio_se(cb, ca)

    rows = []
    for name in BEFORE_AFTER_SERIES + [CONTROL]:
        b, a = windows(name)
        diff, se, dof = spikes.log_ratio_se(b, a)
        ratio, lo, hi, p = ci_from_log(diff, se, dof)
        row = {
            "series": name,
            "before_weeks": f"{before_weeks[0]:%Y-%m-%d} to {before_weeks[-1]:%Y-%m-%d}",
            "after_weeks": f"{after_weeks[0]:%Y-%m-%d} to {after_weeks[-1]:%Y-%m-%d}",
            "before_weekly_mean": round(b.mean()),
            "after_weekly_mean": round(a.mean()),
            "after_vs_before": round(ratio, 3),
            "ci95_low": round(lo, 3),
            "ci95_high": round(hi, 3),
            "p_value": p,
        }
        if name != CONTROL:
            # Ratio of ratios: how much more the series rose than the control did.
            # The two windows are independent of each other's noise only roughly
            # (the control and the series share the same calendar), so adding the
            # variances gives a slightly wider, more cautious interval.
            d_diff = diff - c_diff
            d_se = np.sqrt(se**2 + c_se**2)
            d_dof = min(dof, c_dof)
            rr, rlo, rhi, rp = ci_from_log(d_diff, d_se, d_dof)
            row.update({"vs_control": round(rr, 3), "vs_control_ci95_low": round(rlo, 3),
                        "vs_control_ci95_high": round(rhi, 3), "vs_control_p_value": rp})
        rows.append(row)
    out = pd.DataFrame(rows)
    out["p_value"] = out["p_value"].map(lambda v: float(f"{v:.3g}"))
    out["vs_control_p_value"] = out["vs_control_p_value"].map(
        lambda v: float(f"{v:.3g}") if pd.notna(v) else v)
    return out


def relief_credit_card(db_path):
    con = duckdb.connect(str(db_path), read_only=True)
    con.execute(WINDOW_SQL.read_text())
    window = con.sql("select current_start, last_month_end from analysis_window").df().iloc[0]
    df = con.sql(RELIEF_SQL.read_text()).df()
    con.close()

    all_products = df.groupby("company_name")[["closed", "monetary_relief"]].sum()
    card = df[df["product_group"] == RELIEF_PRODUCT].set_index("company_name")
    card = card[card["closed"] >= RELIEF_MIN_CLOSED].sort_values("closed", ascending=False)

    rows = []
    for company, r in card.iterrows():
        lo, hi = proportion_confint(r["monetary_relief"], r["closed"], alpha=0.05, method="wilson")
        a = all_products.loc[company]
        rows.append({
            "company_name": company,
            "period": f"{window.current_start:%Y-%m-%d} to {window.last_month_end:%Y-%m-%d}",
            "card_closed": int(r["closed"]),
            "card_relief": int(r["monetary_relief"]),
            "card_relief_pct": round(100 * r["monetary_relief"] / r["closed"], 2),
            "card_ci95_low_pct": round(100 * lo, 2),
            "card_ci95_high_pct": round(100 * hi, 2),
            "card_share_of_company_closed_pct": round(100 * r["closed"] / a["closed"], 1),
            "all_products_relief_pct": round(100 * a["monetary_relief"] / a["closed"], 2),
        })
    out = pd.DataFrame(rows)

    first, second = (card.loc[c] for c in RELIEF_PAIR)
    z, p = proportions_ztest([first["monetary_relief"], second["monetary_relief"]],
                             [first["closed"], second["closed"]])
    gap = first["monetary_relief"] / first["closed"] - second["monetary_relief"] / second["closed"]
    se = np.sqrt(sum(r["monetary_relief"] / r["closed"] * (1 - r["monetary_relief"] / r["closed"]) / r["closed"]
                     for r in (first, second)))
    test = (f"{RELIEF_PAIR[0]} vs {RELIEF_PAIR[1]}, {RELIEF_PRODUCT}: gap {100 * gap:+.2f} points "
            f"(95% CI {100 * (gap - 1.96 * se):+.2f} to {100 * (gap + 1.96 * se):+.2f}), "
            f"z = {z:.1f}, p = {p:.2g}")
    return out, test


def main():
    parser = argparse.ArgumentParser(description="Before/after and relief-rate tests.")
    parser.add_argument("--db", default=str(DB_PATH), help="path to the DuckDB warehouse")
    args = parser.parse_args()
    if not (STATS_DIR / "weekly_scores.csv").exists():
        raise SystemExit("Run src/stats/run_spike_detection.py first.")
    if not Path(args.db).exists():
        raise SystemExit(f"No warehouse at {args.db}.")

    pd.set_option("display.width", 220)
    pd.set_option("display.max_columns", 20)

    ba = before_after()
    ba.to_csv(STATS_DIR / "before_after_jan2025.csv", index=False)
    print("== before_after_jan2025.csv")
    print(ba.drop(columns=["before_weeks", "after_weeks"]).to_string(index=False))
    print(f"   before: {ba.before_weeks[0]}, after: {ba.after_weeks[0]}\n")

    relief, test = relief_credit_card(args.db)
    relief.to_csv(STATS_DIR / "relief_credit_card.csv", index=False)
    print("== relief_credit_card.csv")
    print(relief.drop(columns=["period"]).to_string(index=False))
    print(f"\n{test}")


if __name__ == "__main__":
    main()
