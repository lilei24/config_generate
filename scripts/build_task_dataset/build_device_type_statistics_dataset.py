#!/usr/bin/env python3
"""构造按物理设备类型统计设备名称的任务数据集。

每张原始拓扑生成一个样本。标准答案使用 nodes[].devices.TYPE（兼容历史字段
nodes[].device.TYPE）动态分组，并收集对应的 NAME；逻辑角色不参与统计。
一次运行同步生成 with_answer 和 without_answer 两套数据集。
"""

from __future__ import annotations

import argparse
import copy
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


DEFAULT_DATASET_ROOT = Path("datasets")
DEFAULT_OUTPUT_ROOT = Path("device_type_statistics_dataset")
DEFAULT_SPLITS = ("train", "val")
DEFAULT_PROGRESS_INTERVAL = 100

WITH_ANSWER_DIR = "with_answer"
WITHOUT_ANSWER_DIR = "without_answer"
STATS_FILE = "device_type_statistics.csv"
SUMMARY_FILE = "build_summary.json"
ISSUES_FILE = "build_issues.jsonl"

TASK_QUESTION = """请按物理设备类型统计该网络拓扑中的所有设备，并列出每种类型对应的设备名称。不要按设备的逻辑角色分类，仅输出拓扑中实际存在的设备类型。
请以 JSON 对象形式输出，例如：
{
  "AP": ["AP_1", "AP_2"],
  "LSW": ["SW_1", "SW_2"],
  "FW": ["FW_1"]
}"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset-root",
        type=Path,
        default=DEFAULT_DATASET_ROOT,
        help="原始数据集根目录，默认: %(default)s",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="任务数据集输出根目录，默认: %(default)s",
    )
    parser.add_argument(
        "--splits",
        nargs="+",
        default=list(DEFAULT_SPLITS),
        help="处理的数据划分，默认: train val",
    )
    parser.add_argument(
        "--progress-interval",
        type=int,
        default=DEFAULT_PROGRESS_INTERVAL,
        help="每处理 N 个文件打印进度，0 表示关闭，默认: %(default)s",
    )
    parser.add_argument("--indent", type=int, default=2)
    args = parser.parse_args()
    if args.progress_interval < 0:
        parser.error("--progress-interval 不能小于 0")
    if args.indent < 0:
        parser.error("--indent 不能小于 0")
    return args


def iter_json_files(dataset_root: Path, split: str) -> list[Path]:
    split_root = dataset_root / split
    if not split_root.is_dir():
        return []
    return sorted(path for path in split_root.rglob("*.json") if path.is_file())


def load_graph(path: Path) -> tuple[dict[str, Any] | None, str]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as error:  # noqa: BLE001 - 坏文件应记录并继续批处理。
        return None, f"{type(error).__name__}: {error}"
    if not isinstance(value, dict):
        return None, f"top-level type is {type(value).__name__}, expected object"
    return value, ""


def nonempty_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def get_complete_device(
    node: dict[str, Any],
) -> tuple[str | None, str | None, str | None, bool]:
    """读取完整设备信息，优先使用原始数据常见的 devices 字段。"""

    objects: list[tuple[str, dict[str, Any]]] = []
    for field_name in ("devices", "device"):
        value = node.get(field_name)
        if isinstance(value, dict):
            objects.append((field_name, value))

    for field_name, device in objects:
        device_type = nonempty_string(device.get("TYPE"))
        device_name = nonempty_string(device.get("NAME"))
        if device_type is not None and device_name is not None:
            return device_type, device_name, field_name, True

    if not objects:
        return None, None, None, False
    field_name, device = objects[0]
    return (
        nonempty_string(device.get("TYPE")),
        nonempty_string(device.get("NAME")),
        field_name,
        True,
    )


def collect_device_statistics(
    graph: dict[str, Any],
) -> tuple[dict[str, list[str]] | None, dict[str, Any], str]:
    """严格收集所有节点的物理类型和名称，避免生成不完整标准答案。"""

    nodes = graph.get("nodes")
    if not isinstance(nodes, list):
        return None, {}, "nodes-not-list"
    if not nodes:
        return None, {"node_count": 0}, "empty-nodes"

    names_by_type: dict[str, list[str]] = defaultdict(list)
    invalid_reasons: Counter[str] = Counter()
    invalid_node_indexes: list[int] = []
    all_names: list[str] = []
    device_field_counts: Counter[str] = Counter()

    for node_index, node in enumerate(nodes):
        if not isinstance(node, dict):
            invalid_reasons["node-not-object"] += 1
            invalid_node_indexes.append(node_index)
            continue
        device_type, device_name, field_name, has_device_object = (
            get_complete_device(node)
        )
        if not has_device_object:
            invalid_reasons["devices-or-device-not-object"] += 1
            invalid_node_indexes.append(node_index)
            continue
        if device_type is None:
            invalid_reasons["missing-or-empty-device-type"] += 1
        if device_name is None:
            invalid_reasons["missing-or-empty-device-name"] += 1
        if device_type is None or device_name is None:
            invalid_node_indexes.append(node_index)
            continue
        if field_name is None:
            raise AssertionError("完整设备信息必须有来源字段")
        device_field_counts[field_name] += 1
        names_by_type[device_type].append(device_name)
        all_names.append(device_name)

    counters: dict[str, Any] = {
        "node_count": len(nodes),
        "valid_device_count": len(all_names),
        "invalid_node_count": len(invalid_node_indexes),
        "invalid_node_indexes": invalid_node_indexes,
        "invalid_reasons": dict(sorted(invalid_reasons.items())),
        "device_field_counts": dict(sorted(device_field_counts.items())),
    }
    if invalid_node_indexes:
        return None, counters, "node-missing-complete-device-type-or-name"
    if not names_by_type:
        return None, counters, "no-valid-device"

    answer = {
        device_type: sorted(device_names)
        for device_type, device_names in sorted(names_by_type.items())
    }
    name_counts = Counter(all_names)
    counters.update(
        {
            "device_type_count": len(answer),
            "device_type_counts": {
                device_type: len(names) for device_type, names in answer.items()
            },
            "duplicate_name_groups": sum(
                1 for count in name_counts.values() if count > 1
            ),
            "duplicate_name_occurrences": sum(
                count for count in name_counts.values() if count > 1
            ),
        }
    )
    return answer, counters, ""


def build_task_graph(
    graph: dict[str, Any],
    answer: dict[str, list[str]],
    split: str,
    source_file: str,
) -> dict[str, Any]:
    task_graph = copy.deepcopy(graph)
    for key in list(task_graph):
        if key.startswith("task_"):
            task_graph.pop(key)
    task_graph["task_question"] = TASK_QUESTION
    task_graph["task_answer"] = answer
    task_graph["task_metadata"] = {
        "task_name": "device_type_statistics",
        "split": split,
        "source_file": source_file,
        "classification_field": "nodes[].devices.TYPE or nodes[].device.TYPE",
        "device_name_field": "nodes[].devices.NAME or nodes[].device.NAME",
        "samples_per_graph": 1,
    }
    return task_graph


def write_json(path: Path, value: Any, indent: int = 2) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=indent) + "\n",
        encoding="utf-8",
    )


def append_issue(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(value, ensure_ascii=False) + "\n")


def remove_stale_outputs(
    output_root: Path,
    split: str,
    relative_path: Path,
) -> None:
    for version in (WITH_ANSWER_DIR, WITHOUT_ANSWER_DIR):
        output_path = output_root / version / split / relative_path
        if output_path.is_file():
            output_path.unlink()


def write_stats(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "split",
        "source_file",
        "output_file",
        "node_count",
        "device_count",
        "device_type_count",
        "device_types",
        "device_type_counts",
        "duplicate_name_groups",
        "duplicate_name_occurrences",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def build_dataset(args: argparse.Namespace) -> dict[str, Any]:
    dataset_root = args.dataset_root.resolve()
    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    issue_path = output_root / ISSUES_FILE
    if issue_path.exists():
        issue_path.unlink()

    stats_rows: list[dict[str, Any]] = []
    summary: dict[str, Any] = {
        "dataset_root": str(dataset_root),
        "output_root": str(output_root),
        "samples_per_graph": 1,
        "classification_field": "nodes[].devices.TYPE or nodes[].device.TYPE",
        "device_name_field": "nodes[].devices.NAME or nodes[].device.NAME",
        "strict_complete_device_fields": True,
        "splits": {},
    }

    for split in args.splits:
        files = iter_json_files(dataset_root, split)
        skip_reasons: Counter[str] = Counter()
        aggregate_type_counts: Counter[str] = Counter()
        split_summary: dict[str, Any] = {
            "input_files": len(files),
            "generated_files": 0,
            "skipped_files": 0,
            "generated_devices": 0,
            "device_type_counts": {},
            "skip_reasons": {},
        }
        print(f"[{split}] found {len(files)} json files", flush=True)

        for file_index, source_path in enumerate(files, start=1):
            relative_path = source_path.relative_to(dataset_root / split)
            remove_stale_outputs(output_root, split, relative_path)
            graph, load_error = load_graph(source_path)
            answer: dict[str, list[str]] | None = None
            counters: dict[str, Any] = {}
            if graph is None:
                reason = "load-json-error"
                detail: Any = load_error
            else:
                answer, counters, reason = collect_device_statistics(graph)
                detail = counters

            if graph is None or answer is None:
                skip_reasons[reason] += 1
                append_issue(
                    issue_path,
                    {
                        "split": split,
                        "source_file": str(relative_path),
                        "issue": reason,
                        "detail": detail,
                    },
                )
            else:
                task_graph = build_task_graph(
                    graph,
                    answer,
                    split,
                    str(relative_path),
                )
                with_path = output_root / WITH_ANSWER_DIR / split / relative_path
                without_path = (
                    output_root / WITHOUT_ANSWER_DIR / split / relative_path
                )
                write_json(with_path, task_graph, args.indent)
                hidden_graph = copy.deepcopy(task_graph)
                hidden_graph.pop("task_answer", None)
                write_json(without_path, hidden_graph, args.indent)

                type_counts = {
                    device_type: len(names)
                    for device_type, names in answer.items()
                }
                aggregate_type_counts.update(type_counts)
                device_count = sum(type_counts.values())
                split_summary["generated_files"] += 1
                split_summary["generated_devices"] += device_count
                stats_rows.append(
                    {
                        "split": split,
                        "source_file": str(relative_path),
                        "output_file": str(with_path.relative_to(output_root)),
                        "node_count": counters["node_count"],
                        "device_count": device_count,
                        "device_type_count": len(answer),
                        "device_types": json.dumps(
                            list(answer), ensure_ascii=False
                        ),
                        "device_type_counts": json.dumps(
                            type_counts, ensure_ascii=False, sort_keys=True
                        ),
                        "duplicate_name_groups": counters[
                            "duplicate_name_groups"
                        ],
                        "duplicate_name_occurrences": counters[
                            "duplicate_name_occurrences"
                        ],
                    }
                )

            if args.progress_interval > 0 and (
                file_index % args.progress_interval == 0
                or file_index == len(files)
            ):
                print(
                    f"[{split}] {file_index}/{len(files)}，"
                    f"已生成 {split_summary['generated_files']}，"
                    f"跳过 {sum(skip_reasons.values())}",
                    flush=True,
                )

        split_summary["skipped_files"] = sum(skip_reasons.values())
        split_summary["device_type_counts"] = dict(
            sorted(aggregate_type_counts.items())
        )
        split_summary["skip_reasons"] = dict(sorted(skip_reasons.items()))
        summary["splits"][split] = split_summary

    write_stats(output_root / STATS_FILE, stats_rows)
    write_json(output_root / SUMMARY_FILE, summary, args.indent)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


if __name__ == "__main__":
    build_dataset(parse_args())
