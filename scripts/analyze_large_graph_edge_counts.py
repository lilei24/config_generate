#!/usr/bin/env python3
"""筛选节点数超过指定阈值的图，并分析其边数量分布。"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from analyze_edge_counts import (
    cdf_points,
    detail_histogram_bins,
    logarithmic_histogram_bins,
    number_summary,
    quantile_rows,
    write_cdf_svg,
    write_histogram_csv,
    write_histogram_svg,
    write_quantiles_csv,
)


DEFAULT_DATASET_ROOT = Path("datasets")
DEFAULT_OUTPUT_DIR = Path("/tmp/large_graph_edge_count_analysis")
DEFAULT_MIN_NODE_COUNT = 100
DEFAULT_BINS = 30
DEFAULT_DETAIL_PERCENTILE = 95.0
VALID_EDGE_STATUSES = {"ok", "empty_links"}


@dataclass(frozen=True)
class LargeGraphEdgeRow:
    split: str
    file: str
    node_count: int
    edge_count: int
    status: str
    detail: str = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "dataset_root",
        nargs="?",
        type=Path,
        default=DEFAULT_DATASET_ROOT,
        help="包含 train/ 和 val/ 的数据集根目录，默认: %(default)s",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="分析结果输出目录，默认: %(default)s",
    )
    parser.add_argument(
        "--splits",
        nargs="+",
        default=["train", "val"],
        help="需要分析的数据划分，默认: train val",
    )
    parser.add_argument(
        "--min-node-count",
        type=int,
        default=DEFAULT_MIN_NODE_COUNT,
        help="只统计节点数严格大于该值的图，默认: %(default)s",
    )
    parser.add_argument(
        "--bins",
        type=int,
        default=DEFAULT_BINS,
        help="P95 主体直方图的近似分桶数，默认: %(default)s",
    )
    parser.add_argument(
        "--detail-percentile",
        type=float,
        default=DEFAULT_DETAIL_PERCENTILE,
        help="主体直方图显示到的分位数，默认: %(default)s",
    )
    args = parser.parse_args()
    if args.min_node_count < 0:
        parser.error("--min-node-count 不能小于 0")
    if args.bins <= 0:
        parser.error("--bins 必须大于 0")
    if not 0 < args.detail_percentile <= 100:
        parser.error("--detail-percentile 必须在 (0, 100] 范围内")
    args.detail_percentile /= 100
    return args


def iter_json_files(
    dataset_root: Path,
    splits: Iterable[str],
) -> Iterable[tuple[str, Path]]:
    for split in splits:
        split_dir = dataset_root / split
        if not split_dir.is_dir():
            continue
        for path in sorted(split_dir.rglob("*.json")):
            if path.is_file():
                yield split, path


def load_graph(path: Path) -> tuple[dict[str, Any] | None, str, str]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as error:  # noqa: BLE001 - 记录坏文件后继续统计。
        return None, "bad_json", f"{type(error).__name__}: {error}"
    if not isinstance(value, dict):
        return None, "graph_not_object", type(value).__name__
    return value, "ok", ""


def inspect_node_count(graph: dict[str, Any]) -> tuple[int | None, str, str]:
    if "nodes" not in graph:
        return None, "missing_nodes", ""
    nodes = graph["nodes"]
    if not isinstance(nodes, list):
        return None, "nodes_not_list", type(nodes).__name__
    return len(nodes), "ok", ""


def inspect_edge_count(graph: dict[str, Any]) -> tuple[int, str, str]:
    if "links" not in graph:
        return 0, "missing_links", ""
    links = graph["links"]
    if not isinstance(links, list):
        return 0, "links_not_list", type(links).__name__
    if not links:
        return 0, "empty_links", ""
    return len(links), "ok", ""


def write_rows_csv(path: Path, rows: list[LargeGraphEdgeRow]) -> None:
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "split",
                "file",
                "node_count",
                "edge_count",
                "status",
                "detail",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row.__dict__)


def write_rows_txt(path: Path, rows: list[LargeGraphEdgeRow]) -> None:
    with path.open("w", encoding="utf-8") as file:
        file.write("split\tnode_count\tedge_count\tstatus\tfile\tdetail\n")
        for row in rows:
            file.write(
                f"{row.split}\t{row.node_count}\t{row.edge_count}\t{row.status}\t"
                f"{row.file}\t{row.detail}\n"
            )


def split_summary(rows: list[LargeGraphEdgeRow]) -> dict[str, object]:
    result: dict[str, object] = {}
    for split in sorted({row.split for row in rows}):
        split_rows = [row for row in rows if row.split == split]
        valid_counts = [
            row.edge_count
            for row in split_rows
            if row.status in VALID_EDGE_STATUSES
        ]
        result[split] = {
            "selected_graphs": len(split_rows),
            "status_counts": dict(Counter(row.status for row in split_rows)),
            "edge_count": number_summary(valid_counts),
        }
    return result


def analyze(args: argparse.Namespace) -> None:
    args.output_dir.mkdir(parents=True, exist_ok=True)
    missing_split_dirs = [
        split for split in args.splits if not (args.dataset_root / split).is_dir()
    ]
    rows: list[LargeGraphEdgeRow] = []
    selection_status_counts: Counter[str] = Counter()
    scanned_files = 0

    for split, path in iter_json_files(args.dataset_root, args.splits):
        scanned_files += 1
        graph, load_status, load_detail = load_graph(path)
        if graph is None:
            selection_status_counts[load_status] += 1
            continue
        node_count, node_status, _ = inspect_node_count(graph)
        if node_count is None:
            selection_status_counts[node_status] += 1
            continue
        if node_count <= args.min_node_count:
            selection_status_counts["node_count_at_or_below_threshold"] += 1
            continue

        selection_status_counts["selected"] += 1
        edge_count, edge_status, edge_detail = inspect_edge_count(graph)
        rows.append(
            LargeGraphEdgeRow(
                split=split,
                file=str(path.relative_to(args.dataset_root)),
                node_count=node_count,
                edge_count=edge_count,
                status=edge_status,
                detail=edge_detail or load_detail,
            )
        )

    valid_counts = [
        row.edge_count for row in rows if row.status in VALID_EDGE_STATUSES
    ]
    detail_bins, detail_threshold = detail_histogram_bins(
        valid_counts,
        args.bins,
        args.detail_percentile,
    )
    log_bins = logarithmic_histogram_bins(valid_counts)
    summary = {
        "dataset_root": str(args.dataset_root),
        "splits": args.splits,
        "missing_split_dirs": missing_split_dirs,
        "filter": {"node_count_strictly_greater_than": args.min_node_count},
        "scanned_files": scanned_files,
        "selection_status_counts": dict(selection_status_counts),
        "selected_graphs": len(rows),
        "valid_edge_count_graphs": len(valid_counts),
        "edge_status_counts": dict(Counter(row.status for row in rows)),
        "edge_count": number_summary(valid_counts),
        "split_summaries": split_summary(rows),
        "detail_histogram": {
            "percentile": args.detail_percentile * 100,
            "inclusive_max_edge_count": detail_threshold,
        },
        "outputs": {
            "rows_csv": "large_graph_edge_counts.csv",
            "rows_txt": "large_graph_edge_counts.txt",
            "detail_histogram_csv": "large_graph_edge_count_histogram.csv",
            "detail_histogram_svg": "large_graph_edge_count_histogram.svg",
            "log_histogram_csv": "large_graph_edge_count_histogram_log.csv",
            "log_histogram_svg": "large_graph_edge_count_histogram_log.svg",
            "cdf_svg": "large_graph_edge_count_cdf.svg",
            "quantiles_csv": "large_graph_edge_count_quantiles.csv",
        },
    }

    (args.output_dir / "large_graph_edge_count_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_rows_csv(args.output_dir / "large_graph_edge_counts.csv", rows)
    write_rows_txt(args.output_dir / "large_graph_edge_counts.txt", rows)
    write_histogram_csv(
        args.output_dir / "large_graph_edge_count_histogram.csv",
        detail_bins,
    )
    write_histogram_svg(
        args.output_dir / "large_graph_edge_count_histogram.svg",
        detail_bins,
        f"Edge Count for Graphs with More Than {args.min_node_count} Nodes",
    )
    write_histogram_csv(
        args.output_dir / "large_graph_edge_count_histogram_log.csv",
        log_bins,
    )
    write_histogram_svg(
        args.output_dir / "large_graph_edge_count_histogram_log.svg",
        log_bins,
        f"Edge Count Long Tail (> {args.min_node_count} Nodes)",
        logarithmic_y=True,
    )
    write_cdf_svg(
        args.output_dir / "large_graph_edge_count_cdf.svg",
        cdf_points(valid_counts),
    )
    write_quantiles_csv(
        args.output_dir / "large_graph_edge_count_quantiles.csv",
        quantile_rows(valid_counts),
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"分析结果已写入: {args.output_dir.resolve()}")


def main() -> None:
    analyze(parse_args())


if __name__ == "__main__":
    main()
