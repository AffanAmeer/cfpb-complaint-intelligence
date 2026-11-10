"""
Draw the README charts from the KPI CSVs in reports/kpis/.

Run run_kpis.py first, then:
    python src/analysis/plot_findings.py

Saves PNGs to reports/figures/. The charts only read the CSVs, so every
number on them is the same as in the findings doc.
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.ticker import FuncFormatter

PROJECT_ROOT = Path(__file__).resolve().parents[2]
KPI_DIR = PROJECT_ROOT / "reports" / "kpis"
FIG_DIR = PROJECT_ROOT / "reports" / "figures"

SURFACE = "#fcfcfb"
TEXT = "#0b0b0b"
TEXT_2 = "#52514e"
GRID = "#e4e3df"
BLUE_LIGHT = "#86b6ef"
BLUE = "#2a78d6"
BLUE_DARK = "#184f95"


def style(ax):
    ax.set_facecolor(SURFACE)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(TEXT_2)
    ax.tick_params(colors=TEXT_2, labelsize=9, length=0)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def thousands(x, _):
    return f"{x / 1000:,.0f}k"


def monthly_trend():
    df = pd.read_csv(KPI_DIR / "02_monthly_trend.csv", parse_dates=["month_start"])
    df = df[(df.month_start >= "2023-01-01") & (df.month_start <= "2026-09-01")]

    fig, ax = plt.subplots(figsize=(9, 4.2), facecolor=SURFACE)
    style(ax)
    ax.plot(df.month_start, df.complaints_other, color=BLUE_LIGHT, linewidth=1.5,
            marker="o", markersize=3, label="Each month")
    ax.plot(df.month_start, df.other_rolling_3m_avg, color=BLUE_DARK, linewidth=2.2,
            label="3-month average")

    jan = df[df.month_start == "2025-01-01"].iloc[0]
    ax.annotate(f"Jan 2025: {jan.complaints_other:,.0f}\n(one-off jump, mostly Block, Inc.)",
                xy=(jan.month_start, jan.complaints_other),
                xytext=(jan.month_start - pd.Timedelta(days=420), jan.complaints_other - 10000),
                fontsize=8.5, color=TEXT_2,
                arrowprops=dict(arrowstyle="-", color=TEXT_2, linewidth=0.8))

    peak = df.loc[df.other_rolling_3m_avg.idxmax()]
    last = df.iloc[-1]
    ax.annotate(f"Average peaked at {peak.other_rolling_3m_avg:,.0f}\n({peak.month_start:%b %Y})",
                xy=(peak.month_start, peak.other_rolling_3m_avg),
                xytext=(peak.month_start - pd.Timedelta(days=300), peak.other_rolling_3m_avg + 22000),
                fontsize=8.5, color=TEXT_2,
                arrowprops=dict(arrowstyle="-", color=TEXT_2, linewidth=0.8))
    ax.annotate(f"{last.other_rolling_3m_avg:,.0f}\n({last.month_start:%b %Y})",
                xy=(last.month_start, last.other_rolling_3m_avg),
                xytext=(last.month_start + pd.Timedelta(days=12), last.other_rolling_3m_avg - 14000),
                fontsize=8.5, color=TEXT_2)

    ax.yaxis.set_major_formatter(FuncFormatter(thousands))
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.set_ylim(0, None)
    ax.set_xlim(df.month_start.min() - pd.Timedelta(days=20), df.month_start.max() + pd.Timedelta(days=110))
    ax.legend(frameon=False, fontsize=9, labelcolor=TEXT_2, loc="upper left")
    fig.suptitle("Complaints about companies other than the credit bureaus, per month",
                 x=0.06, ha="left", fontsize=12, color=TEXT, fontweight="bold")
    ax.set_title("The 3-month average has fallen since March 2026. Complete months only, Jan 2023 to Sep 2026.",
                 loc="left", fontsize=9, color=TEXT_2)
    fig.text(0.06, 0.01, "Source: CFPB Consumer Complaint Database. reports/kpis/02_monthly_trend.csv", fontsize=7.5, color=TEXT_2)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(FIG_DIR / "non_bureau_monthly_trend.png", dpi=200, facecolor=SURFACE)
    plt.close(fig)


def product_yoy():
    df = pd.read_csv(KPI_DIR / "03_product_yoy.csv")
    df = df.sort_values("other_current").tail(7)
    names = {
        "Credit reporting or other personal consumer reports": "Credit reporting",
        "Checking or savings account": "Checking or savings",
        "Money transfer, virtual currency, or money service": "Money transfer",
        "Payday loan, title loan, personal loan, or advance loan": "Payday / personal loan",
        "Vehicle loan or lease": "Vehicle loan",
    }
    labels = [names.get(p, p) for p in df.product_group]

    fig, ax = plt.subplots(figsize=(9, 4.4), facecolor=SURFACE)
    style(ax)
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    y = range(len(df))
    h = 0.38
    ax.barh([i + h / 2 + 0.02 for i in y], df.other_prior, height=h, color=BLUE_LIGHT,
            label="Oct 2024 to Sep 2025")
    ax.barh([i - h / 2 - 0.02 for i in y], df.other_current, height=h, color=BLUE,
            label="Oct 2025 to Sep 2026")
    for i, (cur, yoy) in enumerate(zip(df.other_current, df.other_yoy_pct)):
        ax.text(cur + 3000, i - h / 2 - 0.02, f"{cur:,.0f} ({yoy:+.1f}%)", va="center",
                fontsize=8.5, color=TEXT)
    ax.set_yticks(list(y))
    ax.set_yticklabels(labels, fontsize=9, color=TEXT)
    ax.xaxis.set_major_formatter(FuncFormatter(thousands))
    ax.set_xlim(0, df.other_current.max() * 1.3)
    ax.spines["bottom"].set_visible(False)
    handles, leg_labels = ax.get_legend_handles_labels()
    ax.legend(handles[::-1], leg_labels[::-1], frameon=False, fontsize=9,
              labelcolor=TEXT_2, loc="lower right")
    fig.suptitle("Debt collection is now the biggest product outside the credit bureaus",
                 x=0.03, ha="left", fontsize=12, color=TEXT, fontweight="bold")
    ax.set_title("Complaints about non-bureau companies by product, last 12 complete months vs the 12 before. "
                 "Top 7 products.", loc="left", fontsize=9, color=TEXT_2)
    fig.text(0.03, 0.01, "Source: CFPB Consumer Complaint Database. reports/kpis/03_product_yoy.csv. "
             "Money transfer fell because Jan 2025 had a one-off jump.", fontsize=7.5, color=TEXT_2)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(FIG_DIR / "non_bureau_products_yoy.png", dpi=200, facecolor=SURFACE)
    plt.close(fig)


def main():
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    monthly_trend()
    product_yoy()
    print(f"Saved charts to {FIG_DIR.relative_to(PROJECT_ROOT)}/")


if __name__ == "__main__":
    main()
