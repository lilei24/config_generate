#!/usr/bin/env python3
"""Plot distance-group × root_key effects from analyze_distance_by_root_key.py output.

Reads the grouped CSV directly. Three plot types:
  1. Heatmap   — rows = root_key, cols = distance group, color = metric
  2. Bar-grid  — one subplot per root_key, X = distance group, n= annotations
  3. Bar-all   — X = distance group, hue = root_key, overlaid bars
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

NUMERIC_COLS = METRIC_COLUMNS + [
    "total_files", "evaluated_files", "model_error_files", "eval_error_files",
    "error_rate",
]


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


def _close_fig(fig: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("  wrote %s" % path, flush=True)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

REQUIRED_COLUMNS = [
    "split", "task", "nearest_same_top_key_group", "target_top_level_key",
    "evaluated_files",
]


def load_data(csv_path: Path, metric: str, split: Optional[str], task: Optional[str],
              min_files: int, root_keys: Optional[List[str]]) -> pd.DataFrame:
    df = pd.read_csv(csv_path)

    n_raw = len(df)
    print("  raw rows: %d" % n_raw, flush=True)

    for col in NUMERIC_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(
            "CSV missing columns: %s\nAvailable: %s\n"
            "Expected grouped CSV from analyze_distance_by_root_key.py."
            % (missing, list(df.columns))
        )

    if metric not in df.columns:
        raise ValueError("Metric '%s' not found. Available: %s" % (metric, METRIC_COLUMNS))

    # Drop rows where metric is missing (empty string → NaN after coercion)
    before = len(df)
    df = df.dropna(subset=[metric])
    print("  after dropna(%s): %d (dropped %d)" % (metric, len(df), before - len(df)), flush=True)

    # Filter out groups with too few evaluated samples
    before = len(df)
    df = df[df["evaluated_files"] >= min_files]
    print("  after min-files>=%d: %d (dropped %d)" % (min_files, len(df), before - len(df)), flush=True)

    # Drop rows without distance group (multi-key answers, non-object answers)
    before = len(df)
    df = df[df["nearest_same_top_key_group"].notna()]
    df = df[df["nearest_same_top_key_group"].astype(str).str.strip() != ""]
    print("  after non-empty distance group: %d (dropped %d)" % (len(df), before - len(df)), flush=True)

    if split:
        df = df[df["split"] == split]
    if task:
        df = df[df["task"] == task]
    if root_keys:
        df = df[df["target_top_level_key"].isin(root_keys)]

    if df.empty:
        raise ValueError("No rows after filtering. Try lowering --min-files.")
    print("  unique root_keys: %d, unique distance_groups: %s" % (
        df["target_top_level_key"].nunique(),
        sorted(df["nearest_same_top_key_group"].dropna().unique()),
    ), flush=True)

    # Sort order
    dist_order = _sorted_distances(df["nearest_same_top_key_group"].unique())
    rk_order = sorted(df["target_top_level_key"].unique())

    df["nearest_same_top_key_group"] = pd.Categorical(
        df["nearest_same_top_key_group"], categories=dist_order, ordered=True
    )
    df["target_top_level_key"] = pd.Categorical(
        df["target_top_level_key"], categories=rk_order, ordered=False
    )
    return df


# ---------------------------------------------------------------------------
# Plot 1: Heatmap  — rows = root_key, cols = distance group
# ---------------------------------------------------------------------------

def plot_heatmap(df: pd.DataFrame, metric: str, output_dir: Path) -> None:
    print("[heatmap] generating …", flush=True)
    pivot = df.pivot_table(
        index="target_top_level_key",
        columns="nearest_same_top_key_group",
        values=metric,
        aggfunc="mean",
    )
    print("  pivot shape: %s" % (pivot.shape,), flush=True)
    pivot = pivot.dropna(how="all").dropna(axis=1, how="all")
    print("  after dropna: %s" % (pivot.shape,), flush=True)
    n_rows, n_cols = pivot.shape
    if n_rows < 1 or n_cols < 1:
        print("  skip: no data after pivot+dropna", flush=True)
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
    ax.set_title("%s\nRoot Key × Distance Group  |  Heatmap" % _metric_label(metric), fontsize=13)
    ax.set_xlabel("Nearest Same-Top-Key Distance Group")
    ax.set_ylabel("Root Key")
    ax.tick_params(axis="y", labelsize=9)
    ax.tick_params(axis="x", labelsize=10)
    _close_fig(fig, output_dir / "heatmap" / ("rootkey_distance_%s.png" % metric))


# ---------------------------------------------------------------------------
# Plot 2: Bar-grid  — one subplot per root_key, X = distance group
# ---------------------------------------------------------------------------

def plot_bar_grid(df: pd.DataFrame, metric: str, output_dir: Path) -> None:
    print("[bar-grid] generating …", flush=True)
    print("  input rows: %d, root_keys: %d, dist_groups: %d" % (
        len(df), df["target_top_level_key"].nunique(),
        df["nearest_same_top_key_group"].nunique(),
    ), flush=True)
    root_key_list = sorted(df["target_top_level_key"].unique())
    n = len(root_key_list)
    ncols = min(3, n)
    nrows = math.ceil(n / ncols)
    dist_order = _sorted_distances(df["nearest_same_top_key_group"].unique())
    cmap = plt.colormaps.get_cmap("Set2")

    fig, axes = plt.subplots(nrows, ncols, figsize=(5 * ncols, 4 * nrows),
                              squeeze=False, sharey=True)

    for ri, rk in enumerate(root_key_list):
        ax = axes[ri // ncols][ri % ncols]
        sub = df[df["target_top_level_key"] == rk]
        values = []
        labels = []
        counts = []
        for dist in dist_order:
            match = sub[sub["nearest_same_top_key_group"] == dist]
            if not match.empty:
                values.append(match[metric].iloc[0])
                counts.append(int(match["evaluated_files"].iloc[0]))
            else:
                values.append(np.nan)
                counts.append(0)
            labels.append(dist)

        x_pos = range(len(labels))
        ax.bar(x_pos, values, color=cmap(ri % 8), width=0.7)
        for xi, (dist, cnt) in enumerate(zip(labels, counts)):
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
    fig.supxlabel("Nearest Same-Top-Key Distance Group", fontsize=13)
    fig.suptitle("%s  |  Bar Grid by Root Key" % _metric_label(metric), fontsize=14)
    fig.tight_layout(rect=[0, 0.04, 1, 0.95])
    _close_fig(fig, output_dir / "bar" / ("grid_%s.png" % metric))


# ---------------------------------------------------------------------------
# Plot 3: Bar-all  — X = distance group, hue = root_key
# ---------------------------------------------------------------------------

def plot_bar_all(df: pd.DataFrame, metric: str, output_dir: Path) -> None:
    print("[bar-all] generating …", flush=True)
    root_key_list = sorted(df["target_top_level_key"].unique())
    dist_order = _sorted_distances(df["nearest_same_top_key_group"].unique())
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
        sub = df[df["target_top_level_key"] == rk]
        values = []
        for dist in dist_order:
            match = sub[sub["nearest_same_top_key_group"] == dist]
            values.append(match[metric].iloc[0] if not match.empty else np.nan)
        offset = (ri - (n_rk - 1) / 2) * bar_width
        ax.bar(x_pos + offset, values, bar_width * 0.9,
               color=cmap(ri % 10), label=rk[:30])

    ax.set_xticks(x_pos)
    ax.set_xticklabels(dist_order, fontsize=10)
    ax.set_ylabel(_metric_label(metric))
    ax.set_xlabel("Nearest Same-Top-Key Distance Group")
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
        description="Plot distance-group × root_key effects from grouped CSV."
    )
    p.add_argument("csv", type=Path, nargs="?", default=None,
                   help="Path to distance_by_root_key_metrics.csv. "
                        "Default: metric-results/distance-by-root-key/distance_by_root_key_metrics.csv")
    p.add_argument("--output-dir", type=Path, default=None,
                   help="Output directory for plots. Default: sibling of CSV / plots/.")
    p.add_argument("--metrics", default="field_path_f1,leaf_triple_f1,value_accuracy",
                   help="Comma-separated metric names. Default: field_path_f1,leaf_triple_f1,value_accuracy")
    p.add_argument("--root-key", action="append", default=None,
                   help="Filter to specific root key(s). Repeatable. Default: all.")
    p.add_argument("--split", default=None, help="Filter by split (e.g. val).")
    p.add_argument("--task", default=None, help="Filter by task (e.g. node_config_qa).")
    p.add_argument("--min-files", type=int, default=3,
                   help="Minimum evaluated_files per group. Default: 3.")
    p.add_argument("--plots", default="heatmap,bar-grid,bar-all",
                   help="Which plot types to generate. Default: heatmap,bar-grid,bar-all")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    _setup_chinese_font()
    matplotlib.use("Agg")

    csv_path = args.csv or Path(
        "metric-results/distance-by-root-key/distance_by_root_key_metrics.csv"
    )
    if not csv_path.exists():
        raise SystemExit("CSV not found: %s" % csv_path)

    output_dir = args.output_dir or csv_path.parent / "plots"
    metric_list = [m.strip() for m in args.metrics.split(",") if m.strip()]
    plot_set = {p.strip() for p in args.plots.split(",") if p.strip()}

    print("[plot-drk] source: %s" % csv_path, flush=True)
    print("[plot-drk] output: %s" % output_dir, flush=True)
    print("[plot-drk] metrics: %s" % metric_list, flush=True)
    print("[plot-drk] plots:   %s" % sorted(plot_set), flush=True)

    for metric in metric_list:
        print("--- %s ---" % metric, flush=True)
        df = load_data(csv_path, metric, args.split, args.task,
                       args.min_files, args.root_key)
        print("  groups after filter: %d" % len(df), flush=True)

        if "heatmap" in plot_set:
            plot_heatmap(df, metric, output_dir)
        if "bar-grid" in plot_set:
            plot_bar_grid(df, metric, output_dir)
        if "bar-all" in plot_set:
            plot_bar_all(df, metric, output_dir)

    print("[plot-drk] done.", flush=True)


if __name__ == "__main__":
    main()
