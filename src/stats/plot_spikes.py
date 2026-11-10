"""
Draw the spike-detection charts from the CSVs in reports/stats/.

Run run_spike_detection.py first, then:
    python src/stats/plot_spikes.py

Saves PNGs to reports/figures/. The charts only read the CSVs, so every number on
them matches the docs.
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.ticker import FuncFormatter

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATS_DIR = PROJECT_ROOT / "reports" / "stats"
FIG_DIR = PROJECT_ROOT / "reports" / "figures"

SURFACE = "#fcfcfb"
TEXT = "#0b0b0b"
TEXT_2 = "#52514e"
GRID = "#e4e3df"
BLUE_LIGHT = "#86b6ef"
BLUE = "#2a78d6"
BLUE_DARK = "#184f95"
ORANGE = "#eb6834"


def style(ax):
    ax.set_facecolor(SURFACE)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(TEXT_2)
    ax.tick_params(colors=TEXT_2, labelsize=9, length=0)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def weekly_with_spikes(scores):
    s = scores[(scores.series == "All non-bureau companies") & (scores.week_start >= "2022-01-03")]
    spikes = s[s.is_spike]

    fig, ax = plt.subplots(figsize=(9, 4.2), facecolor=SURFACE)
    style(ax)
    ax.plot(s.week_start, s.complaints, color=BLUE, linewidth=1.5, label="Complaints each week")
    ax.plot(s.week_start, s.baseline, color=BLUE_DARK, linewidth=1.2, linestyle="--",
            label="Baseline (median of the previous 12 weeks)")
    ax.scatter(spikes.week_start, spikes.complaints, s=40, color=ORANGE, zorder=3,
               edgecolor=SURFACE, linewidth=2, label="Flagged as a spike")

    top = spikes.loc[spikes.complaints.idxmax()]
    ax.annotate(f"Week of {top.week_start:%b %d, %Y}: {top.complaints:,.0f}\n"
                f"vs a baseline of {top.baseline:,.0f} (z = {top.z:.0f})\n"
                "Mostly Cash App (Block) and Zelle (Early Warning)",
                xy=(top.week_start, top.complaints),
                xytext=(top.week_start + pd.Timedelta(days=60), top.complaints - 22000),
                fontsize=8.5, color=TEXT_2,
                arrowprops=dict(arrowstyle="-", color=TEXT_2, linewidth=0.8))
    wf = spikes[spikes.week_start == "2023-01-16"].iloc[0]
    ax.annotate(f"Jan 2023: {wf.complaints:,.0f}\n(mostly Wells Fargo)",
                xy=(wf.week_start, wf.complaints),
                xytext=(wf.week_start - pd.Timedelta(days=200), wf.complaints + 13000),
                fontsize=8.5, color=TEXT_2,
                arrowprops=dict(arrowstyle="-", color=TEXT_2, linewidth=0.8))

    ax.yaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{x / 1000:,.0f}k"))
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.set_ylim(0, None)
    ax.legend(frameon=False, fontsize=8.5, labelcolor=TEXT_2, loc="upper left")
    fig.suptitle("Weekly complaints about companies other than the credit bureaus",
                 x=0.06, ha="left", fontsize=12, color=TEXT, fontweight="bold")
    ax.set_title("Orange weeks pass all three spike rules (robust z >= 4, at least 1.5x baseline, "
                 "at least 100 extra). Complete weeks, Jan 2022 to Sep 2026.",
                 loc="left", fontsize=8.5, color=TEXT_2)
    fig.text(0.06, 0.01, "Source: CFPB Consumer Complaint Database. reports/stats/weekly_scores.csv",
             fontsize=7.5, color=TEXT_2)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(FIG_DIR / "spikes_non_bureau_weekly.png", dpi=200, facecolor=SURFACE)
    plt.close(fig)


def masking(scores):
    s = scores[(scores.series == "Money transfer")
               & (scores.week_start >= "2024-12-16") & (scores.week_start <= "2025-03-03")]
    cap = 60

    fig, axes = plt.subplots(1, 2, figsize=(9, 3.8), facecolor=SURFACE, sharey=True)
    panels = [("plain_z", "Mean and standard deviation", BLUE_LIGHT),
              ("z", "Median and MAD (used here)", BLUE)]
    for ax, (col, title, color) in zip(axes, panels):
        style(ax)
        values = s[col].clip(upper=cap)
        ax.bar(s.week_start, values, width=5, color=color)
        for week, raw in zip(s.week_start, s[col]):
            if raw > cap:
                ax.text(week, cap + 1.5, f"{raw:,.0f}", ha="center", fontsize=8, color=TEXT)
        ax.axhline(4, color=ORANGE, linewidth=1.2)
        ax.text(s.week_start.iloc[-1], 6, "threshold z = 4", ha="right", fontsize=8, color=TEXT_2)
        ax.set_title(title, loc="left", fontsize=10, color=TEXT)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
        ax.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=0, interval=3))
        ax.set_ylim(-3, cap + 8)
    axes[0].set_ylabel("z-score", color=TEXT_2, fontsize=9)
    fig.suptitle("Why the baseline uses the median: money transfer complaints, winter 2024-25",
                 x=0.06, ha="left", fontsize=12, color=TEXT, fontweight="bold")
    fig.text(0.06, 0.86, "With a mean and standard deviation, the Jan 13 week inflates the baseline, "
             "so the next four weeks (still 4x to 28x normal) score below the threshold.",
             fontsize=8.5, color=TEXT_2)
    fig.text(0.06, 0.01, "Bars over 60 are cut off and labelled. Source: reports/stats/weekly_scores.csv",
             fontsize=7.5, color=TEXT_2)
    fig.tight_layout(rect=(0, 0.03, 1, 0.86))
    fig.savefig(FIG_DIR / "spikes_masking_money_transfer.png", dpi=200, facecolor=SURFACE)
    plt.close(fig)


def main():
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    scores = pd.read_csv(STATS_DIR / "weekly_scores.csv", parse_dates=["week_start"])
    weekly_with_spikes(scores)
    masking(scores)
    print(f"Saved charts to {FIG_DIR.relative_to(PROJECT_ROOT)}/")


if __name__ == "__main__":
    main()
