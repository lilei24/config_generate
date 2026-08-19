#!/usr/bin/env python3
"""统计 devicevlan-business 四类配置所在节点的物理设备类型分布。"""

from __future__ import annotations

import argparse
import csv
import json
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


DEFAULT_DATASET_ROOT = Path("datasets")
DEFAULT_OUTPUT_DIR = Path("/tmp/devicevlan_business_type_analysis")
DEFAULT_SPLIT = "all"
DEFAULT_CONFIG_FIELDS = ("configs",)
DEFAULT_PROGRESS_INTERVAL = 100

TARGET_CONFIG_KEYS = (
    "auto-vlan",
    "manual-vlan",
    "vlan-add",
    "vlan-del",
)
MISSING_DEVICE_TYPE = "<missing>"

DISTRIBUTION_FILE = "devicevlan_business_type_distribution.csv"
NODE_DETAIL_FILE = "devicevlan_business_node_details.csv"
SUMMARY_FILE = "devicevlan_business_type_summary.json"
ERROR_FILE = "analysis_errors.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "dataset_root",
        nargs="?",
        type=Path,
        default=DEFAULT_DATASET_ROOT,
        help="数据集根目录，目录下应包含 train/val，默认: %(default)s",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="结果输出目录，默认: %(default)s",
    )
    parser.add_argument(
        "--split",
        choices=["train", "val", "all"],
        default=DEFAULT_SPLIT,
        help="分析 train、val 或全部数据，默认: %(default)s",
    )
    parser.add_argument(
        "--config-fields",
        nargs="+",
        default=list(DEFAULT_CONFIG_FIELDS),
        help="需要扫描的节点配置字段，默认只扫描 configs",
    )
    parser.add_argument(
        "--progress-interval",
        type=int,
        default=DEFAULT_PROGRESS_INTERVAL,
        help="每处理 N 个文件打印一次进度，0 表示关闭，默认: %(default)s",
    )
    args = parser.parse_args()
    if not args.config_fields or any(not field for field in args.config_fields):
        parser.error("--config-fields 至少需要一个非空字段名")
    if len(args.config_fields) != len(set(args.config_fields)):
        parser.error("--config-fields 不能包含重复字段名")
    if args.progress_interval < 0:
        parser.error("--progress-interval 不能小于 0")
    return args


def iter_json_files(dataset_root: Path, split: str) -> list[Path]:
    split_root = dataset_root / split
    if not split_root.is_dir():
        raise FileNotFoundError(f"数据划分目录不存在: {split_root}")
    return sorted(path for path in split_root.rglob("*.json") if path.is_file())


def load_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON 顶层必须是对象，实际为 {type(value).__name__}")
    return value


def object_items(value: Any) -> Iterable[tuple[int, dict[str, Any]]]:
    if isinstance(value, dict):
        yield 0, value
    elif isinstance(value, list):
        for index, item in enumerate(value):
            if isinstance(item, dict):
                yield index, item


def device_type(node: dict[str, Any]) -> str:
    device = node.get("devices")
    if not isinstance(device, dict):
        device = node.get("device")
    if not isinstance(device, dict):
        return MISSING_DEVICE_TYPE
    value = device.get("TYPE")
    if value is None or isinstance(value, (dict, list)):
        return MISSING_DEVICE_TYPE
    text = str(value).strip()
    return text or MISSING_DEVICE_TYPE


def find_target_keys(
    node: dict[str, Any],
    config_fields: list[str],
) -> tuple[set[str], int]:
    """返回节点出现的目标字段集合及 devicevlan-business 对象数量。"""

    found: set[str] = set()
    business_object_count = 0
    for config_field in config_fields:
        for _, config_item in object_items(node.get(config_field)):
            business_container = config_item.get("devicevlan-business")
            for _, business in object_items(business_container):
                business_object_count += 1
                found.update(key for key in TARGET_CONFIG_KEYS if key in business)
    return found, business_object_count


def analyze_graph(
    graph: dict[str, Any],
    split: str,
    source_file: str,
    config_fields: list[str],
) -> tuple[
    list[dict[str, Any]],
    dict[str, Counter[str]],
    Counter[str],
]:
    details: list[dict[str, Any]] = []
    distributions = {key: Counter() for key in TARGET_CONFIG_KEYS}
    counters: Counter[str] = Counter()
    nodes = graph.get("nodes")
    if not isinstance(nodes, list):
        counters["files-with-nodes-not-list"] += 1
        return details, distributions, counters

    counters["nodes"] += len(nodes)
    for node_index, node in enumerate(nodes):
        if not isinstance(node, dict):
            counters["invalid-node-items"] += 1
            continue
        found_keys, business_object_count = find_target_keys(node, config_fields)
        counters["devicevlan-business-objects"] += business_object_count
        if not found_keys:
            continue

        node_type = device_type(node)
        node_id_value = node.get("id")
        node_id = (
            str(node_id_value)
            if node_id_value is not None
            else f"<index:{node_index}>"
        )
        counters["nodes-with-target-config"] += 1
        for key in found_keys:
            distributions[key][node_type] += 1
            counters[f"nodes-with-{key}"] += 1
        details.append(
            {
                "split": split,
                "source_file": source_file,
                "node_index": node_index,
                "node_id": node_id,
                "device_type": node_type,
                "auto_vlan_present": "auto-vlan" in found_keys,
                "manual_vlan_present": "manual-vlan" in found_keys,
                "vlan_add_present": "vlan-add" in found_keys,
                "vlan_del_present": "vlan-del" in found_keys,
            }
        )
    return details, distributions, counters


def update_distributions(
    target: dict[str, Counter[str]],
    source: dict[str, Counter[str]],
) -> None:
    for key in TARGET_CONFIG_KEYS:
        target[key].update(source[key])


def ordered_counts(counter: Counter[str]) -> dict[str, int]:
    return dict(sorted(counter.items(), key=lambda item: (-item[1], item[0])))


def distribution_summary(
    distributions: dict[str, Counter[str]],
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for key in TARGET_CONFIG_KEYS:
        counts = distributions[key]
        total = sum(counts.values())
        result[key] = {
            "node_count": total,
            "device_type_counts": ordered_counts(counts),
            "device_type_ratios": {
                device_type_name: round(count / total if total else 0.0, 8)
                for device_type_name, count in sorted(
                    counts.items(),
                    key=lambda item: (-item[1], item[0]),
                )
            },
        }
    return result


def distribution_rows(
    scope: str,
    distributions: dict[str, Counter[str]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in TARGET_CONFIG_KEYS:
        total = sum(distributions[key].values())
        for type_name, count in sorted(
            distributions[key].items(),
            key=lambda item: (-item[1], item[0]),
        ):
            rows.append(
                {
                    "scope": scope,
                    "config_name": f"devicevlan-business.{key}",
                    "device_type": type_name,
                    "node_count": count,
                    "config_total_node_count": total,
                    "ratio_within_config": round(
                        count / total if total else 0.0,
                        8,
                    ),
                }
            )
    return rows


def write_csv(
    path: Path,
    fieldnames: list[str],
    rows: list[dict[str, Any]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def run(args: argparse.Namespace) -> dict[str, Any]:
    dataset_root = args.dataset_root.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    splits = ["train", "val"] if args.split == "all" else [args.split]

    all_details: list[dict[str, Any]] = []
    all_distributions = {key: Counter() for key in TARGET_CONFIG_KEYS}
    distribution_csv_rows: list[dict[str, Any]] = []
    total_counters: Counter[str] = Counter()
    errors: list[dict[str, str]] = []
    by_split: dict[str, dict[str, Any]] = {}

    for split in splits:
        files = iter_json_files(dataset_root, split)
        split_distributions = {key: Counter() for key in TARGET_CONFIG_KEYS}
        counters: Counter[str] = Counter()
        split_error_count = 0
        started_at = time.time()
        print(f"[{split}] 开始分析：{len(files)} 个 JSON", flush=True)

        for index, path in enumerate(files, start=1):
            source_file = str(path.relative_to(dataset_root / split))
            try:
                graph = load_json_object(path)
                details, distributions, graph_counters = analyze_graph(
                    graph,
                    split,
                    source_file,
                    args.config_fields,
                )
                all_details.extend(details)
                update_distributions(split_distributions, distributions)
                counters.update(graph_counters)
                counters["valid-files"] += 1
            except Exception as error:  # noqa: BLE001 - 坏文件单独记录并继续。
                split_error_count += 1
                errors.append(
                    {
                        "split": split,
                        "source_file": source_file,
                        "error": f"{type(error).__name__}: {error}",
                    }
                )

            if args.progress_interval > 0 and (
                index % args.progress_interval == 0 or index == len(files)
            ):
                elapsed = max(time.time() - started_at, 0.001)
                speed = index / elapsed
                eta = (len(files) - index) / speed if speed else 0.0
                print(
                    f"[{split}] {index}/{len(files)}，"
                    f"命中节点 {counters['nodes-with-target-config']}，"
                    f"错误 {split_error_count}，预计剩余 {eta:.1f} 秒",
                    flush=True,
                )

        update_distributions(all_distributions, split_distributions)
        distribution_csv_rows.extend(
            distribution_rows(split, split_distributions)
        )
        total_counters.update(counters)
        by_split[split] = {
            "input_files": len(files),
            "valid_files": counters["valid-files"],
            "invalid_files": split_error_count,
            "nodes": counters["nodes"],
            "nodes_with_target_config": counters["nodes-with-target-config"],
            "devicevlan_business_objects": counters[
                "devicevlan-business-objects"
            ],
            "invalid_node_items": counters["invalid-node-items"],
            "files_with_nodes_not_list": counters["files-with-nodes-not-list"],
            "config_statistics": distribution_summary(split_distributions),
        }

    distribution_csv_rows.extend(
        distribution_rows("all", all_distributions)
    )
    summary = {
        "dataset_root": str(dataset_root),
        "output_dir": str(output_dir),
        "splits": splits,
        "config_fields": args.config_fields,
        "target_config_keys": [
            f"devicevlan-business.{key}" for key in TARGET_CONFIG_KEYS
        ],
        "counting_rule": (
            "each node is counted at most once per target config key; "
            "key presence is counted regardless of its value"
        ),
        "device_type_field": "nodes[].devices.TYPE or nodes[].device.TYPE",
        "input_files": sum(item["input_files"] for item in by_split.values()),
        "valid_files": total_counters["valid-files"],
        "invalid_files": len(errors),
        "nodes": total_counters["nodes"],
        "nodes_with_target_config": total_counters["nodes-with-target-config"],
        "config_statistics": distribution_summary(all_distributions),
        "by_split": by_split,
    }

    write_csv(
        output_dir / DISTRIBUTION_FILE,
        [
            "scope",
            "config_name",
            "device_type",
            "node_count",
            "config_total_node_count",
            "ratio_within_config",
        ],
        distribution_csv_rows,
    )
    write_csv(
        output_dir / NODE_DETAIL_FILE,
        [
            "split",
            "source_file",
            "node_index",
            "node_id",
            "device_type",
            "auto_vlan_present",
            "manual_vlan_present",
            "vlan_add_present",
            "vlan_del_present",
        ],
        all_details,
    )
    write_csv(
        output_dir / ERROR_FILE,
        ["split", "source_file", "error"],
        errors,
    )
    (output_dir / SUMMARY_FILE).write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return summary


if __name__ == "__main__":
    run(parse_args())
