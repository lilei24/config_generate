#!/usr/bin/env python3
"""筛选节点数超过指定阈值的图，将节点数和 links 数量写入一个 CSV。"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Iterable


DEFAULT_DATASET_ROOT = Path("datasets")
DEFAULT_OUTPUT_DIR = Path("/tmp/large_graph_edge_count_analysis")
DEFAULT_MIN_NODE_COUNT = 100
OUTPUT_FILE = "large_graph_node_link_counts.csv"


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
        help="CSV 输出目录，默认: %(default)s",
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
    args = parser.parse_args()
    if args.min_node_count < 0:
        parser.error("--min-node-count 不能小于 0")
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


def load_graph(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - 坏文件计数后继续处理。
        return None
    return value if isinstance(value, dict) else None


def analyze(args: argparse.Namespace) -> None:
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output_path = args.output_dir / OUTPUT_FILE
    rows: list[dict[str, object]] = []
    scanned_files = 0
    unreadable_files = 0
    invalid_nodes_files = 0
    invalid_links_files = 0

    for split, path in iter_json_files(args.dataset_root, args.splits):
        scanned_files += 1
        graph = load_graph(path)
        if graph is None:
            unreadable_files += 1
            continue

        nodes = graph.get("nodes")
        if not isinstance(nodes, list):
            invalid_nodes_files += 1
            continue
        node_count = len(nodes)
        if node_count <= args.min_node_count:
            continue

        links = graph.get("links")
        if isinstance(links, list):
            link_count: int | str = len(links)
        else:
            link_count = ""
            invalid_links_files += 1

        rows.append(
            {
                "split": split,
                "file": str(path.relative_to(args.dataset_root)),
                "node_count": node_count,
                "link_count": link_count,
            }
        )

    with output_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=["split", "file", "node_count", "link_count"],
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"扫描 JSON 文件: {scanned_files}")
    print(f"节点数 > {args.min_node_count} 的文件: {len(rows)}")
    print(f"无法读取或顶层不是对象: {unreadable_files}")
    print(f"nodes 缺失或不是数组: {invalid_nodes_files}")
    print(f"入选文件中 links 缺失或不是数组: {invalid_links_files}")
    print(f"CSV: {output_path.resolve()}")


def main() -> None:
    analyze(parse_args())


if __name__ == "__main__":
    main()
