#!/usr/bin/env python3
"""分析 cloud-ap-interface 中 process VLAN 是否等于 sw 与 trunk VLAN 的并集。"""

from __future__ import annotations

import argparse
import csv
import json
import re
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


DEFAULT_DATASET_ROOT = Path("datasets")
DEFAULT_OUTPUT_DIR = Path("/tmp/cloud_ap_interface_vlan_union_analysis")
DEFAULT_SPLIT = "all"
DEFAULT_CONFIG_FIELDS = ("configs",)
DEFAULT_PROGRESS_INTERVAL = 100
DEFAULT_MAX_RANGE_SIZE = 4096

DETAIL_FILE = "cloud_ap_interface_vlan_union_details.csv"
SUMMARY_FILE = "cloud_ap_interface_vlan_union_summary.json"
ERROR_FILE = "analysis_errors.csv"

REQUIRED_VLAN_FIELDS = (
    "process-vlan-id",
    "sw-vlan-id",
    "trunk-vlan",
)
RANGE_PATTERN = re.compile(r"^(\d+)\s*-\s*(\d+)$")
INTEGER_PATTERN = re.compile(r"^\d+$")


@dataclass(frozen=True)
class InterfaceLocation:
    split: str
    source_file: str
    node_index: int
    node_id: str
    config_field: str
    config_index: int
    interface_index: int


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
        "--max-range-size",
        type=int,
        default=DEFAULT_MAX_RANGE_SIZE,
        help="单个 VLAN 连续范围允许展开的最大数量，默认: %(default)s",
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
    if args.max_range_size <= 0:
        parser.error("--max-range-size 必须大于 0")
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


def split_vlan_tokens(text: str) -> list[str]:
    return [token.strip() for token in re.split(r"[,，]", text) if token.strip()]


def parse_vlan_token(token: str, max_range_size: int) -> tuple[set[int], str]:
    if INTEGER_PATTERN.fullmatch(token):
        return {int(token)}, ""
    match = RANGE_PATTERN.fullmatch(token)
    if match is None:
        return set(), f"invalid-token:{token}"
    start = int(match.group(1))
    end = int(match.group(2))
    if start > end:
        return set(), f"descending-range:{token}"
    size = end - start + 1
    if size > max_range_size:
        return set(), f"range-too-large:{token}"
    return set(range(start, end + 1)), ""


def parse_vlan_value(value: Any, max_range_size: int) -> tuple[set[int], list[str]]:
    vlan_ids: set[int] = set()
    errors: list[str] = []

    def visit(item: Any) -> None:
        if isinstance(item, bool) or item is None:
            errors.append(f"unsupported-value:{json.dumps(item)}")
            return
        if isinstance(item, int):
            vlan_ids.add(item)
            return
        if isinstance(item, float):
            if item.is_integer():
                vlan_ids.add(int(item))
            else:
                errors.append(f"non-integer-number:{item}")
            return
        if isinstance(item, str):
            tokens = split_vlan_tokens(item)
            if not tokens:
                errors.append("empty-string")
                return
            for token in tokens:
                parsed, error = parse_vlan_token(token, max_range_size)
                vlan_ids.update(parsed)
                if error:
                    errors.append(error)
            return
        if isinstance(item, list):
            if not item:
                errors.append("empty-list")
                return
            for child in item:
                visit(child)
            return
        errors.append(f"unsupported-type:{type(item).__name__}")

    visit(value)
    return vlan_ids, errors


def sorted_vlan_text(vlan_ids: set[int]) -> str:
    return ",".join(str(vlan_id) for vlan_id in sorted(vlan_ids))


def raw_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def interface_row(
    location: InterfaceLocation,
    interface: dict[str, Any],
    max_range_size: int,
) -> tuple[dict[str, Any] | None, str, dict[str, int]]:
    missing_fields = [
        field for field in REQUIRED_VLAN_FIELDS if field not in interface
    ]
    if missing_fields:
        return None, "missing-fields", {field: 1 for field in missing_fields}

    process_ids, process_errors = parse_vlan_value(
        interface["process-vlan-id"], max_range_size
    )
    sw_ids, sw_errors = parse_vlan_value(
        interface["sw-vlan-id"], max_range_size
    )
    trunk_ids, trunk_errors = parse_vlan_value(
        interface["trunk-vlan"], max_range_size
    )
    parse_errors = {
        "process-vlan-id": process_errors,
        "sw-vlan-id": sw_errors,
        "trunk-vlan": trunk_errors,
    }
    flattened_errors = [
        f"{field}:{error}"
        for field, errors in parse_errors.items()
        for error in errors
    ]
    expected_ids = sw_ids | trunk_ids
    extra_process_ids = process_ids - expected_ids
    missing_process_ids = expected_ids - process_ids
    status = "parse-error" if flattened_errors else (
        "matched" if process_ids == expected_ids else "mismatched"
    )
    row = {
        "split": location.split,
        "source_file": location.source_file,
        "node_index": location.node_index,
        "node_id": location.node_id,
        "config_field": location.config_field,
        "config_index": location.config_index,
        "interface_index": location.interface_index,
        "status": status,
        "is_equal": "" if flattened_errors else process_ids == expected_ids,
        "process_vlan_raw": raw_json(interface["process-vlan-id"]),
        "sw_vlan_raw": raw_json(interface["sw-vlan-id"]),
        "trunk_vlan_raw": raw_json(interface["trunk-vlan"]),
        "process_vlan_ids": sorted_vlan_text(process_ids),
        "sw_vlan_ids": sorted_vlan_text(sw_ids),
        "trunk_vlan_ids": sorted_vlan_text(trunk_ids),
        "sw_trunk_union_vlan_ids": sorted_vlan_text(expected_ids),
        "extra_process_vlan_ids": sorted_vlan_text(extra_process_ids),
        "missing_process_vlan_ids": sorted_vlan_text(missing_process_ids),
        "parse_errors": json.dumps(flattened_errors, ensure_ascii=False),
    }
    return row, status, {}


def analyze_graph(
    graph: dict[str, Any],
    split: str,
    source_file: str,
    config_fields: list[str],
    max_range_size: int,
) -> tuple[list[dict[str, Any]], Counter[str], Counter[str]]:
    rows: list[dict[str, Any]] = []
    counters: Counter[str] = Counter()
    missing_field_counts: Counter[str] = Counter()
    nodes = graph.get("nodes")
    if not isinstance(nodes, list):
        counters["files-with-nodes-not-list"] += 1
        return rows, counters, missing_field_counts

    counters["nodes"] += len(nodes)
    for node_index, node in enumerate(nodes):
        if not isinstance(node, dict):
            counters["invalid-node-items"] += 1
            continue
        node_id = str(node.get("id", f"<index:{node_index}>"))
        for config_field in config_fields:
            for config_index, config in object_items(node.get(config_field)):
                cloud_interfaces = config.get("cloud-ap-interfaces")
                if not isinstance(cloud_interfaces, dict):
                    continue
                counters["cloud-ap-interfaces-configs"] += 1
                interface_container = cloud_interfaces.get("cloud-ap-interface")
                found_interface = False
                for interface_index, interface in object_items(interface_container):
                    found_interface = True
                    counters["cloud-ap-interface-objects"] += 1
                    location = InterfaceLocation(
                        split=split,
                        source_file=source_file,
                        node_index=node_index,
                        node_id=node_id,
                        config_field=config_field,
                        config_index=config_index,
                        interface_index=interface_index,
                    )
                    row, status, missing = interface_row(
                        location,
                        interface,
                        max_range_size,
                    )
                    counters[status] += 1
                    missing_field_counts.update(missing)
                    if row is not None:
                        rows.append(row)
                if not found_interface:
                    counters["missing-or-invalid-interface-container"] += 1
    return rows, counters, missing_field_counts


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
    all_rows: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    total_counters: Counter[str] = Counter()
    total_missing_fields: Counter[str] = Counter()
    by_split: dict[str, dict[str, Any]] = {}

    for split in splits:
        files = iter_json_files(dataset_root, split)
        counters: Counter[str] = Counter()
        missing_fields: Counter[str] = Counter()
        split_error_count = 0
        started_at = time.time()
        print(f"[{split}] 开始分析：{len(files)} 个 JSON", flush=True)

        for index, path in enumerate(files, start=1):
            source_file = str(path.relative_to(dataset_root / split))
            try:
                graph = load_json_object(path)
                rows, graph_counters, graph_missing_fields = analyze_graph(
                    graph,
                    split,
                    source_file,
                    args.config_fields,
                    args.max_range_size,
                )
                all_rows.extend(rows)
                counters.update(graph_counters)
                missing_fields.update(graph_missing_fields)
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
                compared = counters["matched"] + counters["mismatched"]
                print(
                    f"[{split}] {index}/{len(files)}，有效比较 {compared}，"
                    f"匹配 {counters['matched']}，不匹配 {counters['mismatched']}，"
                    f"预计剩余 {eta:.1f} 秒",
                    flush=True,
                )

        compared = counters["matched"] + counters["mismatched"]
        by_split[split] = {
            "input_files": len(files),
            "valid_files": counters["valid-files"],
            "invalid_files": split_error_count,
            "nodes": counters["nodes"],
            "cloud_ap_interfaces_configs": counters[
                "cloud-ap-interfaces-configs"
            ],
            "cloud_ap_interface_objects": counters[
                "cloud-ap-interface-objects"
            ],
            "complete_field_interfaces": (
                counters["matched"]
                + counters["mismatched"]
                + counters["parse-error"]
            ),
            "compared_interfaces": compared,
            "matched_interfaces": counters["matched"],
            "mismatched_interfaces": counters["mismatched"],
            "parse_error_interfaces": counters["parse-error"],
            "incomplete_field_interfaces": counters["missing-fields"],
            "missing_field_counts": dict(sorted(missing_fields.items())),
            "match_ratio": round(
                counters["matched"] / compared if compared else 0.0,
                8,
            ),
            "invalid_node_items": counters["invalid-node-items"],
            "files_with_nodes_not_list": counters["files-with-nodes-not-list"],
            "missing_or_invalid_interface_containers": counters[
                "missing-or-invalid-interface-container"
            ],
        }
        total_counters.update(counters)
        total_missing_fields.update(missing_fields)

    compared_total = total_counters["matched"] + total_counters["mismatched"]
    summary = {
        "dataset_root": str(dataset_root),
        "output_dir": str(output_dir),
        "splits": splits,
        "config_fields": args.config_fields,
        "required_vlan_fields": list(REQUIRED_VLAN_FIELDS),
        "comparison_rule": (
            "process-vlan-id == union(sw-vlan-id, trunk-vlan); "
            "only interfaces containing all three fields are candidates"
        ),
        "max_range_size": args.max_range_size,
        "input_files": sum(item["input_files"] for item in by_split.values()),
        "valid_files": total_counters["valid-files"],
        "invalid_files": len(errors),
        "cloud_ap_interface_objects": total_counters[
            "cloud-ap-interface-objects"
        ],
        "complete_field_interfaces": (
            total_counters["matched"]
            + total_counters["mismatched"]
            + total_counters["parse-error"]
        ),
        "compared_interfaces": compared_total,
        "matched_interfaces": total_counters["matched"],
        "mismatched_interfaces": total_counters["mismatched"],
        "parse_error_interfaces": total_counters["parse-error"],
        "incomplete_field_interfaces": total_counters["missing-fields"],
        "missing_field_counts": dict(sorted(total_missing_fields.items())),
        "match_ratio": round(
            total_counters["matched"] / compared_total if compared_total else 0.0,
            8,
        ),
        "by_split": by_split,
    }

    detail_fields = [
        "split",
        "source_file",
        "node_index",
        "node_id",
        "config_field",
        "config_index",
        "interface_index",
        "status",
        "is_equal",
        "process_vlan_raw",
        "sw_vlan_raw",
        "trunk_vlan_raw",
        "process_vlan_ids",
        "sw_vlan_ids",
        "trunk_vlan_ids",
        "sw_trunk_union_vlan_ids",
        "extra_process_vlan_ids",
        "missing_process_vlan_ids",
        "parse_errors",
    ]
    write_csv(output_dir / DETAIL_FILE, detail_fields, all_rows)
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
