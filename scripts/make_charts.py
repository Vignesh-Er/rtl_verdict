"""scripts/make_charts.py - 4 figures for results/silent_bugs.md and
results/equivalent_mutant_rate.md, read entirely from corpus_stats.json.
matplotlib only. Emits .svg and .png (2x) into results/figures/. Fully
regenerable: `python scripts/make_charts.py`.

No 3D, no gradients, no drop shadows. Every axis labeled with units. Every
figure's caption (printed alongside, and embeddable under the image) states
n. Verdict colors come from chart_palette.py - the same module the later
static dashboard (Phase 5) will import, so colors never drift between the
two surfaces.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt

matplotlib.use("Agg")

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from chart_palette import CATEGORICAL, CHROME, VERDICT_COLORS, VERDICT_ORDER  # noqa: E402

FIGURES_DIR = REPO_ROOT / "results" / "figures"

plt.rcParams.update({
    "font.family": "sans-serif",
    "axes.edgecolor": CHROME["baseline"],
    "axes.labelcolor": CHROME["secondary_ink"],
    "text.color": CHROME["primary_ink"],
    "xtick.color": CHROME["secondary_ink"],
    "ytick.color": CHROME["secondary_ink"],
    "axes.grid": True,
    "grid.color": CHROME["gridline"],
    "grid.linewidth": 0.8,
    "figure.facecolor": CHROME["surface"],
    "axes.facecolor": CHROME["surface"],
    "savefig.facecolor": CHROME["surface"],
})


def _save(fig, name: str) -> None:
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    svg_path = FIGURES_DIR / f"{name}.svg"
    png_path = FIGURES_DIR / f"{name}.png"
    fig.savefig(svg_path, bbox_inches="tight")
    fig.savefig(png_path, bbox_inches="tight", dpi=192)  # 2x of a typical 96dpi baseline
    plt.close(fig)
    print(f"  wrote {svg_path.relative_to(REPO_ROOT)} + {png_path.relative_to(REPO_ROOT)}")


def fig1_verdict_composition(stats: dict) -> None:
    """Stacked bar: verdict composition per design, n on each bar."""
    designs = stats["designs"]
    names = [d["name"] for d in designs]
    fig, ax = plt.subplots(figsize=(7, 4.5))

    bottoms = [0.0] * len(designs)
    for verdict in VERDICT_ORDER:
        counts = [d["verdicts"].get(verdict, 0) for d in designs]
        bars = ax.bar(names, counts, bottom=bottoms, color=VERDICT_COLORS[verdict], label=verdict, width=0.6)
        for bar, count, bottom in zip(bars, counts, bottoms):
            if count > 0:
                ax.text(
                    bar.get_x() + bar.get_width() / 2, bottom + count / 2, str(count),
                    ha="center", va="center", fontsize=9,
                    color="white" if verdict in ("KEEP", "SILENT") else CHROME["primary_ink"],
                )
        bottoms = [b + c for b, c in zip(bottoms, counts)]

    ax.set_ylim(0, max(bottoms) * 1.18)  # headroom so the n= labels never collide with the title
    for i, d in enumerate(designs):
        ax.text(i, d["recorded"] + max(bottoms) * 0.03, f"n={d['recorded']}", ha="center", va="bottom", fontsize=9, color=CHROME["secondary_ink"])

    ax.set_ylabel("mutant count")
    ax.set_title("Verdict composition per design")
    ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1.0), frameon=False, fontsize=9)
    ax.spines[["top", "right"]].set_visible(False)
    fig.text(0.01, -0.02, f"n = {stats['corpus_totals']['recorded']} total generated tasks across {len(designs)} designs.", fontsize=8, color=CHROME["muted_ink"])
    _save(fig, "fig1_verdict_composition")


def fig2_silent_vs_coverage(stats: dict) -> None:
    """Silent % per design as bars, DUT-only toggle coverage as overlaid
    points - both on ONE shared 0-100% axis (not a dual-axis chart; see
    results/silent_bugs.md §5 - the two designs' toggle-point denominators
    span 9.4x, so this is deliberately NOT presented as a correlation claim,
    just two same-unit measurements placed at comparable height). Every
    bar/point is direct-labeled with its own count/denominator so the reader
    is never dependent on reading the axis precisely or inferring precision
    that isn't there.
    """
    sbr = stats["silent_bug_rate"]
    cov_by_design = {c["design"]: c["toggle"] for c in stats["coverage"]}
    per_design = sbr["per_design"]
    names = [d["design"] for d in per_design]
    silent_pct = [d["rate_pct"] for d in per_design]
    cov_pct = [round(100.0 * cov_by_design[d["design"]]["hit"] / cov_by_design[d["design"]]["total"], 1) for d in per_design]

    fig, ax = plt.subplots(figsize=(7.2, 5.0))

    bars = ax.bar(names, silent_pct, color=VERDICT_COLORS["SILENT"], width=0.5, label="silent-bug rate (%)", zorder=2)
    for bar, pct, d in zip(bars, silent_pct, per_design):
        ax.text(bar.get_x() + bar.get_width() / 2, pct - 3, f"{pct}%\n(n={d['n']})", ha="center", va="top", fontsize=8.5, color="white", zorder=4)

    ax.scatter(names, cov_pct, color=CATEGORICAL["series_1"], s=110, zorder=5, edgecolors=CHROME["surface"], linewidths=1.2, label="DUT-only toggle coverage (%)")
    for x, pct, d in zip(names, cov_pct, per_design):
        cov = cov_by_design[d["design"]]
        # place above if the point sits clear of its own bar top, else below -
        # keeps the coverage label from overlapping the silent-rate label
        # inside the bar (checked by rendering and looking - see caption).
        above = pct > d["rate_pct"] - 8
        ax.annotate(
            f"{pct}% ({cov['hit']}/{cov['total']})", (x, pct),
            textcoords="offset points", xytext=(0, 10 if above else -16),
            ha="center", fontsize=8.5, color=CATEGORICAL["series_1"], zorder=6,
        )

    ax.set_ylim(0, 108)
    ax.set_ylabel("percent (0-100%, one shared axis for both series)")
    ax.set_title("Silent-bug rate vs. DUT-only toggle coverage, per design")
    ax.legend(loc="upper left", frameon=False, fontsize=9)
    ax.spines[["top", "right"]].set_visible(False)
    fig.text(
        0.01, -0.04,
        f"n = {sbr['denominator']} real bugs (KEEP+SILENT) across {len(per_design)} designs, n=18-25 per design. "
        f"Toggle-point denominators span 9.4x (20-188) across designs - not a like-for-like comparison. "
        f"See results/silent_bugs.md §5/§5.1 - suggestive pattern only (exact permutation p=0.083, n=4), not a correlation claim.",
        fontsize=7.5, color=CHROME["muted_ink"], wrap=True,
    )
    _save(fig, "fig2_silent_rate_vs_coverage")


def fig3_equivalence_by_operator(stats: dict) -> None:
    """Equivalence rate per operator, sorted descending, n annotated per bar."""
    ops = [op for op in stats["operators"] if op["equivalent_rate_pct"] is not None]
    ops = sorted(ops, key=lambda o: o["equivalent_rate_pct"], reverse=True)
    names = [o["name"] for o in ops]
    rates = [o["equivalent_rate_pct"] for o in ops]
    ns = [o["evaluated_n"] for o in ops]

    fig, ax = plt.subplots(figsize=(7.5, 5.4))
    bars = ax.bar(names, rates, color=VERDICT_COLORS["QUARANTINE"], width=0.6)
    for bar, rate, n in zip(bars, rates, ns):
        marker = "" if n >= 30 else " *"
        ax.text(bar.get_x() + bar.get_width() / 2, rate + 4, f"{rate}%\nn={n}{marker}", ha="center", va="bottom", fontsize=8.5)

    ax.set_ylabel("equivalent-mutant rate (%)")
    ax.set_ylim(0, 122)  # headroom for the 100% bar's 2-line label, clear of the title
    ax.set_title("Equivalent-mutant rate by operator (QUARANTINE / evaluated)")
    ax.set_xticks(range(len(names)))
    ax.set_xticklabels(names, rotation=30, ha="right")
    ax.spines[["top", "right"]].set_visible(False)
    fig.subplots_adjust(bottom=0.32)  # room for the rotated tick labels, clear of the caption below
    fig.text(0.01, 0.01, "* n<30 - raw counts only, not a stable rate. n = evaluated candidates (generated minus ERROR).", fontsize=8, color=CHROME["muted_ink"])
    _save(fig, "fig3_equivalence_by_operator")


def fig4_divergence_depth_histogram(stats: dict) -> None:
    """Divergence-depth histogram for KEEP tasks."""
    hist = stats["divergence_depth_histogram_keep"]
    buckets = list(hist["buckets"].keys())
    counts = list(hist["buckets"].values())

    fig, ax = plt.subplots(figsize=(6.5, 4.2))
    bars = ax.bar(buckets, counts, color=CATEGORICAL["series_1"], width=0.6)
    for bar, count in zip(bars, counts):
        if count > 0:
            ax.text(bar.get_x() + bar.get_width() / 2, count + 0.5, str(count), ha="center", va="bottom", fontsize=9)

    ax.set_xlabel("divergence cycle (bucketed)")
    ax.set_ylabel("KEEP task count")
    ax.set_title("Divergence depth for KEEP tasks (formal counterexample cycle)")
    ax.spines[["top", "right"]].set_visible(False)
    fig.text(0.01, -0.02, f"n = {hist['n']} KEEP tasks with a recorded divergence_cycle.", fontsize=8, color=CHROME["muted_ink"])
    _save(fig, "fig4_divergence_depth_histogram")


def main() -> None:
    stats_path = REPO_ROOT / "results" / "corpus_stats.json"
    if not stats_path.exists():
        raise SystemExit(f"{stats_path} not found - run scripts/build_stats.py first")
    stats = json.loads(stats_path.read_text())

    print("Generating charts from results/corpus_stats.json...")
    fig1_verdict_composition(stats)
    fig2_silent_vs_coverage(stats)
    fig3_equivalence_by_operator(stats)
    fig4_divergence_depth_histogram(stats)
    print(f"done - {FIGURES_DIR.relative_to(REPO_ROOT)}/")


if __name__ == "__main__":
    main()
