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


def histogram_bins(values: list[int], requested_bins: int) -> list[tuple[str, int]]:
    if not values:
        return []

    max_value = max(values)
    if max_value <= 100:
        counts = Counter(values)
        return [
            (str(value), counts.get(value, 0))
            for value in range(0, max_value + 1)
        ]

    bin_count = max(1, requested_bins)
    bin_width = max(1, math.ceil((max_value + 1) / bin_count))
    bins: list[tuple[int, int, int]] = []
    for start in range(0, max_value + 1, bin_width):
        end = min(start + bin_width - 1, max_value)
        bins.append((start, end, 0))

    index_by_start = {start: index for index, (start, _, _) in enumerate(bins)}
    for value in values:
        start = (value // bin_width) * bin_width
        index = index_by_start[start]
        bin_start, bin_end, count = bins[index]
        bins[index] = (bin_start, bin_end, count + 1)

    return [(f"{start}-{end}", count) for start, end, count in bins]


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
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=["edge_count_bin", "graph_count"],
        )
        writer.writeheader()
        for label, count in bins:
            writer.writerow({"edge_count_bin": label, "graph_count": count})


def write_histogram_svg(
    path: Path,
    bins: list[tuple[str, int]],
    title: str,
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
            'font-size="16" font-family="Arial">graph count</text>'
        ),
    ]

    label_stride = max(1, math.ceil(len(bins) / 24))
    for index, (label, count) in enumerate(bins):
        x = margin_left + index * (bar_width + bar_gap)
        bar_height = 0 if max_count == 0 else (count / max_count) * plot_height
        y = margin_top + plot_height - bar_height
        parts.append(
            f'<rect x="{x:.2f}" y="{y:.2f}" width="{bar_width:.2f}" '
            f'height="{bar_height:.2f}" fill="#4C78A8"/>'
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


def analyze(
    dataset_root: Path,
    output_dir: Path,
    splits: list[str],
    bins: int,
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
    bins_data = histogram_bins(counts, bins)
    summary = summarize_counts(rows)
    summary["dataset_root"] = str(dataset_root)
    summary["missing_split_dirs"] = missing_split_dirs
    summary["outputs"] = {
        "edge_counts_csv": "edge_counts.csv",
        "edge_counts_txt": "edge_counts.txt",
        "edge_count_histogram_csv": "edge_count_histogram.csv",
        "edge_count_histogram_svg": "edge_count_histogram.svg",
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
        "Edge Count Distribution",
    )


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
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    analyze(args.dataset_root, args.output_dir, args.splits, args.bins)
    print(f"Wrote edge-count reports to {args.output_dir}")


if __name__ == "__main__":
    main()
