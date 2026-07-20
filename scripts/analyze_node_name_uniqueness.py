#!/usr/bin/env python3
"""分析原始拓扑数据中 devices.NAME 能否唯一标识节点。

主要关注同一站点（单个 JSON）内部：同一个非空节点名称是否对应多个不同
node.id。跨站点重名也会统计，但由于站点名称可以提供作用域，因此不会直接判定
站点内节点标识失效。
"""

from __future__ import annotations

import argparse
import csv
import json
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


DEFAULT_DATASET_ROOT = Path("datasets")
DEFAULT_OUTPUT_DIR = Path("/tmp/node_name_uniqueness_analysis")
DEFAULT_PROGRESS_INTERVAL = 50
STATISTICS_FILE = "node_name_uniqueness_statistics.json"
WITHIN_GRAPH_DUPLICATES_FILE = "within_graph_duplicate_node_names.csv"
CROSS_GRAPH_REUSE_FILE = "cross_graph_reused_node_names.csv"
MISSING_NAME = "<missing>"


@dataclass
class GraphNameResult:
    split: str
    source_file: str
    status: str
    detail: str
    raw_node_records: int
    valid_nodes: int
    named_nodes: int
    missing_name_nodes: int
    duplicate_id_records: int
    duplicate_names: dict[str, list[str]]
    node_names: dict[str, str]


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


def get_device_name(node: dict[str, Any]) -> str:
    device = node.get("devices")
    if not isinstance(device, dict):
        device = node.get("device")
    if not isinstance(device, dict):
        return MISSING_NAME
    value = device.get("NAME")
    if value is None:
        return MISSING_NAME
    name = str(value).strip()
    return name if name else MISSING_NAME


def analyze_graph(
    dataset_root: Path,
    split: str,
    path: Path,
) -> GraphNameResult:
    source_file = str(path.relative_to(dataset_root))
    try:
        graph = json.loads(path.read_text(encoding="utf-8"))
    except Exception as error:  # noqa: BLE001 - 坏文件需要记录并继续分析。
        return GraphNameResult(
            split=split,
            source_file=source_file,
            status="bad_json",
            detail=f"{type(error).__name__}: {error}",
            raw_node_records=0,
            valid_nodes=0,
            named_nodes=0,
            missing_name_nodes=0,
            duplicate_id_records=0,
            duplicate_names={},
            node_names={},
        )
    if not isinstance(graph, dict) or not isinstance(graph.get("nodes"), list):
        actual_type = type(graph.get("nodes") if isinstance(graph, dict) else graph).__name__
        return GraphNameResult(
            split=split,
            source_file=source_file,
            status="nodes_not_list",
            detail=f"actual_type={actual_type}",
            raw_node_records=0,
            valid_nodes=0,
            named_nodes=0,
            missing_name_nodes=0,
            duplicate_id_records=0,
            duplicate_names={},
            node_names={},
        )

    nodes = graph["nodes"]
    node_names: dict[str, str] = {}
    invalid_node_records = 0
    duplicate_id_records = 0
    for node in nodes:
        if not isinstance(node, dict) or node.get("id") is None:
            invalid_node_records += 1
            continue
        node_id = str(node["id"])
        if node_id in node_names:
            duplicate_id_records += 1
            continue
        node_names[node_id] = get_device_name(node)

    ids_by_name: dict[str, list[str]] = defaultdict(list)
    for node_id, name in node_names.items():
        if name != MISSING_NAME:
            ids_by_name[name].append(node_id)
    duplicate_names = {
        name: sorted(node_ids)
        for name, node_ids in ids_by_name.items()
        if len(node_ids) > 1
    }
    missing_name_nodes = sum(name == MISSING_NAME for name in node_names.values())
    details: list[str] = []
    if invalid_node_records:
        details.append(f"invalid_node_records={invalid_node_records}")
    if duplicate_id_records:
        details.append(f"duplicate_id_records={duplicate_id_records}")
    return GraphNameResult(
        split=split,
        source_file=source_file,
        status="ok",
        detail="; ".join(details),
        raw_node_records=len(nodes),
        valid_nodes=len(node_names),
        named_nodes=len(node_names) - missing_name_nodes,
        missing_name_nodes=missing_name_nodes,
        duplicate_id_records=duplicate_id_records,
        duplicate_names=duplicate_names,
        node_names=node_names,
    )


def build_scope_summary(results: list[GraphNameResult]) -> dict[str, Any]:
    valid_results = [result for result in results if result.status == "ok"]
    duplicate_groups = sum(len(result.duplicate_names) for result in valid_results)
    nodes_in_duplicate_groups = sum(
        len(node_ids)
        for result in valid_results
        for node_ids in result.duplicate_names.values()
    )
    duplicate_excess_nodes = sum(
        len(node_ids) - 1
        for result in valid_results
        for node_ids in result.duplicate_names.values()
    )
    missing_name_nodes = sum(result.missing_name_nodes for result in valid_results)
    graphs_with_duplicate_names = sum(
        bool(result.duplicate_names) for result in valid_results
    )
    graphs_with_missing_names = sum(
        result.missing_name_nodes > 0 for result in valid_results
    )
    return {
        "input_files": len(results),
        "analyzed_graphs": len(valid_results),
        "skipped_files": len(results) - len(valid_results),
        "raw_node_records": sum(result.raw_node_records for result in valid_results),
        "valid_nodes": sum(result.valid_nodes for result in valid_results),
        "named_nodes": sum(result.named_nodes for result in valid_results),
        "missing_name_nodes": missing_name_nodes,
        "duplicate_id_records": sum(
            result.duplicate_id_records for result in valid_results
        ),
        "graphs_with_duplicate_node_names": graphs_with_duplicate_names,
        "graphs_with_missing_node_names": graphs_with_missing_names,
        "within_graph_duplicate_name_groups": duplicate_groups,
        "within_graph_nodes_in_duplicate_groups": nodes_in_duplicate_groups,
        "within_graph_duplicate_excess_nodes": duplicate_excess_nodes,
        "all_named_nodes_unique_within_graph": duplicate_groups == 0,
        "all_nodes_have_non_missing_unique_names_within_graph": (
            duplicate_groups == 0 and missing_name_nodes == 0
        ),
    }


def build_cross_graph_reuse(
    results: list[GraphNameResult],
) -> list[dict[str, Any]]:
    locations_by_name: dict[str, list[dict[str, str]]] = defaultdict(list)
    for result in results:
        if result.status != "ok":
            continue
        for node_id, name in result.node_names.items():
            if name == MISSING_NAME:
                continue
            locations_by_name[name].append(
                {
                    "split": result.split,
                    "source_file": result.source_file,
                    "node_id": node_id,
                }
            )

    reused: list[dict[str, Any]] = []
    for name, locations in locations_by_name.items():
        graph_count = len(
            {(item["split"], item["source_file"]) for item in locations}
        )
        if graph_count <= 1:
            continue
        reused.append(
            {
                "node_name": name,
                "distinct_graph_count": graph_count,
                "node_occurrence_count": len(locations),
                "locations": sorted(
                    locations,
                    key=lambda item: (
                        item["split"],
                        item["source_file"],
                        item["node_id"],
                    ),
                ),
            }
        )
    return sorted(
        reused,
        key=lambda item: (
            -item["distinct_graph_count"],
            -item["node_occurrence_count"],
            item["node_name"],
        ),
    )


def write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def print_summary(summary: dict[str, Any], cross_graph_reuse_count: int) -> None:
    print(f"\n{'=' * 68}")
    print("节点名称唯一性统计完成")
    print(f"{'=' * 68}")
    print(
        f"有效图：{summary['analyzed_graphs']}，有效节点：{summary['valid_nodes']}，"
        f"缺失名称：{summary['missing_name_nodes']}"
    )
    print(
        f"站点内存在重名的图：{summary['graphs_with_duplicate_node_names']}，"
        f"重名组：{summary['within_graph_duplicate_name_groups']}，"
        f"涉及节点：{summary['within_graph_nodes_in_duplicate_groups']}"
    )
    print(f"跨站点重复使用的名称：{cross_graph_reuse_count}")
    if summary["all_nodes_have_non_missing_unique_names_within_graph"]:
        print("结论：所有节点均具有非空且在站点内唯一的 NAME。")
    elif summary["all_named_nodes_unique_within_graph"]:
        print("结论：已有 NAME 在站点内唯一，但部分节点缺少 NAME。")
    else:
        print("结论：存在同一站点内不同节点使用相同 NAME，NAME 不能单独作为唯一标识。")
    print(f"{'=' * 68}")


def run_analysis(args: argparse.Namespace) -> None:
    dataset_root = args.dataset_root.resolve()
    output_dir = args.output_dir.resolve()
    splits = ["train", "val"] if args.split == "all" else [args.split]
    results: list[GraphNameResult] = []

    for split in splits:
        files = list(iter_json_files(dataset_root, [split]))
        started_at = time.time()
        print(f"[{split}] 开始分析：{len(files)} 个文件", flush=True)
        for index, (_, path) in enumerate(files, start=1):
            results.append(analyze_graph(dataset_root, split, path))
            if args.progress_interval > 0 and (
                index % args.progress_interval == 0 or index == len(files)
            ):
                elapsed = max(0.001, time.time() - started_at)
                speed = index / elapsed
                eta = (len(files) - index) / speed if speed else 0.0
                print(
                    f"[{split}] {index}/{len(files)}，{speed:.2f} 文件/秒，"
                    f"预计剩余 {eta:.1f} 秒",
                    flush=True,
                )

    overall = build_scope_summary(results)
    cross_graph_reuse = build_cross_graph_reuse(results)
    per_file = [
        {
            "split": result.split,
            "source_file": result.source_file,
            "status": result.status,
            "detail": result.detail,
            "raw_node_records": result.raw_node_records,
            "valid_nodes": result.valid_nodes,
            "named_nodes": result.named_nodes,
            "missing_name_nodes": result.missing_name_nodes,
            "duplicate_id_records": result.duplicate_id_records,
            "duplicate_name_group_count": len(result.duplicate_names),
            "nodes_in_duplicate_name_groups": sum(
                len(node_ids) for node_ids in result.duplicate_names.values()
            ),
            "all_named_nodes_unique": not result.duplicate_names,
            "all_nodes_have_non_missing_unique_names": (
                not result.duplicate_names and result.missing_name_nodes == 0
            ),
            "duplicate_names": [
                {
                    "node_name": name,
                    "distinct_node_count": len(node_ids),
                    "node_ids": node_ids,
                }
                for name, node_ids in sorted(result.duplicate_names.items())
            ],
        }
        for result in results
    ]
    output = {
        "summary": {
            "definition": {
                "node_identity": "nodes[].id",
                "node_name": "nodes[].devices.NAME; nodes[].device.NAME is also supported",
                "comparison": "trimmed, case-sensitive exact string comparison",
                "missing_name": MISSING_NAME,
                "within_graph_duplicate": (
                    "one non-missing NAME maps to multiple distinct node ids in one JSON"
                ),
                "cross_graph_reuse": (
                    "one NAME appears in multiple JSON files; site scope can still disambiguate it"
                ),
            },
            "dataset_root": str(dataset_root),
            "splits": splits,
            "overall": {
                **overall,
                "cross_graph_reused_name_groups": len(cross_graph_reuse),
            },
            "by_split": {
                split: build_scope_summary(
                    [result for result in results if result.split == split]
                )
                for split in splits
            },
        },
        "per_file": per_file,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / STATISTICS_FILE).write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    within_graph_rows = []
    for result in results:
        for name, node_ids in sorted(result.duplicate_names.items()):
            within_graph_rows.append(
                {
                    "split": result.split,
                    "source_file": result.source_file,
                    "node_name": name,
                    "distinct_node_count": len(node_ids),
                    "node_ids": json.dumps(node_ids, ensure_ascii=False),
                }
            )
    write_csv(
        output_dir / WITHIN_GRAPH_DUPLICATES_FILE,
        ["split", "source_file", "node_name", "distinct_node_count", "node_ids"],
        within_graph_rows,
    )
    write_csv(
        output_dir / CROSS_GRAPH_REUSE_FILE,
        [
            "node_name",
            "distinct_graph_count",
            "node_occurrence_count",
            "locations",
        ],
        (
            {
                **{key: value for key, value in item.items() if key != "locations"},
                "locations": json.dumps(item["locations"], ensure_ascii=False),
            }
            for item in cross_graph_reuse
        ),
    )
    print_summary(overall, len(cross_graph_reuse))
    print(f"结果目录：{output_dir}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="统计 devices.NAME 在站点内和跨站点是否唯一。"
    )
    parser.add_argument(
        "dataset_root",
        nargs="?",
        type=Path,
        default=DEFAULT_DATASET_ROOT,
        help=f"数据集根目录，包含 train/ 和 val/。默认：{DEFAULT_DATASET_ROOT}",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"统计结果目录。默认：{DEFAULT_OUTPUT_DIR}",
    )
    parser.add_argument(
        "--split",
        choices=["train", "val", "all"],
        default="all",
        help="分析 train、val 或全部数据。默认：all",
    )
    parser.add_argument(
        "--progress-interval",
        type=int,
        default=DEFAULT_PROGRESS_INTERVAL,
        help="每处理 N 个文件打印一次进度，0 表示关闭。默认：%(default)s",
    )
    args = parser.parse_args()
    if args.progress_interval < 0:
        parser.error("--progress-interval 不能小于 0")
    return args


if __name__ == "__main__":
    run_analysis(parse_args())
