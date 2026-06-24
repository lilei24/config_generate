#!/usr/bin/env python3
"""Plot three-level grouped metrics: betweenness × distance × root key.

Visualizations:
  1. Heatmap           — betweenness vs distance, color = metric (per root_key)
  2. Heatmap-all       — same, aggregated across all root_keys
  3. Combined-heatmap  — rows = "root_key | dist=X", cols = betweenness (3 dims)
  4. Line              — betweenness on X, distance as hue (per root_key)
  5. Line-by-dist      — one subplot per distance, root_key as hue
  6. Bar               — one subplot per root_key, X = distance, hue = betweenness
  7. Bar-all           — same, aggregated across all root_keys

Input: the grouped CSV written by analyze_betweenness_distance_rootkey.py.
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
# Palette
# ---------------------------------------------------------------------------

BETWEENNESS_HEATMAP_CMAP = "YlOrRd"

DISTANCE_PALETTE = {
    "0": "#1b9e77", "1": "#7570b3", "2": "#d95f02",
    "3": "#e7298a", "4": "#66a61e", "5": "#e6ab02",
    "inf": "#a6761d",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_grouped_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    for col in [
        "field_path_precision", "field_path_recall", "field_path_f1",
        "leaf_triple_precision", "leaf_triple_recall", "leaf_triple_f1",
        "value_accuracy", "hallucinated_rate", "missing_rate",
        "top_level_exact_match",
        "total_files", "evaluated_files", "model_error_files", "eval_error_files",
        "error_rate",
    ]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _betweenness_sort_key(group: str) -> Tuple[int, float]:
    if "-" in group:
        try:
            return (0, float(group.split("-", 1)[0]))
        except ValueError:
            pass
    return (1, 0.0)


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


def _sorted_betweenness_groups(groups: List[str]) -> List[str]:
    return sorted(set(groups), key=_betweenness_sort_key)


def _sorted_distance_groups(groups: List[str]) -> List[str]:
    return sorted(set(str(g) for g in groups), key=_distance_sort_key)


def _pick_distance_colors(distances: List[str]) -> Dict[str, str]:
    cmap = plt.colormaps.get_cmap("tab10")
    mapping: Dict[str, str] = {}
    for idx, dist in enumerate(distances):
        if dist in DISTANCE_PALETTE:
            mapping[dist] = DISTANCE_PALETTE[dist]
        else:
            mapping[dist] = matplotlib.colors.to_hex(cmap(idx % 10))
    return mapping


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


def _metric_label(metric: str) -> str:
    labels = {
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


def _close_fig(fig: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("  wrote %s" % path, flush=True)


def _safe_filename(text: str) -> str:
    return text.replace("/", "_").replace("\\", "_").replace("|", "_").replace(" ", "_")


# ---------------------------------------------------------------------------
# Annotation helper: every non-NaN cell gets a number
# ---------------------------------------------------------------------------

def _make_annot(pivot: pd.DataFrame) -> pd.DataFrame:
    """Return a DataFrame of annotation strings: NaN → '', value → '%.2f'."""
    n_rows, n_cols = pivot.shape
    data: List[List[str]] = []
    for r in range(n_rows):
        row_vals: List[str] = []
        for c in range(n_cols):
            v = pivot.iloc[r, c]
            row_vals.append("" if pd.isna(v) else "%.2f" % v)
        data.append(row_vals)
    return pd.DataFrame(data, index=pivot.index, columns=pivot.columns)


def _annotate_heatmap_cells(
    ax: Any,
    pivot: pd.DataFrame,
    font_size: float,
    vmin: float,
    vmax: float,
) -> None:
    """Draw every non-NaN cell value manually.

    Seaborn annotations can become unreliable or unreadable on very tall
    heatmaps. Manual annotation keeps the combined view faithful to the CSV.
    """

    midpoint = (vmin + vmax) / 2 if vmax > vmin else vmin
    for row_index in range(pivot.shape[0]):
        for col_index in range(pivot.shape[1]):
            value = pivot.iloc[row_index, col_index]
            if pd.isna(value):
                continue
            text_color = "white" if float(value) >= midpoint else "#111111"
            ax.text(
                col_index + 0.5,
                row_index + 0.5,
                "%.2f" % value,
                ha="center",
                va="center",
                fontsize=font_size,
                color=text_color,
            )


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

REQUIRED_COLUMNS = [
    "split", "task",
    "betweenness_centrality_group", "nearest_same_top_key_distance",
    "target_top_level_key", "evaluated_files",
]


def load_data(csv_path: Path, metric: str, split: Optional[str], task: Optional[str],
              min_files: int, root_keys: Optional[List[str]]) -> pd.DataFrame:
    df = _read_grouped_csv(csv_path)

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(
            "CSV missing columns: %s\nAvailable: %s\n"
            "Expected output from analyze_betweenness_distance_rootkey.py."
            % (missing, list(df.columns))
        )
    if metric not in df.columns:
        raise ValueError("Metric '%s' not found. Available: %s" % (metric, list(df.columns)))

    if split:
        df = df[df["split"] == split]
    if task:
        df = df[df["task"] == task]
    if root_keys:
        df = df[df["target_top_level_key"].isin(root_keys)]

    if df.empty:
        raise ValueError("No rows after filtering.")

    # Drop rows where metric is NaN
    df = df.dropna(subset=[metric])

    # Filter by sample count
    df = df[df["evaluated_files"] >= min_files]

    # Drop rows without distance info
    df = df[df["nearest_same_top_key_distance"].notna()]
    df = df[df["nearest_same_top_key_distance"].astype(str).str.strip() != ""]

    if df.empty:
        raise ValueError("No valid rows — try lowering --min-files")

    # Normalize distance to string
    df["nearest_same_top_key_distance"] = df["nearest_same_top_key_distance"].astype(str)

    return df


# ---------------------------------------------------------------------------
# Plot 1: Heatmap (per root_key)
# ---------------------------------------------------------------------------

def plot_heatmap(df: pd.DataFrame, metric: str, output_dir: Path,
                 root_keys: Optional[List[str]]) -> None:
    print("[heatmap] generating …", flush=True)
    rk_list = root_keys or sorted(df["target_top_level_key"].unique())
    for rk in rk_list:
        sub = df[df["target_top_level_key"] == rk]
        if sub.empty:
            continue
        pivot = sub.pivot_table(
            index="nearest_same_top_key_distance",
            columns="betweenness_centrality_group",
            values=metric, aggfunc="mean",
        )
        pivot = pivot.dropna(how="all").dropna(axis=1, how="all")
        if pivot.shape[0] < 1 or pivot.shape[1] < 1:
            continue

        # Sort rows: small distance at bottom, inf at top
        row_order = sorted(pivot.index, key=_distance_sort_key)
        pivot = pivot.loc[row_order].iloc[::-1]

        annot_mat = _make_annot(pivot)
        n_dist, n_bc = pivot.shape
        cell_size = 0.65
        fig, ax = plt.subplots(figsize=(max(6, n_bc * cell_size + 2),
                                        max(4, n_dist * cell_size + 1.5)))
        sns.heatmap(
            pivot, annot=annot_mat, fmt="", cmap=BETWEENNESS_HEATMAP_CMAP,
            vmin=0.0, vmax=1.0, linewidths=0.5, linecolor="white",
            cbar_kws={"shrink": 0.8}, ax=ax,
        )
        ax.set_title("%s\n%s  |  Heatmap" % (_metric_label(metric), rk), fontsize=13)
        ax.set_xlabel("Betweenness Centrality Group")
        ax.set_ylabel("Nearest Same-Top-Key Distance  (bottom → top)")
        _close_fig(fig, output_dir / "heatmap" / ("%s_%s.png" % (_safe_filename(rk), metric)))


# ---------------------------------------------------------------------------
# Plot 2: Heatmap-all (all root_keys)
# ---------------------------------------------------------------------------

def plot_heatmap_all(df: pd.DataFrame, metric: str, output_dir: Path) -> None:
    print("[heatmap-all] generating …", flush=True)
    pivot = df.pivot_table(
        index="nearest_same_top_key_distance",
        columns="betweenness_centrality_group",
        values=metric, aggfunc="mean",
    )
    pivot = pivot.dropna(how="all").dropna(axis=1, how="all")
    if pivot.shape[0] < 1 or pivot.shape[1] < 1:
        print("  skip: no data", flush=True)
        return

    row_order = sorted(pivot.index, key=_distance_sort_key)
    pivot = pivot.loc[row_order].iloc[::-1]

    annot_mat = _make_annot(pivot)
    n_dist, n_bc = pivot.shape
    cell_size = 0.7
    fig, ax = plt.subplots(figsize=(max(6, n_bc * cell_size + 2),
                                    max(4, n_dist * cell_size + 1.5)))
    vmin = df[metric].min() if not df[metric].isna().all() else 0.0
    vmax = df[metric].max() if not df[metric].isna().all() else 1.0
    sns.heatmap(
        pivot, annot=annot_mat, fmt="", cmap=BETWEENNESS_HEATMAP_CMAP,
        vmin=vmin, vmax=vmax, linewidths=0.5, linecolor="white",
        cbar_kws={"shrink": 0.8}, ax=ax,
    )
    ax.set_title("%s\nAll root keys  |  Heatmap" % _metric_label(metric), fontsize=13)
    ax.set_xlabel("Betweenness Centrality Group")
    ax.set_ylabel("Nearest Same-Top-Key Distance  (bottom → top)")
    _close_fig(fig, output_dir / "heatmap" / ("all_rootkeys_%s.png" % metric))


# ---------------------------------------------------------------------------
# Plot 3: Combined heatmap — rows = "root_key | dist=X", cols = betweenness
# ---------------------------------------------------------------------------

def plot_combined_heatmap(df: pd.DataFrame, metric: str, output_dir: Path,
                          root_keys: Optional[List[str]]) -> None:
    print("[combined-heatmap] generating …", flush=True)

    df = df.copy()
    df["row_label"] = (df["target_top_level_key"].astype(str)
                       + "  │ dist=" + df["nearest_same_top_key_distance"].astype(str))

    pivot = df.pivot_table(
        index="row_label", columns="betweenness_centrality_group",
        values=metric, aggfunc="mean",
    )
    pivot = pivot.dropna(how="all").dropna(axis=1, how="all")
    if pivot.shape[0] < 1 or pivot.shape[1] < 1:
        print("  skip: no data", flush=True)
        return

    # Sort: within each root_key, bottom=small dist, top=inf
    def _row_sort_key(label: str) -> Tuple[str, Any]:
        parts = label.rsplit("dist=", 1)
        rk = parts[0].rstrip(" │\t\n\r")
        dist_str = parts[1].strip() if len(parts) > 1 else ""
        dk = _distance_sort_key(dist_str)
        return (rk, (-dk[0], -dk[1]))

    row_order = sorted(pivot.index, key=_row_sort_key)
    pivot = pivot.loc[row_order]

    n_rows, n_cols = pivot.shape
    # Larger cells keep row-level numeric annotations visible in dense plots.
    cell_w, cell_h = 0.9, 0.85
    fig_w = max(8, n_cols * cell_w + 3)
    fig_h = max(6, n_rows * cell_h + 2.0)
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))

    vmin = pivot.min().min() if not pivot.isna().all().all() else 0.0
    vmax = pivot.max().max() if not pivot.isna().all().all() else 1.0

    font_sz = max(6, min(10, int(cell_h * 12)))
    sns.heatmap(
        pivot, annot=False, fmt="", cmap=BETWEENNESS_HEATMAP_CMAP,
        vmin=vmin, vmax=vmax, linewidths=0.5, linecolor="#dddddd",
        cbar_kws={"shrink": 0.7}, ax=ax,
    )
    _annotate_heatmap_cells(ax, pivot, font_sz, float(vmin), float(vmax))

    # Separator lines between root_key blocks
    prev_rk = None
    for yi, label in enumerate(row_order):
        rk = label.rsplit("dist=", 1)[0].rstrip(" │\t\n\r")
        if prev_rk is not None and rk != prev_rk:
            ax.axhline(y=yi, color="#333333", linewidth=1.2)
        prev_rk = rk

    ax.set_title("%s\nroot_key × distance  |  Combined Heatmap" % _metric_label(metric),
                 fontsize=13)
    ax.set_xlabel("Betweenness Centrality Group")
    ax.set_ylabel("")
    ax.tick_params(axis="y", labelsize=8)
    ax.tick_params(axis="x", labelsize=8, rotation=45)
    out_base = output_dir / "combined-heatmap" / ("combined_%s" % metric)
    out_base.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_base.with_suffix(".png"), dpi=150, bbox_inches="tight")
    fig.savefig(out_base.with_suffix(".pdf"), bbox_inches="tight")
    plt.close(fig)
    print("  wrote %s" % out_base.with_suffix(".png"), flush=True)
    print("  wrote %s" % out_base.with_suffix(".pdf"), flush=True)


# ---------------------------------------------------------------------------
# Plot 4: Line
# ---------------------------------------------------------------------------

def plot_lines(df: pd.DataFrame, metric: str, output_dir: Path,
               root_keys: Optional[List[str]]) -> None:
    print("[line] generating …", flush=True)
    rk_list = root_keys or sorted(df["target_top_level_key"].unique())
    dist_groups = _sorted_distance_groups(df["nearest_same_top_key_distance"].unique())
    dist_colors = _pick_distance_colors(dist_groups)

    for rk in rk_list:
        sub = df[df["target_top_level_key"] == rk]
        if sub.empty:
            continue
        agg = sub.groupby(["betweenness_centrality_group", "nearest_same_top_key_distance"],
                           observed=False)[metric].mean().reset_index()
        agg = agg.dropna(subset=[metric])
        if agg.empty:
            continue

        fig, ax = plt.subplots(figsize=(10, 5))
        bc_labels = _sorted_betweenness_groups(agg["betweenness_centrality_group"].unique().tolist())
        x_pos = range(len(bc_labels))

        for dist in dist_groups:
            dsub = agg[agg["nearest_same_top_key_distance"] == dist]
            if dsub.empty:
                continue
            values = []
            valid_x = []
            for xi, bc_label in enumerate(bc_labels):
                match = dsub[dsub["betweenness_centrality_group"] == bc_label]
                if not match.empty:
                    values.append(match[metric].iloc[0])
                    valid_x.append(xi)
            if not values:
                continue
            ax.plot(valid_x, values, marker="o", linewidth=1.8, markersize=5,
                    color=dist_colors.get(dist, "#333333"), label="dist=%s" % dist)

        ax.set_xticks(x_pos)
        ax.set_xticklabels(bc_labels, rotation=45, ha="right", fontsize=8)
        ax.set_ylabel(_metric_label(metric))
        ax.set_xlabel("Betweenness Centrality Group")
        ax.set_title("%s\n%s  |  Line" % (_metric_label(metric), rk), fontsize=13)
        ax.legend(title="Distance", fontsize=8, title_fontsize=9)
        ax.set_ylim(0, 1)
        ax.grid(True, alpha=0.3)
        _close_fig(fig, output_dir / "line" / ("%s_%s.png" % (_safe_filename(rk), metric)))


# ---------------------------------------------------------------------------
# Plot 5: Line-by-dist
# ---------------------------------------------------------------------------

def plot_lines_by_distance(df: pd.DataFrame, metric: str, output_dir: Path,
                           root_keys: Optional[List[str]]) -> None:
    print("[line-by-dist] generating …", flush=True)
    rk_list = root_keys or sorted(df["target_top_level_key"].unique())
    if len(rk_list) > 12:
        print("  skip: too many root keys (%d) for overlaid view" % len(rk_list), flush=True)
        return

    dist_groups = _sorted_distance_groups(df["nearest_same_top_key_distance"].unique())
    ncols = min(3, len(dist_groups))
    nrows = math.ceil(len(dist_groups) / ncols)

    fig, axes = plt.subplots(nrows, ncols, figsize=(5 * ncols, 4 * nrows),
                              squeeze=False, sharex=True, sharey=True)
    cmap = plt.colormaps.get_cmap("tab10")

    for di, dist in enumerate(dist_groups):
        ax = axes[di // ncols][di % ncols]
        sub = df[df["nearest_same_top_key_distance"] == dist]
        if sub.empty:
            ax.set_title("dist=%s (no data)" % dist)
            continue
        bc_labels = _sorted_betweenness_groups(sub["betweenness_centrality_group"].unique().tolist())
        for ri, rk in enumerate(rk_list):
            rsub = sub[sub["target_top_level_key"] == rk]
            agg = rsub.groupby("betweenness_centrality_group",
                               observed=False)[metric].mean()
            values = [agg.get(bc, np.nan) for bc in bc_labels]
            ax.plot(range(len(bc_labels)), values, marker="o", linewidth=1.5,
                    markersize=4, color=cmap(ri % 10), label=rk[:25])
        ax.set_xticks(range(len(bc_labels)))
        ax.set_xticklabels(bc_labels, rotation=45, ha="right", fontsize=7)
        ax.set_ylim(0, 1)
        ax.set_title("distance = %s" % dist, fontsize=11)
        ax.grid(True, alpha=0.3)

    for di in range(len(dist_groups), nrows * ncols):
        axes[di // ncols][di % ncols].set_visible(False)

    handles, labels = ax.get_legend_handles_labels()
    if handles:
        fig.legend(handles, labels, loc="lower center", ncol=min(6, len(handles)),
                   fontsize=8, title="Root Key", title_fontsize=9)
    fig.supylabel(_metric_label(metric), fontsize=13)
    fig.supxlabel("Betweenness Centrality Group", fontsize=13)
    fig.suptitle("%s  |  Lines by Distance Group" % _metric_label(metric), fontsize=14)
    fig.tight_layout(rect=[0, 0.08, 1, 0.95])
    _close_fig(fig, output_dir / "line" / ("by_distance_%s.png" % metric))


# ---------------------------------------------------------------------------
# Plot 6: Bar grid (per root_key)
# ---------------------------------------------------------------------------

def plot_bars(df: pd.DataFrame, metric: str, output_dir: Path,
              root_keys: Optional[List[str]]) -> None:
    print("[bar] generating …", flush=True)
    rk_list = root_keys or sorted(df["target_top_level_key"].unique())
    bc_groups = _sorted_betweenness_groups(df["betweenness_centrality_group"].unique().tolist())
    bc_palette = dict(zip(bc_groups, sns.color_palette("Set2", len(bc_groups))))

    n = len(rk_list)
    ncols = min(3, n)
    nrows = math.ceil(n / ncols)
    fig, axes = plt.subplots(nrows, ncols, figsize=(5.5 * ncols, 4 * nrows),
                              squeeze=False, sharey=True)

    for ri, rk in enumerate(rk_list):
        ax = axes[ri // ncols][ri % ncols]
        sub = df[df["target_top_level_key"] == rk]
        if sub.empty:
            ax.set_title(rk[:30] + " (no data)")
            continue
        agg = sub.groupby(["nearest_same_top_key_distance", "betweenness_centrality_group"],
                           observed=False)[metric].mean().reset_index()
        agg = agg.dropna(subset=[metric])
        if agg.empty:
            ax.set_title(rk[:30] + " (no data)")
            continue
        dist_labels = _sorted_distance_groups(agg["nearest_same_top_key_distance"].unique())
        x_pos = range(len(dist_labels))
        bar_width = 0.8 / len(bc_groups)

        for bi, bc in enumerate(bc_groups):
            values = []
            for dist in dist_labels:
                match = agg[(agg["nearest_same_top_key_distance"] == dist) &
                             (agg["betweenness_centrality_group"] == bc)]
                values.append(match[metric].iloc[0] if not match.empty else np.nan)
            offset = (bi - (len(bc_groups) - 1) / 2) * bar_width
            bars = ax.bar([p + offset for p in x_pos], values, bar_width * 0.9,
                          color=bc_palette[bc], label=bc)
            for bar_obj, v in zip(bars, values):
                if not np.isnan(v):
                    ax.text(bar_obj.get_x() + bar_obj.get_width() / 2, v + 0.01,
                            "%.2f" % v, ha="center", va="bottom", fontsize=6)

        ax.set_xticks(x_pos)
        ax.set_xticklabels(dist_labels, fontsize=9)
        ax.set_title(rk[:30], fontsize=10)
        ax.set_ylim(0, 1.08)
        ax.grid(True, axis="y", alpha=0.3)

    for ri in range(n, nrows * ncols):
        axes[ri // ncols][ri % ncols].set_visible(False)

    handles, labels = ax.get_legend_handles_labels()
    if handles:
        fig.legend(handles, labels, loc="lower center", ncol=min(8, len(handles)),
                   fontsize=8, title="Betweenness", title_fontsize=9)
    fig.supylabel(_metric_label(metric), fontsize=13)
    fig.supxlabel("Nearest Same-Top-Key Distance", fontsize=13)
    fig.suptitle("%s  |  Bars by Root Key" % _metric_label(metric), fontsize=14)
    fig.tight_layout(rect=[0, 0.08, 1, 0.95])
    _close_fig(fig, output_dir / "bar" / ("by_rootkey_%s.png" % metric))


# ---------------------------------------------------------------------------
# Plot 7: Bar-all
# ---------------------------------------------------------------------------

def plot_bars_all(df: pd.DataFrame, metric: str, output_dir: Path) -> None:
    print("[bar-all] generating …", flush=True)
    bc_groups = _sorted_betweenness_groups(df["betweenness_centrality_group"].unique().tolist())
    bc_palette = dict(zip(bc_groups, sns.color_palette("Set2", len(bc_groups))))
    agg = df.groupby(["nearest_same_top_key_distance", "betweenness_centrality_group"],
                      observed=False)[metric].mean().reset_index()
    agg = agg.dropna(subset=[metric])
    if agg.empty:
        print("  skip: no data", flush=True)
        return

    dist_labels = _sorted_distance_groups(agg["nearest_same_top_key_distance"].unique())
    x_pos = range(len(dist_labels))
    bar_width = 0.8 / len(bc_groups)
    fig, ax = plt.subplots(figsize=(max(8, len(dist_labels) * 1.2), 5))

    for bi, bc in enumerate(bc_groups):
        values: List[float] = []
        for dist in dist_labels:
            match = agg[(agg["nearest_same_top_key_distance"] == dist) &
                         (agg["betweenness_centrality_group"] == bc)]
            values.append(match[metric].iloc[0] if not match.empty else np.nan)
        offset = (bi - (len(bc_groups) - 1) / 2) * bar_width
        bars = ax.bar([p + offset for p in x_pos], values, bar_width * 0.9,
                      color=bc_palette[bc], label=bc)
        for bar_obj, v in zip(bars, values):
            if not np.isnan(v):
                ax.text(bar_obj.get_x() + bar_obj.get_width() / 2, v + 0.005,
                        "%.2f" % v, ha="center", va="bottom", fontsize=6, rotation=90)

    ax.set_xticks(x_pos)
    ax.set_xticklabels(dist_labels, fontsize=10)
    ax.set_ylabel(_metric_label(metric))
    ax.set_xlabel("Nearest Same-Top-Key Distance")
    ax.set_title("%s\nAll Root Keys  |  Bar" % _metric_label(metric), fontsize=13)
    ax.set_ylim(0, 1.08)
    ax.legend(title="Betweenness", fontsize=8, title_fontsize=9)
    ax.grid(True, axis="y", alpha=0.3)
    _close_fig(fig, output_dir / "bar" / ("all_rootkeys_%s.png" % metric))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

METRICS = [
    "field_path_f1", "leaf_triple_f1", "value_accuracy",
    "top_level_exact_match", "hallucinated_rate", "missing_rate",
    "field_path_precision", "field_path_recall",
    "leaf_triple_precision", "leaf_triple_recall",
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Plot betweenness × distance × root key grouped metrics."
    )
    p.add_argument("csv", type=Path, nargs="?", default=None,
                   help="Path to betweenness_distance_rootkey_metrics.csv. "
                        "Default: metric-results/betweenness-distance-rootkey/betweenness_distance_rootkey_metrics.csv")
    p.add_argument("--output-dir", type=Path, default=None,
                   help="Output directory for plots. Default: sibling of CSV / plots/.")
    p.add_argument("--metrics", default="field_path_f1,leaf_triple_f1,value_accuracy",
                   help="Comma-separated metric names.")
    p.add_argument("--root-key", action="append", default=None,
                   help="Filter to specific root key(s). Repeatable.")
    p.add_argument("--split", default=None, help="Filter by split.")
    p.add_argument("--task", default=None, help="Filter by task.")
    p.add_argument("--min-files", type=int, default=3,
                   help="Minimum evaluated_files per group. Default: 3.")
    p.add_argument("--plots", default="combined-heatmap",
                   help="Which plot types to generate.")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    _setup_chinese_font()
    matplotlib.use("Agg")

    csv_path = args.csv or Path(
        "metric-results/betweenness-distance-rootkey/betweenness_distance_rootkey_metrics.csv"
    )
    if not csv_path.exists():
        raise SystemExit("CSV not found: %s" % csv_path)

    output_dir = args.output_dir or csv_path.parent / "plots"
    metric_list = [m.strip() for m in args.metrics.split(",") if m.strip()]
    plot_set = {p.strip() for p in args.plots.split(",") if p.strip()}

    print("[plot] source: %s" % csv_path, flush=True)
    print("[plot] output: %s" % output_dir, flush=True)
    print("[plot] metrics: %s" % metric_list, flush=True)
    print("[plot] plots:   %s" % sorted(plot_set), flush=True)

    for metric in metric_list:
        print("--- %s ---" % metric, flush=True)
        df = load_data(csv_path, metric, args.split, args.task, args.min_files,
                       args.root_key)
        print("  rows after filter: %d" % len(df), flush=True)

        if "heatmap" in plot_set:
            plot_heatmap(df, metric, output_dir, args.root_key)
        if "heatmap-all" in plot_set:
            plot_heatmap_all(df, metric, output_dir)
        if "combined-heatmap" in plot_set:
            plot_combined_heatmap(df, metric, output_dir, args.root_key)
        if "line" in plot_set:
            plot_lines(df, metric, output_dir, args.root_key)
        if "line-by-dist" in plot_set:
            plot_lines_by_distance(df, metric, output_dir, args.root_key)
        if "bar" in plot_set:
            plot_bars(df, metric, output_dir, args.root_key)
        if "bar-all" in plot_set:
            plot_bars_all(df, metric, output_dir)

    print("[plot] done.", flush=True)


if __name__ == "__main__":
    main()
