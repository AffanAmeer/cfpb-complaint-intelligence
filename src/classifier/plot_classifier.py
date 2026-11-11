"""
Draw the classifier charts from the CSVs in reports/classifier/.

Run train_classifier.py first, then:
    python src/classifier/plot_classifier.py

Saves PNGs to reports/figures/. The charts only read the CSVs, so every number on
them matches the docs.
"""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RESULTS_DIR = PROJECT_ROOT / "reports" / "classifier"
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


def confusion(summary):
    cm = pd.read_csv(RESULTS_DIR / "confusion_matrix.csv", index_col=0)
    # Each row as a share of that product's real complaints: the diagonal is recall.
    shares = cm.div(cm.sum(axis=1), axis=0)
    labels = list(cm.index)

    cmap = LinearSegmentedColormap.from_list("blues", [SURFACE, BLUE_LIGHT, BLUE, BLUE_DARK])
    fig, ax = plt.subplots(figsize=(8.6, 7.4), facecolor=SURFACE)
    ax.set_facecolor(SURFACE)
    ax.imshow(shares.values, cmap=cmap, vmin=0, vmax=1)
    for i in range(len(labels)):
        for j in range(len(labels)):
            v = shares.values[i, j]
            if v >= 0.005:
                ax.text(j, i, f"{v:.0%}", ha="center", va="center", fontsize=7.5,
                        color=SURFACE if v > 0.5 else TEXT)
    ax.set_xticks(range(len(labels)), labels, rotation=40, ha="right", fontsize=8.5, color=TEXT_2)
    ax.set_yticks(range(len(labels)), [f"{l} ({n:,})" for l, n in zip(labels, cm.sum(axis=1))],
                  fontsize=8.5, color=TEXT_2)
    ax.set_xlabel("Predicted product group", color=TEXT_2, fontsize=9)
    ax.set_ylabel("Actual product group (test complaints)", color=TEXT_2, fontsize=9)
    ax.tick_params(length=0)
    for side in ax.spines.values():
        side.set_visible(False)
    fig.suptitle("Where the classifier gets it right, and what it confuses",
                 x=0.03, ha="left", fontsize=12, color=TEXT, fontweight="bold")
    fig.text(0.03, 0.935, f"Each row adds to 100%. The diagonal is recall. Test set: "
             f"{summary['test_rows']:,} complaints from {summary['test_period']}, never seen in training.",
             fontsize=8.5, color=TEXT_2)
    fig.text(0.03, 0.01, "Source: CFPB Narratives Archive. reports/classifier/confusion_matrix.csv",
             fontsize=7.5, color=TEXT_2)
    fig.tight_layout(rect=(0, 0.02, 1, 0.93))
    fig.savefig(FIG_DIR / "classifier_confusion_matrix.png", dpi=200, facecolor=SURFACE)
    plt.close(fig)


def routing():
    r = pd.read_csv(RESULTS_DIR / "confidence_routing.csv")
    r = r[r.min_confidence > 0]
    x = np.arange(len(r))

    fig, ax = plt.subplots(figsize=(8.6, 4.2), facecolor=SURFACE)
    style(ax)
    w = 0.38
    ax.bar(x - w / 2, r.share_auto_routed, width=w, color=BLUE_LIGHT, label="Share of complaints auto-routed")
    ax.bar(x + w / 2, r.accuracy_auto_routed, width=w, color=BLUE_DARK, label="Accuracy on the auto-routed ones")
    for xi, s, a in zip(x, r.share_auto_routed, r.accuracy_auto_routed):
        ax.text(xi - w / 2, s + 0.015, f"{s:.0%}", ha="center", fontsize=8, color=TEXT_2)
        ax.text(xi + w / 2, a + 0.015, f"{a:.0%}", ha="center", fontsize=8, color=TEXT)
    ax.set_xticks(x, [f"{t:.0%}" for t in r.min_confidence])
    ax.set_xlabel("Only auto-route when the model is at least this confident", color=TEXT_2, fontsize=9)
    ax.set_ylim(0, 1.12)
    ax.set_yticks([0, 0.25, 0.5, 0.75, 1.0], ["0%", "25%", "50%", "75%", "100%"])
    ax.legend(frameon=False, fontsize=8.5, labelcolor=TEXT_2, loc="upper left", ncols=2)
    fig.suptitle("Trading coverage for accuracy: let the model route the easy ones",
                 x=0.06, ha="left", fontsize=12, color=TEXT, fontweight="bold")
    ax.set_title("Complaints below the threshold go to a person. Test set only.",
                 loc="left", fontsize=8.5, color=TEXT_2)
    fig.text(0.06, 0.01, "Source: CFPB Narratives Archive. reports/classifier/confidence_routing.csv",
             fontsize=7.5, color=TEXT_2)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(FIG_DIR / "classifier_confidence_routing.png", dpi=200, facecolor=SURFACE)
    plt.close(fig)


def main():
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    summary = json.loads((RESULTS_DIR / "run_summary.json").read_text())
    confusion(summary)
    routing()
    print(f"Saved charts to {FIG_DIR.relative_to(PROJECT_ROOT)}/")


if __name__ == "__main__":
    main()
