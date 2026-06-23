#!/usr/bin/env python3
"""Plot root_key × distance effects (aggregating over betweenness centrality).

Uses the per-file CSV from analyze_betweenness_by_distance.py, groups by
target_top_level_key × nearest_same_top_key_distance, and generates:

  1. Heatmap   — rows = root_key, cols = distance, color = metric
  2. Bar-grid  — one subplot per root_key, X = distance
  3. Bar-all   — X = distance, hue = root_key, overlaid bars
"""

from __future__ import annotations

import argparse
import math
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

METRIC_COLUMNS = [
    "field_path_precision", "field_path_recall", "field_path_f1",
    "leaf_triple_precision", "leaf_triple_recall", "leaf_triple_f1",
    "value_accuracy", "hallucinated_rate", "missing_rate",
    "top_level_exact_match",
]

NUMERIC_COLS = METRIC_COLUMNS + ["evaluated_files"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _distance_sort_key(group: Any) -> Tuple[int, float]:
    if isinstance(group, float) and math.isinf(group):
        return (1, float("inf"))
    if isinstance(group, str) and group == "inf":
        return (1, float("inf"))
    if isinstance(group, (int, float, np.integer, np.floating)):
        val = float(group)
        if math.isinf(val):
            return (1, float("inf"))
        if math.isnan(val):
            return (2, 0.0)
        try:
            return (0, int(val))
        except (ValueError, OverflowError):
            return (0, val)
    group_str = str(group)
    if not group_str:
        return (2, 0.0)
    if group_str == "inf":
        return (1, float("inf"))
    try:
        return (0, int(group_str))
    except (ValueError, OverflowError):
        return (2, float("inf") if "inf" in group_str.lower() else 0.0)


def _sorted_distances(groups: Any) -> List[str]:
    return sorted(set(str(g) for g in groups), key=_distance_sort_key)


def _metric_label(metric: str) -> str:
    labels: Dict[str, str] = {
        "field_path_f1": "Field Path F1",
        "leaf_triple_f1": "Leaf Triple F1",
        "value_accuracy": "Value Accuracy",
        "top_level_exact_match": "Top-Level Exact Match",
        "field_path_precision": "Field Path Precision",
        "field_path_recall": "Field Path Recall",
        "leaf_triple_precision": "Leaf Triple Precision",
        "leaf_triple_recall": "Leaf Triple Recall",
        "hallucinated_rate": "Hallucinated Rate",
        "missing_rate": "Missing Rate",
    }
    return labels.get(metric, metric)


def _setup_chinese_font() -> None:
    for family in ("Noto Sans CJK SC", "WenQuanYi Micro Hei", "SimHei", "Microsoft YaHei"):
        for fpath in matplotlib.font_manager.findSystemFonts():
            if family.lower().replace(" ", "") in Path(fpath).name.lower().replace(" ", ""):
                matplotlib.font_manager.fontManager.addfont(fpath)
                plt.rcParams["font.family"] = \
                    matplotlib.font_manager.FontProperties(fname=fpath).get_name()
                return
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        plt.rcParams["font.family"] = "sans-serif"


def _safe_filename(text: str) -> str:
    return text.replace("/", "_").replace("\\", "_").replace("|", "_").replace(" ", "_")


def _close_fig(fig: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("  wrote %s" % path, flush=True)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_data(csv_path: Path, metric: str, split: Optional[str], task: Optional[str],
              min_files: int, root_keys: Optional[List[str]]) -> pd.DataFrame:
    df = pd.read_csv(csv_path)

    # Coerce numeric
    for col in NUMERIC_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Validate columns
    for col in ["split", "task", "target_top_level_key",
                "nearest_same_top_key_distance", "status"]:
        if col not in df.columns:
            raise ValueError(
                "CSV missing column '%s'. Expected per-file CSV from "
                "analyze_betweenness_by_distance.py." % col
            )

    if metric not in df.columns:
        raise ValueError("Metric '%s' not in CSV. Available: %s" % (metric, METRIC_COLUMNS))

    # Keep only successfully evaluated rows
    df = df[df["status"] == "ok"]

    # Drop rows missing distance info (multi-key answers etc.)
    df = df[df["nearest_same_top_key_distance"].notna()]
    df = df[df["nearest_same_top_key_distance"].astype(str).str.strip() != ""]

    # Filter
    if split:
        df = df[df["split"] == split]
    if task:
        df = df[df["task"] == task]
    if root_keys:
        df = df[df["target_top_level_key"].isin(root_keys)]

    if df.empty:
        raise ValueError("No rows after filtering.")

    # Group by root_key × distance, aggregate metric
    agg = df.groupby(["split", "task", "target_top_level_key",
                      "nearest_same_top_key_distance"])[metric].agg(
        mean="mean", count="count"
    ).reset_index()
    agg = agg[agg["count"] >= min_files]
    agg = agg.rename(columns={"mean": metric})

    if agg.empty:
        raise ValueError("No groups with >= %d files." % min_files)

    # Sort
    dist_order = _sorted_distances(agg["nearest_same_top_key_distance"].unique())
    rk_order = sorted(agg["target_top_level_key"].unique())
    agg["nearest_same_top_key_distance"] = pd.Categorical(
        agg["nearest_same_top_key_distance"], categories=dist_order, ordered=True
    )
    agg["target_top_level_key"] = pd.Categorical(
        agg["target_top_level_key"], categories=rk_order, ordered=False
    )
    return agg


# ---------------------------------------------------------------------------
# Plot 1: Heatmap  — rows = root_key, cols = distance
# ---------------------------------------------------------------------------

def plot_heatmap(agg: pd.DataFrame, metric: str, output_dir: Path) -> None:
    print("[heatmap] generating …", flush=True)
    pivot = agg.pivot_table(
        index="target_top_level_key",
        columns="nearest_same_top_key_distance",
        values=metric,
        aggfunc="mean",
    )
    pivot = pivot.dropna(how="all").dropna(axis=1, how="all")
    n_rows, n_cols = pivot.shape
    if n_rows < 1 or n_cols < 1:
        print("  skip: no data", flush=True)
        return

    cell_h, cell_w = 0.5, 0.7
    fig, ax = plt.subplots(figsize=(max(5, n_cols * cell_w + 2),
                                    max(4, n_rows * cell_h + 1.5)))
    annot = n_rows * n_cols <= 60
    vmin = pivot.min().min() if not pivot.isna().all().all() else 0.0
    vmax = pivot.max().max() if not pivot.isna().all().all() else 1.0
    sns.heatmap(
        pivot, annot=annot, fmt=".2f", cmap="YlOrRd",
        vmin=vmin, vmax=vmax, linewidths=0.5, linecolor="white",
        cbar_kws={"shrink": 0.8}, ax=ax,
    )
    ax.set_title("%s\nRoot Key × Distance  |  Heatmap" % _metric_label(metric), fontsize=13)
    ax.set_xlabel("Nearest Same-Top-Key Distance")
    ax.set_ylabel("Root Key")
    ax.tick_params(axis="y", labelsize=9)
    ax.tick_params(axis="x", labelsize=10)
    _close_fig(fig, output_dir / "heatmap" / ("rootkey_distance_%s.png" % metric))


# ---------------------------------------------------------------------------
# Plot 2: Bar-grid  — one subplot per root_key, X = distance
# ---------------------------------------------------------------------------

def plot_bar_grid(agg: pd.DataFrame, metric: str, output_dir: Path) -> None:
    print("[bar-grid] generating …", flush=True)
    root_key_list = sorted(agg["target_top_level_key"].unique())
    n = len(root_key_list)
    ncols = min(3, n)
    nrows = math.ceil(n / ncols)
    dist_order = _sorted_distances(agg["nearest_same_top_key_distance"].unique())

    fig, axes = plt.subplots(nrows, ncols, figsize=(5 * ncols, 4 * nrows),
                              squeeze=False, sharey=True)
    # Use a consistent color per root_key
    cmap = plt.colormaps.get_cmap("Set2")

    for ri, rk in enumerate(root_key_list):
        ax = axes[ri // ncols][ri % ncols]
        sub = agg[agg["target_top_level_key"] == rk]
        values = []
        labels = []
        for dist in dist_order:
            match = sub[sub["nearest_same_top_key_distance"] == dist]
            if not match.empty:
                values.append(match[metric].iloc[0])
                labels.append(dist)
            else:
                values.append(np.nan)
                labels.append(dist)

        x_pos = range(len(labels))
        bars = ax.bar(x_pos, values, color=cmap(ri % 8), width=0.7)
        # Annotate with sample count
        for xi, dist in enumerate(labels):
            match = sub[sub["nearest_same_top_key_distance"] == dist]
            cnt = match["count"].iloc[0] if not match.empty else 0
            if cnt:
                ax.text(xi, 0.02, "n=%d" % cnt, ha="center", va="bottom",
                        fontsize=7, color="#333333")

        ax.set_xticks(x_pos)
        ax.set_xticklabels(labels, fontsize=9)
        ax.set_title(rk[:35], fontsize=10)
        ax.set_ylim(0, 1.05)
        ax.grid(True, axis="y", alpha=0.3)

    for ri in range(n, nrows * ncols):
        axes[ri // ncols][ri % ncols].set_visible(False)

    fig.supylabel(_metric_label(metric), fontsize=13)
    fig.supxlabel("Nearest Same-Top-Key Distance", fontsize=13)
    fig.suptitle("%s  |  Bar Grid by Root Key" % _metric_label(metric), fontsize=14)
    fig.tight_layout(rect=[0, 0.04, 1, 0.95])
    _close_fig(fig, output_dir / "bar" / ("grid_%s.png" % metric))


# ---------------------------------------------------------------------------
# Plot 3: Bar-all  — X = distance, hue = root_key
# ---------------------------------------------------------------------------

def plot_bar_all(agg: pd.DataFrame, metric: str, output_dir: Path) -> None:
    print("[bar-all] generating …", flush=True)
    root_key_list = sorted(agg["target_top_level_key"].unique())
    dist_order = _sorted_distances(agg["nearest_same_top_key_distance"].unique())
    cmap = plt.colormaps.get_cmap("tab10")

    n_rk = len(root_key_list)
    n_dist = len(dist_order)
    if n_rk < 1 or n_dist < 1:
        print("  skip: no data", flush=True)
        return

    x_pos = np.arange(n_dist)
    bar_width = 0.8 / n_rk

    fig, ax = plt.subplots(figsize=(max(8, n_dist * 1.4), 5))

    for ri, rk in enumerate(root_key_list):
        sub = agg[agg["target_top_level_key"] == rk]
        values = []
        for dist in dist_order:
            match = sub[sub["nearest_same_top_key_distance"] == dist]
            values.append(match[metric].iloc[0] if not match.empty else np.nan)
        offset = (ri - (n_rk - 1) / 2) * bar_width
        ax.bar(x_pos + offset, values, bar_width * 0.9,
               color=cmap(ri % 10), label=rk[:30])

    ax.set_xticks(x_pos)
    ax.set_xticklabels(dist_order, fontsize=10)
    ax.set_ylabel(_metric_label(metric))
    ax.set_xlabel("Nearest Same-Top-Key Distance")
    ax.set_title("%s  |  Bar by Root Key" % _metric_label(metric), fontsize=13)
    ax.set_ylim(0, 1.05)
    ax.legend(title="Root Key", fontsize=8, title_fontsize=9,
              ncol=max(1, min(4, n_rk)))
    ax.grid(True, axis="y", alpha=0.3)
    _close_fig(fig, output_dir / "bar" / ("all_rootkeys_%s.png" % metric))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Plot root_key × distance effects from per-file CSV."
    )
    p.add_argument("csv", type=Path, nargs="?", default=None,
                   help="Path to per_file_betweenness_by_distance.csv. "
                        "Default: metric-results/betweenness-by-distance/per_file_betweenness_by_distance.csv")
    p.add_argument("--output-dir", type=Path, default=None,
                   help="Output directory for plots. Default: sibling of CSV / plots/.")
    p.add_argument("--metrics", default="field_path_f1,leaf_triple_f1,value_accuracy",
                   help="Comma-separated metric names. Default: field_path_f1,leaf_triple_f1,value_accuracy")
    p.add_argument("--root-key", action="append", default=None,
                   help="Filter to specific root key(s). Repeatable. Default: all.")
    p.add_argument("--split", default=None, help="Filter by split (e.g. val).")
    p.add_argument("--task", default=None, help="Filter by task (e.g. node_config_qa).")
    p.add_argument("--min-files", type=int, default=3,
                   help="Minimum samples per (root_key × distance) group. Default: 3.")
    p.add_argument("--plots", default="heatmap,bar-grid,bar-all",
                   help="Which plot types to generate. Default: heatmap,bar-grid,bar-all")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    _setup_chinese_font()
    matplotlib.use("Agg")

    csv_path = args.csv or Path(
        "metric-results/betweenness-by-distance/per_file_betweenness_by_distance.csv"
    )
    if not csv_path.exists():
        raise SystemExit("CSV not found: %s" % csv_path)

    output_dir = args.output_dir or csv_path.parent / "plots"
    metric_list = [m.strip() for m in args.metrics.split(",") if m.strip()]
    plot_set = {p.strip() for p in args.plots.split(",") if p.strip()}

    print("[plot-bd] source: %s" % csv_path, flush=True)
    print("[plot-bd] output: %s" % output_dir, flush=True)
    print("[plot-bd] metrics: %s" % metric_list, flush=True)
    print("[plot-bd] plots:   %s" % sorted(plot_set), flush=True)

    for metric in metric_list:
        print("--- %s ---" % metric, flush=True)
        agg = load_data(csv_path, metric, args.split, args.task,
                        args.min_files, args.root_key)
        print("  groups after filter: %d" % len(agg), flush=True)

        if "heatmap" in plot_set:
            plot_heatmap(agg, metric, output_dir)
        if "bar-grid" in plot_set:
            plot_bar_grid(agg, metric, output_dir)
        if "bar-all" in plot_set:
            plot_bar_all(agg, metric, output_dir)

    print("[plot-bd] done.", flush=True)


if __name__ == "__main__":
    main()
