#!/usr/bin/env python3
"""统计拓扑数据集中所有节点的物理设备 MODEL 分布。"""

from __future__ import annotations

import argparse
import csv
import json
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


DEFAULT_DATASET_ROOT = Path("datasets")
DEFAULT_OUTPUT_DIR = Path("/tmp/device_model_analysis")
DEFAULT_SPLIT = "all"
DEFAULT_PROGRESS_INTERVAL = 100

MODEL_COUNTS_FILE = "device_model_counts.csv"
LEGACY_MODEL_COUNTS_FILE = "device_model_counts.json"
SUMMARY_FILE = "device_model_summary.json"
ERROR_FILE = "analysis_errors.csv"
MISSING_DEVICE_TYPE = "<missing>"


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
        help="统计 train、val 或全部数据，默认: %(default)s",
    )
    parser.add_argument(
        "--progress-interval",
        type=int,
        default=DEFAULT_PROGRESS_INTERVAL,
        help="每处理 N 个文件打印一次进度，0 表示关闭，默认: %(default)s",
    )
    args = parser.parse_args()
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


def device_object(node: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    """优先读取 devices，并兼容历史字段 device。"""

    devices = node.get("devices")
    if isinstance(devices, dict):
        return devices, "devices"
    device = node.get("device")
    if isinstance(device, dict):
        return device, "device"
    return None, ""


def normalized_model(value: Any) -> str | None:
    if value is None or isinstance(value, (dict, list)):
        return None
    text = str(value).strip()
    return text or None


def normalized_device_type(value: Any) -> str:
    if value is None or isinstance(value, (dict, list)):
        return MISSING_DEVICE_TYPE
    text = str(value).strip()
    return text or MISSING_DEVICE_TYPE


def analyze_graph(
    graph: dict[str, Any],
) -> tuple[
    Counter[str],
    dict[str, Counter[str]],
    Counter[str],
    Counter[str],
]:
    """返回型号数量、型号对应类型分布、节点状态和设备字段来源。"""

    models: Counter[str] = Counter()
    model_type_counts: dict[str, Counter[str]] = defaultdict(Counter)
    node_states: Counter[str] = Counter()
    device_fields: Counter[str] = Counter()
    nodes = graph.get("nodes")
    if not isinstance(nodes, list):
        node_states["nodes-not-list"] += 1
        return models, model_type_counts, node_states, device_fields

    for node in nodes:
        node_states["total-nodes"] += 1
        if not isinstance(node, dict):
            node_states["node-not-object"] += 1
            continue
        device, field_name = device_object(node)
        if device is None:
            node_states["missing-device-object"] += 1
            continue
        device_fields[field_name] += 1
        model = normalized_model(device.get("MODEL"))
        if model is None:
            node_states["missing-or-empty-model"] += 1
            continue
        device_type = normalized_device_type(device.get("TYPE"))
        models[model] += 1
        model_type_counts[model][device_type] += 1
        node_states["valid-model-nodes"] += 1
    return models, model_type_counts, node_states, device_fields


def ordered_counts(counter: Counter[str]) -> dict[str, int]:
    return dict(sorted(counter.items(), key=lambda item: (-item[1], item[0])))


def write_errors(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["split", "source_file", "error"])
        writer.writeheader()
        writer.writerows(rows)


def update_model_type_counts(
    target: dict[str, Counter[str]],
    source: dict[str, Counter[str]],
) -> None:
    for model, type_counts in source.items():
        target[model].update(type_counts)


def write_model_counts(
    path: Path,
    model_counts: Counter[str],
    model_type_counts: dict[str, Counter[str]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for model, count in sorted(
        model_counts.items(), key=lambda item: (-item[1], item[0])
    ):
        type_counts = ordered_counts(model_type_counts.get(model, Counter()))
        if sum(type_counts.values()) != count:
            raise AssertionError(f"MODEL={model!r} 的 TYPE 分布数量与总数不一致")
        rows.append(
            {
                "model": model,
                "count": count,
                "device_type_counts": json.dumps(
                    type_counts,
                    ensure_ascii=False,
                ),
            }
        )
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=["model", "count", "device_type_counts"],
        )
        writer.writeheader()
        writer.writerows(rows)


def run(args: argparse.Namespace) -> None:
    dataset_root = args.dataset_root.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    splits = ["train", "val"] if args.split == "all" else [args.split]

    model_counts: Counter[str] = Counter()
    model_type_counts: dict[str, Counter[str]] = defaultdict(Counter)
    node_states: Counter[str] = Counter()
    device_field_counts: Counter[str] = Counter()
    errors: list[dict[str, str]] = []
    by_split: dict[str, dict[str, Any]] = {}

    for split in splits:
        files = iter_json_files(dataset_root, split)
        split_models: Counter[str] = Counter()
        split_model_types: dict[str, Counter[str]] = defaultdict(Counter)
        split_states: Counter[str] = Counter()
        split_device_fields: Counter[str] = Counter()
        split_error_count = 0
        started_at = time.time()
        print(f"[{split}] 开始统计：{len(files)} 个 JSON", flush=True)

        for index, path in enumerate(files, start=1):
            source_file = str(path.relative_to(dataset_root / split))
            try:
                graph = load_json_object(path)
                (
                    graph_models,
                    graph_model_types,
                    graph_states,
                    graph_device_fields,
                ) = analyze_graph(graph)
                split_models.update(graph_models)
                update_model_type_counts(split_model_types, graph_model_types)
                split_states.update(graph_states)
                split_device_fields.update(graph_device_fields)
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
                    f"有效型号节点 {sum(split_models.values())}，"
                    f"错误 {split_error_count}，预计剩余 {eta:.1f} 秒",
                    flush=True,
                )

        model_counts.update(split_models)
        update_model_type_counts(model_type_counts, split_model_types)
        node_states.update(split_states)
        device_field_counts.update(split_device_fields)
        by_split[split] = {
            "input_files": len(files),
            "invalid_files": split_error_count,
            "total_nodes": split_states["total-nodes"],
            "valid_model_nodes": split_states["valid-model-nodes"],
            "missing_or_empty_model_nodes": split_states[
                "missing-or-empty-model"
            ],
            "unique_models": len(split_models),
            "device_field_counts": ordered_counts(split_device_fields),
        }

    summary = {
        "dataset_root": str(dataset_root),
        "output_dir": str(output_dir),
        "splits": splits,
        "model_field": "nodes[].devices.MODEL or nodes[].device.MODEL",
        "input_files": sum(item["input_files"] for item in by_split.values()),
        "invalid_files": len(errors),
        "total_nodes": node_states["total-nodes"],
        "valid_model_nodes": node_states["valid-model-nodes"],
        "missing_or_empty_model_nodes": node_states["missing-or-empty-model"],
        "missing_device_object_nodes": node_states["missing-device-object"],
        "invalid_node_items": node_states["node-not-object"],
        "files_with_nodes_not_list": node_states["nodes-not-list"],
        "unique_models": len(model_counts),
        "device_field_counts": ordered_counts(device_field_counts),
        "by_split": by_split,
    }

    legacy_counts_path = output_dir / LEGACY_MODEL_COUNTS_FILE
    if legacy_counts_path.is_file():
        legacy_counts_path.unlink()
    write_model_counts(
        output_dir / MODEL_COUNTS_FILE,
        model_counts,
        model_type_counts,
    )
    (output_dir / SUMMARY_FILE).write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_errors(output_dir / ERROR_FILE, errors)

    print(
        f"完成：统计 {summary['valid_model_nodes']} 个有效型号节点，"
        f"共 {summary['unique_models']} 种 MODEL，错误文件 {len(errors)} 个",
        flush=True,
    )
    print(f"型号统计：{output_dir / MODEL_COUNTS_FILE}", flush=True)


if __name__ == "__main__":
    run(parse_args())
