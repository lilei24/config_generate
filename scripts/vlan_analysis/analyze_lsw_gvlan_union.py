#!/usr/bin/env python3
"""分析节点 lsw-gvlan-business 是否等于接口 VLAN 配置的并集。"""

from __future__ import annotations

import argparse
import csv
import json
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


DEFAULT_DATASET_ROOT = Path("datasets")
DEFAULT_OUTPUT_DIR = Path("/tmp/lsw_gvlan_union_analysis")
DEFAULT_SPLIT = "all"
DEFAULT_CONFIG_FIELDS = ("configs",)
DEFAULT_PROGRESS_INTERVAL = 100
DEFAULT_MAX_RANGE_SIZE = 4096

DETAIL_FILE = "lsw_gvlan_union_details.csv"
SUMMARY_FILE = "lsw_gvlan_union_summary.json"
ERROR_FILE = "analysis_errors.csv"

RANGE_PATTERN = re.compile(r"^(\d+)\s*-\s*(\d+)$")
INTEGER_PATTERN = re.compile(r"^\d+$")


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
            tokens = [
                token.strip()
                for token in re.split(r"[,，]", item)
                if token.strip()
            ]
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


def collect_named_values(
    value: Any,
    field_name: str,
    path: str,
) -> list[tuple[str, Any]]:
    """递归收集对象中名称完全匹配的字段值。"""

    values: list[tuple[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            if key == field_name:
                values.append((child_path, child))
            else:
                values.extend(collect_named_values(child, field_name, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            values.extend(
                collect_named_values(child, field_name, f"{path}[{index}]")
            )
    return values


def parse_named_values(
    values: list[tuple[str, Any]],
    max_range_size: int,
) -> tuple[set[int], list[str]]:
    vlan_ids: set[int] = set()
    errors: list[str] = []
    for path, value in values:
        parsed, value_errors = parse_vlan_value(value, max_range_size)
        vlan_ids.update(parsed)
        errors.extend(f"{path}:{error}" for error in value_errors)
    return vlan_ids, errors


def sorted_vlan_text(vlan_ids: set[int]) -> str:
    return ",".join(str(vlan_id) for vlan_id in sorted(vlan_ids))


def raw_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def contains_all_vlan(value: Any) -> bool:
    """判断 VLAN 表达式中是否包含独立的 all 通配值。"""

    if isinstance(value, str):
        return any(
            token.strip().lower() == "all"
            for token in re.split(r"[,，]", value)
        )
    if isinstance(value, list):
        return any(contains_all_vlan(item) for item in value)
    if isinstance(value, dict):
        return any(contains_all_vlan(item) for item in value.values())
    return False


def analyze_node(
    node: dict[str, Any],
    config_fields: list[str],
    max_range_size: int,
) -> tuple[dict[str, Any] | None, Counter[str]]:
    counters: Counter[str] = Counter()
    target_containers: list[Any] = []
    allow_values: list[tuple[str, Any]] = []
    interface_vlan_values: list[tuple[str, Any]] = []

    for config_field in config_fields:
        for config_index, config in object_items(node.get(config_field)):
            business_container = config.get("lsw-interfaces-business")
            for business_index, business in object_items(business_container):
                counters["lsw-interfaces-business-objects"] += 1
                base_path = (
                    f"{config_field}[{config_index}]."
                    f"lsw-interfaces-business[{business_index}]"
                )
                if "lsw-gvlan-business" in business:
                    target_containers.append(business["lsw-gvlan-business"])
                if "lsw-interface" in business:
                    allow_values.extend(
                        collect_named_values(
                            business["lsw-interface"],
                            "allow-through-vlan",
                            f"{base_path}.lsw-interface",
                        )
                    )
                if "lsw-interfaces" in business:
                    interface_vlan_values.extend(
                        collect_named_values(
                            business["lsw-interfaces"],
                            "vlan-id",
                            f"{base_path}.lsw-interfaces",
                        )
                    )

    if any(contains_all_vlan(value) for _, value in allow_values):
        counters["nodes-skipped-allow-through-vlan-all"] += 1
        return None, counters
    if not target_containers:
        counters["nodes-without-lsw-gvlan-business"] += 1
        return None, counters

    target_values: list[tuple[str, Any]] = []
    for target_index, container in enumerate(target_containers):
        if isinstance(container, (dict, list)):
            target_values.extend(
                collect_named_values(
                    container,
                    "vlan",
                    f"lsw-gvlan-business[{target_index}]",
                )
            )
        else:
            target_values.append(
                (f"lsw-gvlan-business[{target_index}]", container)
            )

    target_ids, target_errors = parse_named_values(
        target_values,
        max_range_size,
    )
    allow_ids, allow_errors = parse_named_values(
        allow_values,
        max_range_size,
    )
    interface_vlan_ids, interface_errors = parse_named_values(
        interface_vlan_values,
        max_range_size,
    )
    parse_errors = [
        *(f"lsw-gvlan-business:{error}" for error in target_errors),
        *(f"allow-through-vlan:{error}" for error in allow_errors),
        *(f"lsw-interfaces.vlan-id:{error}" for error in interface_errors),
    ]
    expected_ids = allow_ids | interface_vlan_ids
    extra_target_ids = target_ids - expected_ids
    missing_target_ids = expected_ids - target_ids
    status = "parse-error" if parse_errors else (
        "matched" if target_ids == expected_ids else "mismatched"
    )
    target_raw = (
        target_containers[0]
        if len(target_containers) == 1
        else target_containers
    )
    counters[status] += 1
    return (
        {
            "status": status,
            "is_equal": "" if parse_errors else target_ids == expected_ids,
            "lsw_gvlan_business_raw": raw_json(target_raw),
            "target_vlan_ids": sorted_vlan_text(target_ids),
            "allow_through_vlan_ids": sorted_vlan_text(allow_ids),
            "lsw_interfaces_vlan_ids": sorted_vlan_text(interface_vlan_ids),
            "source_union_vlan_ids": sorted_vlan_text(expected_ids),
            "extra_target_vlan_ids": sorted_vlan_text(extra_target_ids),
            "missing_target_vlan_ids": sorted_vlan_text(missing_target_ids),
            "allow_through_vlan_value_count": len(allow_values),
            "lsw_interfaces_vlan_value_count": len(interface_vlan_values),
            "parse_errors": json.dumps(parse_errors, ensure_ascii=False),
        },
        counters,
    )


def analyze_graph(
    graph: dict[str, Any],
    split: str,
    source_file: str,
    config_fields: list[str],
    max_range_size: int,
) -> tuple[list[dict[str, Any]], Counter[str]]:
    rows: list[dict[str, Any]] = []
    counters: Counter[str] = Counter()
    nodes = graph.get("nodes")
    if not isinstance(nodes, list):
        counters["files-with-nodes-not-list"] += 1
        return rows, counters

    counters["nodes"] += len(nodes)
    for node_index, node in enumerate(nodes):
        if not isinstance(node, dict):
            counters["invalid-node-items"] += 1
            continue
        analysis, node_counters = analyze_node(
            node,
            config_fields,
            max_range_size,
        )
        counters.update(node_counters)
        if analysis is None:
            continue
        counters["nodes-with-lsw-gvlan-business"] += 1
        node_id_value = node.get("id")
        analysis.update(
            {
                "split": split,
                "source_file": source_file,
                "node_index": node_index,
                "node_id": (
                    str(node_id_value)
                    if node_id_value is not None
                    else f"<index:{node_index}>"
                ),
            }
        )
        rows.append(analysis)
    return rows, counters


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


def split_summary(
    input_files: int,
    invalid_files: int,
    counters: Counter[str],
) -> dict[str, Any]:
    compared = counters["matched"] + counters["mismatched"]
    return {
        "input_files": input_files,
        "valid_files": counters["valid-files"],
        "invalid_files": invalid_files,
        "nodes": counters["nodes"],
        "nodes_with_lsw_gvlan_business": counters[
            "nodes-with-lsw-gvlan-business"
        ],
        "nodes_without_lsw_gvlan_business": counters[
            "nodes-without-lsw-gvlan-business"
        ],
        "nodes_skipped_allow_through_vlan_all": counters[
            "nodes-skipped-allow-through-vlan-all"
        ],
        "compared_nodes": compared,
        "matched_nodes": counters["matched"],
        "mismatched_nodes": counters["mismatched"],
        "parse_error_nodes": counters["parse-error"],
        "match_ratio": round(
            counters["matched"] / compared if compared else 0.0,
            8,
        ),
        "lsw_interfaces_business_objects": counters[
            "lsw-interfaces-business-objects"
        ],
        "invalid_node_items": counters["invalid-node-items"],
        "files_with_nodes_not_list": counters["files-with-nodes-not-list"],
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    dataset_root = args.dataset_root.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    splits = ["train", "val"] if args.split == "all" else [args.split]
    all_rows: list[dict[str, Any]] = []
    total_counters: Counter[str] = Counter()
    errors: list[dict[str, str]] = []
    by_split: dict[str, dict[str, Any]] = {}

    for split in splits:
        files = iter_json_files(dataset_root, split)
        counters: Counter[str] = Counter()
        split_error_count = 0
        started_at = time.time()
        print(f"[{split}] 开始分析：{len(files)} 个 JSON", flush=True)

        for index, path in enumerate(files, start=1):
            source_file = str(path.relative_to(dataset_root / split))
            try:
                graph = load_json_object(path)
                rows, graph_counters = analyze_graph(
                    graph,
                    split,
                    source_file,
                    args.config_fields,
                    args.max_range_size,
                )
                all_rows.extend(rows)
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
                compared = counters["matched"] + counters["mismatched"]
                print(
                    f"[{split}] {index}/{len(files)}，有效比较 {compared}，"
                    f"匹配 {counters['matched']}，不匹配 {counters['mismatched']}，"
                    f"预计剩余 {eta:.1f} 秒",
                    flush=True,
                )

        by_split[split] = split_summary(
            len(files),
            split_error_count,
            counters,
        )
        total_counters.update(counters)

    total = split_summary(
        sum(item["input_files"] for item in by_split.values()),
        len(errors),
        total_counters,
    )
    summary = {
        "dataset_root": str(dataset_root),
        "output_dir": str(output_dir),
        "splits": splits,
        "config_fields": args.config_fields,
        "comparison_rule": (
            "union(recursive vlan fields in lsw-gvlan-business) == "
            "union(lsw-interface[].allow-through-vlan, "
            "lsw-interfaces[].vlan-id) per node"
        ),
        "allow_through_vlan_all_rule": (
            "skip the node when any allow-through-vlan contains all"
        ),
        "empty_lsw_gvlan_business_rule": "{} or [] represents an empty VLAN set",
        "missing_source_field_rule": "missing source fields represent empty sets",
        "max_range_size": args.max_range_size,
        **total,
        "by_split": by_split,
    }

    write_csv(
        output_dir / DETAIL_FILE,
        [
            "split",
            "source_file",
            "node_index",
            "node_id",
            "status",
            "is_equal",
            "lsw_gvlan_business_raw",
            "target_vlan_ids",
            "allow_through_vlan_ids",
            "lsw_interfaces_vlan_ids",
            "source_union_vlan_ids",
            "extra_target_vlan_ids",
            "missing_target_vlan_ids",
            "allow_through_vlan_value_count",
            "lsw_interfaces_vlan_value_count",
            "parse_errors",
        ],
        all_rows,
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
