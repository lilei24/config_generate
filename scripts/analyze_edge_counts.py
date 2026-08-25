#!/usr/bin/env python3
"""Analyze only edge counts for train/val graph JSON files."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from statistics import mean, median
from typing import Iterable
from xml.sax.saxutils import escape


# Local defaults. The expected layout is:
# datasets/train/*.json
# datasets/val/*.json
DEFAULT_DATASET_ROOT = Path("datasets")
DEFAULT_OUTPUT_DIR = Path("/tmp/edge_count_analysis")
VALID_STATUSES = {"ok", "empty_links"}


@dataclass
class EdgeCountRow:
    split: str
    file: str
    edge_count: int
    status: str
    detail: str = ""


def iter_json_files(
    dataset_root: Path,
    splits: Iterable[str],
) -> Iterable[tuple[str, Path]]:
    for split in splits:
        split_dir = dataset_root / split
        if not split_dir.exists():
            continue
        for path in sorted(split_dir.rglob("*.json")):
            if path.is_file():
                yield split, path


def count_edges(path: Path) -> tuple[int, str, str]:
    """统计原始 links 数组长度，不过滤重复链路、自环或无效端点。"""
    try:
        graph = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - keep going and report the bad file.
        return 0, "bad_json", str(exc)

    if not isinstance(graph, dict):
        return 0, "graph_not_object", type(graph).__name__

    if "links" not in graph:
        return 0, "missing_links", ""

    links = graph["links"]
    if not isinstance(links, list):
        return 0, "links_not_list", type(links).__name__

    if not links:
        return 0, "empty_links", ""

    return len(links), "ok", ""


def number_summary(values: list[int]) -> dict[str, float | int | None]:
    if not values:
        return {
            "count": 0,
            "min": None,
            "max": None,
            "mean": None,
            "median": None,
        }
    return {
        "count": len(values),
        "min": min(values),
        "max": max(values),
        "mean": round(mean(values), 4),
        "median": median(values),
    }


def summarize_counts(rows: list[EdgeCountRow]) -> dict[str, object]:
    valid_counts = [row.edge_count for row in rows if row.status in VALID_STATUSES]
    split_counts: dict[str, dict[str, object]] = {}
    for split in sorted({row.split for row in rows}):
        split_rows = [row for row in rows if row.split == split]
        split_valid = [
            row.edge_count for row in split_rows if row.status in VALID_STATUSES
        ]
        split_counts[split] = {
            "files": len(split_rows),
            "status_counts": dict(Counter(row.status for row in split_rows)),
            "edge_count": number_summary(split_valid),
        }

    return {
        "files": len(rows),
        "status_counts": dict(Counter(row.status for row in rows)),
        "edge_count": number_summary(valid_counts),
        "splits": split_counts,
    }


def percentile(values: list[int], ratio: float) -> float | None:
    """使用线性插值计算分位数，ratio 取值范围为 0 到 1。"""
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * ratio
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def detail_histogram_bins(
    values: list[int],
    requested_bins: int,
    detail_percentile: float,
) -> tuple[list[tuple[str, int]], int | None]:
    """细分 0 到指定分位数，并将长尾样本放入独立溢出桶。"""
    threshold_value = percentile(values, detail_percentile)
    if threshold_value is None:
        return [], None
    threshold = math.ceil(threshold_value)
    bin_width = max(1, math.ceil((threshold + 1) / max(1, requested_bins)))
    bins: list[tuple[int, int, int]] = []
    for start in range(0, threshold + 1, bin_width):
        bins.append((start, min(start + bin_width - 1, threshold), 0))

    overflow_count = 0
    for value in values:
        if value > threshold:
            overflow_count += 1
            continue
        index = min(value // bin_width, len(bins) - 1)
        start, end, count = bins[index]
        bins[index] = (start, end, count + 1)

    result = [
        (str(start) if start == end else f"{start}-{end}", count)
        for start, end, count in bins
    ]
    if overflow_count:
        result.append((f">{threshold}", overflow_count))
    return result, threshold


def logarithmic_histogram_bins(values: list[int]) -> list[tuple[str, int]]:
    """按 0、1、2-3、4-7 等二次幂区间保留完整长尾。"""
    if not values:
        return []
    counts = Counter(values)
    result = [("0", counts.get(0, 0))]
    max_value = max(values)
    if max_value >= 1:
        result.append(("1", counts.get(1, 0)))
    start = 2
    while start <= max_value:
        end = start * 2 - 1
        result.append(
            (
                f"{start}-{end}",
                sum(count for value, count in counts.items() if start <= value <= end),
            )
        )
        start *= 2
    return result


def quantile_rows(values: list[int]) -> list[tuple[str, float | None]]:
    return [
        (f"P{percent}", percentile(values, percent / 100))
        for percent in (0, 25, 50, 75, 90, 95, 99, 100)
    ]


def cdf_points(values: list[int]) -> list[tuple[int, int, float]]:
    counts = Counter(values)
    cumulative = 0
    result: list[tuple[int, int, float]] = []
    for edge_count, graph_count in sorted(counts.items()):
        cumulative += graph_count
        result.append((edge_count, cumulative, cumulative / len(values)))
    return result


def write_csv(path: Path, rows: list[EdgeCountRow]) -> None:
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=["split", "file", "edge_count", "status", "detail"],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "split": row.split,
                    "file": row.file,
                    "edge_count": row.edge_count,
                    "status": row.status,
                    "detail": row.detail,
                }
            )


def write_txt(path: Path, rows: list[EdgeCountRow]) -> None:
    width = max((len(row.file) for row in rows), default=4)
    with path.open("w", encoding="utf-8") as file:
        file.write("split\tedge_count\tstatus\tfile\tdetail\n")
        for row in rows:
            file.write(
                f"{row.split}\t{row.edge_count}\t{row.status}\t"
                f"{row.file:<{width}}\t{row.detail}\n"
            )


def write_histogram_csv(path: Path, bins: list[tuple[str, int]]) -> None:
    total = sum(count for _, count in bins)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=["edge_count_bin", "graph_count", "graph_ratio"],
        )
        writer.writeheader()
        for label, count in bins:
            writer.writerow(
                {
                    "edge_count_bin": label,
                    "graph_count": count,
                    "graph_ratio": round(count / total, 6) if total else 0.0,
                }
            )


def write_quantiles_csv(
    path: Path,
    rows: list[tuple[str, float | None]],
) -> None:
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=["quantile", "edge_count"])
        writer.writeheader()
        for label, value in rows:
            writer.writerow(
                {
                    "quantile": label,
                    "edge_count": "" if value is None else round(value, 4),
                }
            )


def write_histogram_svg(
    path: Path,
    bins: list[tuple[str, int]],
    title: str,
    *,
    logarithmic_y: bool = False,
) -> None:
    width = 1200
    height = 720
    margin_left = 80
    margin_right = 30
    margin_top = 70
    margin_bottom = 110
    plot_width = width - margin_left - margin_right
    plot_height = height - margin_top - margin_bottom
    max_count = max((count for _, count in bins), default=1)
    total_count = sum(count for _, count in bins)
    bar_gap = 2
    bar_width = max(
        1,
        (plot_width - bar_gap * max(0, len(bins) - 1)) / max(1, len(bins)),
    )

    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
            f'height="{height}" viewBox="0 0 {width} {height}">'
        ),
        '<rect width="100%" height="100%" fill="white"/>',
        (
            f'<text x="{width / 2}" y="32" text-anchor="middle" '
            f'font-size="24" font-family="Arial">{escape(title)}</text>'
        ),
        (
            f'<line x1="{margin_left}" y1="{margin_top + plot_height}" '
            f'x2="{width - margin_right}" y2="{margin_top + plot_height}" '
            'stroke="#222"/>'
        ),
        (
            f'<line x1="{margin_left}" y1="{margin_top}" x2="{margin_left}" '
            f'y2="{margin_top + plot_height}" stroke="#222"/>'
        ),
        (
            f'<text x="{margin_left - 45}" y="{margin_top + 10}" '
            f'font-size="12" font-family="Arial">{max_count}</text>'
        ),
        (
            f'<text x="{margin_left - 20}" y="{margin_top + plot_height + 4}" '
            'font-size="12" font-family="Arial">0</text>'
        ),
        (
            f'<text x="{width / 2}" y="{height - 20}" text-anchor="middle" '
            'font-size="16" font-family="Arial">edge count per graph</text>'
        ),
        (
            f'<text x="20" y="{height / 2}" '
            f'transform="rotate(-90 20 {height / 2})" text-anchor="middle" '
            f'font-size="16" font-family="Arial">graph count'
            f'{" (log scale)" if logarithmic_y else ""}</text>'
        ),
    ]

    label_stride = max(1, math.ceil(len(bins) / 24))
    for index, (label, count) in enumerate(bins):
        x = margin_left + index * (bar_width + bar_gap)
        if max_count == 0:
            bar_height = 0
        elif logarithmic_y:
            bar_height = math.log1p(count) / math.log1p(max_count) * plot_height
        else:
            bar_height = count / max_count * plot_height
        y = margin_top + plot_height - bar_height
        parts.append(
            f'<rect x="{x:.2f}" y="{y:.2f}" width="{bar_width:.2f}" '
            f'height="{bar_height:.2f}" fill="#4C78A8">'
            f"<title>{escape(label)}: {count} graphs "
            f"({count / total_count:.2%})</title></rect>"
            if total_count
            else (
                f'<rect x="{x:.2f}" y="{y:.2f}" width="{bar_width:.2f}" '
                f'height="{bar_height:.2f}" fill="#4C78A8">'
                f"<title>{escape(label)}: 0 graphs</title></rect>"
            )
        )
        if index % label_stride == 0 or index == len(bins) - 1:
            label_x = x + bar_width / 2
            label_y = margin_top + plot_height + 18
            parts.append(
                f'<text x="{label_x:.2f}" y="{label_y}" '
                f'transform="rotate(45 {label_x:.2f} {label_y})" '
                f'text-anchor="start" font-size="10" font-family="Arial">'
                f"{escape(label)}</text>"
            )

    parts.append("</svg>")
    path.write_text("\n".join(parts), encoding="utf-8")


def write_cdf_svg(
    path: Path,
    points: list[tuple[int, int, float]],
) -> None:
    width, height = 1200, 720
    left, right, top, bottom = 90, 35, 65, 85
    plot_width = width - left - right
    plot_height = height - top - bottom
    max_value = max((value for value, _, _ in points), default=0)
    log_max = math.log1p(max_value) or 1.0

    def x_position(value: int) -> float:
        return left + math.log1p(value) / log_max * plot_width

    def y_position(ratio: float) -> float:
        return top + (1 - ratio) * plot_height

    polyline = " ".join(
        f"{x_position(value):.2f},{y_position(ratio):.2f}"
        for value, _, ratio in points
    )
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
            f'height="{height}" viewBox="0 0 {width} {height}">'
        ),
        '<rect width="100%" height="100%" fill="white"/>',
        (
            f'<text x="{width / 2}" y="32" text-anchor="middle" '
            'font-size="24" font-family="Arial">Edge Count CDF</text>'
        ),
        (
            f'<line x1="{left}" y1="{top + plot_height}" '
            f'x2="{width - right}" y2="{top + plot_height}" stroke="#222"/>'
        ),
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_height}" stroke="#222"/>',
    ]
    for index in range(0, 11):
        ratio = index / 10
        y = y_position(ratio)
        parts.append(
            f'<line x1="{left}" y1="{y:.2f}" x2="{width - right}" y2="{y:.2f}" stroke="#e3e7eb"/>'
        )
        parts.append(
            f'<text x="{left - 12}" y="{y + 4:.2f}" text-anchor="end" '
            f'font-size="11" font-family="Arial">{ratio:.1f}</text>'
        )
    tick_values = [0]
    tick = 1
    while tick <= max_value:
        tick_values.append(tick)
        tick *= 2
    tick_stride = max(1, math.ceil(len(tick_values) / 12))
    for index, value in enumerate(tick_values):
        if index % tick_stride and value != tick_values[-1]:
            continue
        x = x_position(value)
        parts.append(
            f'<line x1="{x:.2f}" y1="{top + plot_height}" '
            f'x2="{x:.2f}" y2="{top + plot_height + 6}" stroke="#222"/>'
        )
        parts.append(
            f'<text x="{x:.2f}" y="{top + plot_height + 22}" '
            f'text-anchor="middle" font-size="10" font-family="Arial">{value}</text>'
        )
    if points:
        parts.append(
            f'<polyline points="{polyline}" fill="none" stroke="#2A7F62" stroke-width="3"/>'
        )
    parts.extend(
        [
            (
                f'<text x="{width / 2}" y="{height - 20}" '
                'text-anchor="middle" font-size="16" font-family="Arial">'
                "edge count per graph (log scale)</text>"
            ),
            (
                f'<text x="22" y="{height / 2}" '
                f'transform="rotate(-90 22 {height / 2})" text-anchor="middle" '
                'font-size="16" font-family="Arial">'
                "cumulative graph ratio</text>"
            ),
            "</svg>",
        ]
    )
    path.write_text("\n".join(parts), encoding="utf-8")


def analyze(
    dataset_root: Path,
    output_dir: Path,
    splits: list[str],
    bins: int,
    detail_percentile: float,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    rows: list[EdgeCountRow] = []
    missing_split_dirs = [
        split for split in splits if not (dataset_root / split).exists()
    ]
    for split, path in iter_json_files(dataset_root, splits):
        edge_count, status, detail = count_edges(path)
        rows.append(
            EdgeCountRow(
                split=split,
                file=str(path.relative_to(dataset_root)),
                edge_count=edge_count,
                status=status,
                detail=detail,
            )
        )

    counts = [row.edge_count for row in rows if row.status in VALID_STATUSES]
    bins_data, detail_threshold = detail_histogram_bins(
        counts,
        bins,
        detail_percentile,
    )
    log_bins_data = logarithmic_histogram_bins(counts)
    quantiles = quantile_rows(counts)
    summary = summarize_counts(rows)
    summary["dataset_root"] = str(dataset_root)
    summary["missing_split_dirs"] = missing_split_dirs
    summary["detail_histogram"] = {
        "percentile": detail_percentile * 100,
        "inclusive_max_edge_count": detail_threshold,
    }
    summary["outputs"] = {
        "edge_counts_csv": "edge_counts.csv",
        "edge_counts_txt": "edge_counts.txt",
        "edge_count_histogram_csv": "edge_count_histogram.csv",
        "edge_count_histogram_svg": "edge_count_histogram.svg",
        "edge_count_histogram_log_csv": "edge_count_histogram_log.csv",
        "edge_count_histogram_log_svg": "edge_count_histogram_log.svg",
        "edge_count_cdf_svg": "edge_count_cdf.svg",
        "edge_count_quantiles_csv": "edge_count_quantiles.csv",
    }

    (output_dir / "edge_count_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    write_csv(output_dir / "edge_counts.csv", rows)
    write_txt(output_dir / "edge_counts.txt", rows)
    write_histogram_csv(output_dir / "edge_count_histogram.csv", bins_data)
    write_histogram_svg(
        output_dir / "edge_count_histogram.svg",
        bins_data,
        f"Edge Count Distribution (0-P{detail_percentile * 100:g})",
    )
    write_histogram_csv(
        output_dir / "edge_count_histogram_log.csv",
        log_bins_data,
    )
    write_histogram_svg(
        output_dir / "edge_count_histogram_log.svg",
        log_bins_data,
        "Edge Count Distribution (Logarithmic Bins and Y Axis)",
        logarithmic_y=True,
    )
    write_cdf_svg(output_dir / "edge_count_cdf.svg", cdf_points(counts))
    write_quantiles_csv(output_dir / "edge_count_quantiles.csv", quantiles)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze per-graph edge counts and draw a histogram."
    )
    parser.add_argument(
        "dataset_root",
        nargs="?",
        type=Path,
        default=DEFAULT_DATASET_ROOT,
        help=(
            "Dataset root containing train/ and val/ directories. "
            f"Default: {DEFAULT_DATASET_ROOT}"
        ),
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Directory for generated edge-count reports. Default: {DEFAULT_OUTPUT_DIR}",
    )
    parser.add_argument(
        "--splits",
        nargs="+",
        default=["train", "val"],
        help="Split directory names to analyze.",
    )
    parser.add_argument(
        "--bins",
        type=int,
        default=30,
        help="Approximate histogram bins when max edge count is above 100.",
    )
    parser.add_argument(
        "--detail-percentile",
        type=float,
        default=95.0,
        help="Upper percentile shown in the detailed histogram. Default: 95.",
    )
    args = parser.parse_args()
    if args.bins <= 0:
        parser.error("--bins must be greater than 0")
    if not 0 < args.detail_percentile <= 100:
        parser.error("--detail-percentile must be in (0, 100]")
    args.detail_percentile /= 100
    return args


def main() -> None:
    args = parse_args()
    analyze(
        args.dataset_root,
        args.output_dir,
        args.splits,
        args.bins,
        args.detail_percentile,
    )
    print(f"Wrote edge-count reports to {args.output_dir}")


if __name__ == "__main__":
    main()
