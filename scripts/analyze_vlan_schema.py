#!/usr/bin/env python3
"""发现原始拓扑数据中所有 key 名包含 vlan 的 JSON Schema 路径。"""

from __future__ import annotations

import argparse
import csv
import json
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable


DEFAULT_DATASET_ROOT = Path("datasets")
DEFAULT_OUTPUT_DIR = Path("/tmp/vlan_schema_analysis")
DEFAULT_PROGRESS_INTERVAL = 50
DEFAULT_MAX_EXAMPLES = 5
DEFAULT_MAX_EXAMPLE_LENGTH = 300
MISSING_VALUE = "<missing>"
NO_CONFIG_KEY = "<none>"
UNKNOWN_CONFIG_KEY = "<unknown>"

FIELD_PATH_FILE = "vlan_field_path_summary.csv"
VALUE_TYPE_FILE = "vlan_value_type_summary.csv"
TOP_LEVEL_KEY_FILE = "vlan_top_level_key_summary.csv"
SUMMARY_FILE = "vlan_analysis_summary.json"


@dataclass(frozen=True)
class ScanContext:
    split: str
    source_file: str
    scope: str
    node_ref: str | None = None
    device_type: str = MISSING_VALUE
    device_role: str = MISSING_VALUE
    top_level_config_key: str = NO_CONFIG_KEY


@dataclass
class PathStatistics:
    files: set[str] = field(default_factory=set)
    nodes: set[str] = field(default_factory=set)
    occurrence_count: int = 0
    top_level_keys: Counter[str] = field(default_factory=Counter)
    value_types: Counter[str] = field(default_factory=Counter)
    value_type_files: dict[str, set[str]] = field(
        default_factory=lambda: defaultdict(set)
    )
    device_types: Counter[str] = field(default_factory=Counter)
    device_roles: Counter[str] = field(default_factory=Counter)
    examples: list[str] = field(default_factory=list)
    example_set: set[str] = field(default_factory=set)


@dataclass
class TopLevelKeyStatistics:
    files: set[str] = field(default_factory=set)
    nodes: set[str] = field(default_factory=set)
    paths: set[str] = field(default_factory=set)
    occurrence_count: int = 0
    value_types: Counter[str] = field(default_factory=Counter)
    device_types: Counter[str] = field(default_factory=Counter)
    device_roles: Counter[str] = field(default_factory=Counter)


class VlanSchemaAnalyzer:
    def __init__(self, max_examples: int, max_example_length: int) -> None:
        self.max_examples = max_examples
        self.max_example_length = max_example_length
        self.path_stats: dict[tuple[str, str], PathStatistics] = {}
        self.top_key_stats: dict[tuple[str, str], TopLevelKeyStatistics] = {}
        self.total_occurrences = 0
        self.scope_counts: Counter[str] = Counter()
        self.value_type_counts: Counter[str] = Counter()
        self.split_occurrences: Counter[str] = Counter()

    def record(self, path: str, key: str, value: Any, context: ScanContext) -> None:
        if "vlan" not in key.lower():
            return

        value_type = json_value_type(value)
        file_ref = f"{context.split}/{context.source_file}"
        stats = self.path_stats.setdefault(
            (context.scope, path),
            PathStatistics(),
        )
        stats.files.add(file_ref)
        if context.node_ref is not None:
            stats.nodes.add(context.node_ref)
        stats.occurrence_count += 1
        stats.top_level_keys[context.top_level_config_key] += 1
        stats.value_types[value_type] += 1
        stats.value_type_files[value_type].add(file_ref)
        if context.scope == "node":
            stats.device_types[context.device_type] += 1
            stats.device_roles[context.device_role] += 1

        example = compact_example(value, self.max_example_length)
        if example not in stats.example_set and len(stats.examples) < self.max_examples:
            stats.example_set.add(example)
            stats.examples.append(example)

        top_stats = self.top_key_stats.setdefault(
            (context.scope, context.top_level_config_key),
            TopLevelKeyStatistics(),
        )
        top_stats.files.add(file_ref)
        if context.node_ref is not None:
            top_stats.nodes.add(context.node_ref)
        top_stats.paths.add(path)
        top_stats.occurrence_count += 1
        top_stats.value_types[value_type] += 1
        if context.scope == "node":
            top_stats.device_types[context.device_type] += 1
            top_stats.device_roles[context.device_role] += 1

        self.total_occurrences += 1
        self.scope_counts[context.scope] += 1
        self.value_type_counts[value_type] += 1
        self.split_occurrences[context.split] += 1


def json_value_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def compact_example(value: Any, max_length: int) -> str:
    serialized = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if len(serialized) <= max_length:
        return serialized
    return serialized[: max(0, max_length - 3)] + "..."


def scalar_text(value: Any, fallback: str = MISSING_VALUE) -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    return text if text else fallback


def get_device(node: dict[str, Any]) -> dict[str, Any]:
    device = node.get("devices")
    if not isinstance(device, dict):
        device = node.get("device")
    return device if isinstance(device, dict) else {}


def get_device_type(node: dict[str, Any]) -> str:
    return scalar_text(get_device(node).get("TYPE"))


def get_device_role(node: dict[str, Any]) -> str:
    topology_node = node.get("topologyNode")
    if not isinstance(topology_node, dict):
        return MISSING_VALUE
    return scalar_text(topology_node.get("DEVICEROLE"))


def child_path(parent: str, key: str) -> str:
    return f"{parent}.{key}" if parent else key


def walk_value(
    value: Any,
    path: str,
    context: ScanContext,
    analyzer: VlanSchemaAnalyzer,
) -> None:
    if isinstance(value, dict):
        walk_mapping(value, path, context, analyzer)
    elif isinstance(value, list):
        item_path = f"{path}[]"
        for item in value:
            walk_value(item, item_path, context, analyzer)


def walk_mapping(
    mapping: dict[str, Any],
    path: str,
    context: ScanContext,
    analyzer: VlanSchemaAnalyzer,
    excluded_keys: set[str] | None = None,
) -> None:
    excluded = excluded_keys or set()
    for key, value in mapping.items():
        if key in excluded:
            continue
        key_text = str(key)
        current_path = child_path(path, key_text)
        analyzer.record(current_path, key_text, value, context)
        walk_value(value, current_path, context, analyzer)


def scan_config_item(
    item: Any,
    item_path: str,
    context: ScanContext,
    analyzer: VlanSchemaAnalyzer,
) -> None:
    if not isinstance(item, dict):
        walk_value(
            item,
            item_path,
            replace(context, top_level_config_key=UNKNOWN_CONFIG_KEY),
            analyzer,
        )
        return

    for top_key, value in item.items():
        top_key_text = str(top_key)
        top_context = replace(context, top_level_config_key=top_key_text)
        current_path = child_path(item_path, top_key_text)
        analyzer.record(current_path, top_key_text, value, top_context)
        walk_value(value, current_path, top_context, analyzer)


def scan_config_container(
    value: Any,
    path: str,
    context: ScanContext,
    analyzer: VlanSchemaAnalyzer,
) -> None:
    if isinstance(value, list):
        for item in value:
            scan_config_item(item, f"{path}[]", context, analyzer)
    elif isinstance(value, dict):
        scan_config_item(value, path, context, analyzer)
    else:
        walk_value(value, path, context, analyzer)


def scan_node(
    node: Any,
    node_index: int,
    split: str,
    source_file: str,
    analyzer: VlanSchemaAnalyzer,
) -> None:
    if not isinstance(node, dict):
        return
    node_id = scalar_text(node.get("id"), f"<node-index:{node_index}>")
    context = ScanContext(
        split=split,
        source_file=source_file,
        scope="node",
        node_ref=f"{split}/{source_file}#{node_id}",
        device_type=get_device_type(node),
        device_role=get_device_role(node),
    )
    walk_mapping(
        node,
        "nodes[]",
        context,
        analyzer,
        excluded_keys={"config", "configs"},
    )
    for config_field in ("config", "configs"):
        if config_field in node:
            scan_config_container(
                node[config_field],
                f"nodes[].{config_field}",
                context,
                analyzer,
            )


def scan_device_group(
    group: Any,
    split: str,
    source_file: str,
    analyzer: VlanSchemaAnalyzer,
) -> None:
    if not isinstance(group, dict):
        return
    context = ScanContext(split, source_file, "deviceGroup")
    walk_mapping(
        group,
        "deviceGroups[]",
        context,
        analyzer,
        excluded_keys={"config", "configs"},
    )
    for config_field in ("config", "configs"):
        if config_field in group:
            scan_config_container(
                group[config_field],
                f"deviceGroups[].{config_field}",
                context,
                analyzer,
            )


def scan_graph(
    graph: dict[str, Any],
    split: str,
    source_file: str,
    analyzer: VlanSchemaAnalyzer,
) -> None:
    nodes = graph.get("nodes")
    if isinstance(nodes, list):
        for node_index, node in enumerate(nodes):
            scan_node(node, node_index, split, source_file, analyzer)

    groups = graph.get("deviceGroups")
    if isinstance(groups, list):
        for group in groups:
            scan_device_group(group, split, source_file, analyzer)

    links = graph.get("links")
    if isinstance(links, list):
        link_context = ScanContext(split, source_file, "link")
        for link in links:
            walk_value(link, "links[]", link_context, analyzer)

    other_context = ScanContext(split, source_file, "other")
    walk_mapping(
        graph,
        "",
        other_context,
        analyzer,
        excluded_keys={"nodes", "deviceGroups", "links"},
    )


def iter_json_files(dataset_root: Path, split: str) -> list[Path]:
    split_dir = dataset_root / split
    if not split_dir.is_dir():
        return []
    return sorted(path for path in split_dir.rglob("*.json") if path.is_file())


def counter_json(counter: Counter[str]) -> str:
    return json.dumps(
        dict(sorted(counter.items(), key=lambda item: (-item[1], item[0]))),
        ensure_ascii=False,
    )


def list_json(values: Iterable[str]) -> str:
    return json.dumps(list(values), ensure_ascii=False)


def write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_outputs(
    output_dir: Path,
    analyzer: VlanSchemaAnalyzer,
    summary: dict[str, Any],
) -> None:
    field_rows = []
    value_type_rows = []
    for (scope, path), stats in sorted(analyzer.path_stats.items()):
        field_rows.append(
            {
                "scope": scope,
                "normalized_path": path,
                "file_count": len(stats.files),
                "occurrence_count": stats.occurrence_count,
                "involved_node_count": len(stats.nodes),
                "top_level_config_keys": counter_json(stats.top_level_keys),
                "value_types": counter_json(stats.value_types),
                "device_types": counter_json(stats.device_types),
                "device_roles": counter_json(stats.device_roles),
                "example_values": list_json(stats.examples),
            }
        )
        for value_type, count in sorted(stats.value_types.items()):
            value_type_rows.append(
                {
                    "scope": scope,
                    "normalized_path": path,
                    "value_type": value_type,
                    "file_count": len(stats.value_type_files[value_type]),
                    "occurrence_count": count,
                    "ratio_within_path": round(
                        count / stats.occurrence_count,
                        6,
                    ),
                }
            )

    top_key_rows = []
    for (scope, top_key), stats in sorted(analyzer.top_key_stats.items()):
        top_key_rows.append(
            {
                "scope": scope,
                "top_level_config_key": top_key,
                "file_count": len(stats.files),
                "occurrence_count": stats.occurrence_count,
                "unique_path_count": len(stats.paths),
                "involved_node_count": len(stats.nodes),
                "value_types": counter_json(stats.value_types),
                "device_types": counter_json(stats.device_types),
                "device_roles": counter_json(stats.device_roles),
                "normalized_paths": list_json(sorted(stats.paths)),
            }
        )

    write_csv(
        output_dir / FIELD_PATH_FILE,
        [
            "scope",
            "normalized_path",
            "file_count",
            "occurrence_count",
            "involved_node_count",
            "top_level_config_keys",
            "value_types",
            "device_types",
            "device_roles",
            "example_values",
        ],
        field_rows,
    )
    write_csv(
        output_dir / VALUE_TYPE_FILE,
        [
            "scope",
            "normalized_path",
            "value_type",
            "file_count",
            "occurrence_count",
            "ratio_within_path",
        ],
        value_type_rows,
    )
    write_csv(
        output_dir / TOP_LEVEL_KEY_FILE,
        [
            "scope",
            "top_level_config_key",
            "file_count",
            "occurrence_count",
            "unique_path_count",
            "involved_node_count",
            "value_types",
            "device_types",
            "device_roles",
            "normalized_paths",
        ],
        top_key_rows,
    )
    (output_dir / SUMMARY_FILE).write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def run_analysis(args: argparse.Namespace) -> None:
    dataset_root = args.dataset_root.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    splits = ["train", "val"] if args.split == "all" else [args.split]
    analyzer = VlanSchemaAnalyzer(args.max_examples, args.max_example_length)
    errors: list[dict[str, str]] = []
    split_summary: dict[str, dict[str, int]] = {}

    for split in splits:
        files = iter_json_files(dataset_root, split)
        analyzed_files = 0
        started_at = time.time()
        print(f"[{split}] 开始扫描：{len(files)} 个文件", flush=True)
        for index, path in enumerate(files, start=1):
            source_file = str(path.relative_to(dataset_root / split))
            try:
                graph = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(graph, dict):
                    raise ValueError(
                        f"top-level JSON type is {type(graph).__name__}, expected object"
                    )
                scan_graph(graph, split, source_file, analyzer)
                analyzed_files += 1
            except Exception as error:  # noqa: BLE001 - 坏文件需要记录并继续。
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
                elapsed = max(0.001, time.time() - started_at)
                speed = index / elapsed
                eta = (len(files) - index) / speed if speed else 0.0
                print(
                    f"[{split}] {index}/{len(files)}，{speed:.2f} 文件/秒，"
                    f"预计剩余 {eta:.1f} 秒",
                    flush=True,
                )
        split_summary[split] = {
            "input_files": len(files),
            "analyzed_files": analyzed_files,
            "failed_files": len(files) - analyzed_files,
            "vlan_occurrences": analyzer.split_occurrences.get(split, 0),
        }

    summary = {
        "dataset_root": str(dataset_root),
        "output_dir": str(output_dir),
        "splits": splits,
        "match_rule": "case-insensitive key substring contains 'vlan'",
        "array_path_normalization": "every list index is represented as []",
        "scope_definition": {
            "node": "all fields under nodes[], including config/configs",
            "deviceGroup": "all fields under deviceGroups[], including config/configs",
            "link": "all fields under links[]",
            "other": "all other top-level structures",
        },
        "input_files": sum(item["input_files"] for item in split_summary.values()),
        "analyzed_files": sum(
            item["analyzed_files"] for item in split_summary.values()
        ),
        "failed_files": len(errors),
        "vlan_occurrence_count": analyzer.total_occurrences,
        "unique_scope_path_count": len(analyzer.path_stats),
        "unique_top_level_key_count": len(analyzer.top_key_stats),
        "occurrences_by_scope": dict(sorted(analyzer.scope_counts.items())),
        "occurrences_by_value_type": dict(
            sorted(analyzer.value_type_counts.items())
        ),
        "by_split": split_summary,
        "errors": errors,
    }
    write_outputs(output_dir, analyzer, summary)
    print(
        f"完成：{summary['analyzed_files']} 个文件，"
        f"{summary['vlan_occurrence_count']} 次 VLAN key 出现，"
        f"{summary['unique_scope_path_count']} 条标准化路径"
    )
    print(f"结果目录：{output_dir}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "dataset_root",
        nargs="?",
        type=Path,
        default=DEFAULT_DATASET_ROOT,
        help=f"原始数据集根目录，默认: {DEFAULT_DATASET_ROOT}",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"统计结果目录，默认: {DEFAULT_OUTPUT_DIR}",
    )
    parser.add_argument(
        "--split",
        choices=["train", "val", "all"],
        default="all",
        help="扫描 train、val 或全部数据，默认: all",
    )
    parser.add_argument(
        "--progress-interval",
        type=int,
        default=DEFAULT_PROGRESS_INTERVAL,
        help="每处理 N 个文件打印一次进度，0 表示关闭，默认: %(default)s",
    )
    parser.add_argument(
        "--max-examples",
        type=int,
        default=DEFAULT_MAX_EXAMPLES,
        help="每条路径最多保留的不同示例值数量，默认: %(default)s",
    )
    parser.add_argument(
        "--max-example-length",
        type=int,
        default=DEFAULT_MAX_EXAMPLE_LENGTH,
        help="单个示例值的最大字符数，默认: %(default)s",
    )
    args = parser.parse_args()
    if args.progress_interval < 0:
        parser.error("--progress-interval 不能小于 0")
    if args.max_examples < 0:
        parser.error("--max-examples 不能小于 0")
    if args.max_example_length < 3:
        parser.error("--max-example-length 不能小于 3")
    return args


if __name__ == "__main__":
    run_analysis(parse_args())
