#!/usr/bin/env python3
"""评价 vLLM 两节点全部最短路径结果，输出逐样本和 Macro 汇总指标。"""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


DEFAULT_RESULT_ROOT = Path("vllm-results/shortest_path")
DEFAULT_OUTPUT_DIR = Path("vllm-results/shortest_path-evaluation")
DEFAULT_SPLIT = "val"
DEFAULT_PROGRESS_INTERVAL = 100

METRIC_NAMES = (
    "path_length_accuracy",
    "path_valid_rate",
    "path_precision",
    "path_recall",
    "path_f1",
    "path_exact_match_rate",
    "role_accuracy",
    "device_name_accuracy",
)


@dataclass
class SampleMetrics:
    path_length_accuracy: float = 0.0
    path_valid_rate: float = 0.0
    path_precision: float = 0.0
    path_recall: float = 0.0
    path_f1: float = 0.0
    path_exact_match_rate: float = 0.0
    role_accuracy: float = 0.0
    device_name_accuracy: float = 0.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--result-root",
        type=Path,
        default=DEFAULT_RESULT_ROOT,
        help="vLLM 推理结果根目录，默认: %(default)s",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="评价结果目录，默认: %(default)s",
    )
    parser.add_argument(
        "--split",
        choices=["train", "val", "all"],
        default=DEFAULT_SPLIT,
        help="评价的数据划分，默认: %(default)s",
    )
    parser.add_argument(
        "--progress-interval",
        type=int,
        default=DEFAULT_PROGRESS_INTERVAL,
        help="每处理 N 个文件打印进度，0 表示关闭，默认: %(default)s",
    )
    args = parser.parse_args()
    if args.progress_interval < 0:
        parser.error("--progress-interval 不能小于 0")
    return args


def load_json_object(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"JSON 顶层必须是对象，实际为 {type(data).__name__}")
    return data


def get_device(node: dict[str, Any]) -> dict[str, Any]:
    device = node.get("device")
    if not isinstance(device, dict):
        device = node.get("devices")
    return device if isinstance(device, dict) else {}


def build_node_metadata(
    document: dict[str, Any],
) -> tuple[set[str], dict[str, str], dict[str, str]]:
    node_ids: set[str] = set()
    role_by_id: dict[str, str] = {}
    name_by_id: dict[str, str] = {}
    nodes = document.get("nodes")
    if not isinstance(nodes, list):
        return node_ids, role_by_id, name_by_id

    for node in nodes:
        if not isinstance(node, dict) or node.get("id") is None:
            continue
        node_id = str(node["id"])
        if node_id in node_ids:
            continue
        node_ids.add(node_id)

        topology_node = node.get("topologyNode")
        role = topology_node.get("DEVICEROLE") if isinstance(topology_node, dict) else None
        role_by_id[node_id] = str(role) if role is not None else ""

        name = get_device(node).get("NAME")
        name_by_id[node_id] = str(name) if name is not None else node_id
    return node_ids, role_by_id, name_by_id


def build_adjacency(
    document: dict[str, Any], node_ids: set[str]
) -> dict[str, set[str]]:
    adjacency = {node_id: set() for node_id in node_ids}
    directed = bool(document.get("directed", False))
    links = document.get("links")
    if not isinstance(links, list):
        return adjacency

    for link in links:
        if not isinstance(link, dict):
            continue
        source = link.get("source")
        target = link.get("target")
        if source is None or target is None:
            continue
        source_id = str(source)
        target_id = str(target)
        if source_id not in node_ids or target_id not in node_ids:
            continue
        adjacency[source_id].add(target_id)
        if not directed:
            adjacency[target_id].add(source_id)
    return adjacency


def normalize_gold_paths(value: Any) -> set[tuple[str, ...]]:
    if not isinstance(value, list):
        return set()
    paths: set[tuple[str, ...]] = set()
    for path in value:
        if (
            isinstance(path, list)
            and path
            and all(isinstance(node_id, str) and node_id for node_id in path)
        ):
            paths.add(tuple(path))
    return paths


def normalize_predicted_paths(
    value: Any,
) -> tuple[list[Any], list[tuple[str, ...]], int]:
    if not isinstance(value, list):
        return [], [], 0
    normalized: list[tuple[str, ...]] = []
    malformed = 0
    for path in value:
        if (
            isinstance(path, list)
            and path
            and all(isinstance(node_id, str) and node_id for node_id in path)
        ):
            normalized.append(tuple(path))
        else:
            malformed += 1
    return value, normalized, malformed


def is_valid_shortest_path(
    path: tuple[str, ...],
    source_id: str | None,
    target_id: str | None,
    shortest_length: int | None,
    node_ids: set[str],
    adjacency: dict[str, set[str]],
) -> bool:
    if not path or source_id is None or target_id is None or shortest_length is None:
        return False
    if path[0] != source_id or path[-1] != target_id:
        return False
    if any(node_id not in node_ids for node_id in path):
        return False
    if len(set(path)) != len(path):
        return False
    if len(path) - 1 != shortest_length:
        return False
    return all(right in adjacency.get(left, set()) for left, right in zip(path, path[1:]))


def annotation_accuracy(
    raw_paths: Any,
    sequences: Any,
    expected_by_id: dict[str, str],
) -> float:
    if not isinstance(raw_paths, list) or not raw_paths:
        return 0.0
    if not isinstance(sequences, list) or len(sequences) != len(raw_paths):
        return 0.0

    total_positions = 0
    correct_positions = 0
    for path, sequence in zip(raw_paths, sequences):
        if not isinstance(path, list) or not isinstance(sequence, list):
            return 0.0
        if not path or len(sequence) != len(path):
            return 0.0
        total_positions += len(path)
        for node_id, predicted_value in zip(path, sequence):
            if (
                isinstance(node_id, str)
                and isinstance(predicted_value, str)
                and node_id in expected_by_id
                and predicted_value == expected_by_id[node_id]
            ):
                correct_positions += 1
    return correct_positions / total_positions if total_positions else 0.0


def evaluate_document(document: dict[str, Any]) -> tuple[SampleMetrics, dict[str, int]]:
    metrics = SampleMetrics()
    answer = document.get("task_answer")
    prediction = document.get("model-output")
    if not isinstance(answer, dict) or not isinstance(prediction, dict):
        return metrics, {
            "predicted_path_count": 0,
            "gold_path_count": 0,
            "true_positive": 0,
            "false_positive": 0,
            "false_negative": 0,
        }

    gold_length = answer.get("path_length")
    if isinstance(gold_length, bool) or not isinstance(gold_length, int):
        gold_length = None
    predicted_length = prediction.get("path_length")
    metrics.path_length_accuracy = float(
        gold_length is not None
        and not isinstance(predicted_length, bool)
        and isinstance(predicted_length, int)
        and predicted_length == gold_length
    )

    gold_paths = normalize_gold_paths(answer.get("paths"))
    raw_paths, normalized_paths, malformed_count = normalize_predicted_paths(
        prediction.get("paths")
    )
    predicted_path_set = set(normalized_paths)
    true_positive = len(predicted_path_set & gold_paths)
    false_positive = len(predicted_path_set - gold_paths) + malformed_count
    false_negative = len(gold_paths - predicted_path_set)

    precision_denominator = true_positive + false_positive
    recall_denominator = true_positive + false_negative
    metrics.path_precision = (
        true_positive / precision_denominator if precision_denominator else 0.0
    )
    metrics.path_recall = (
        true_positive / recall_denominator if recall_denominator else 0.0
    )
    if metrics.path_precision + metrics.path_recall:
        metrics.path_f1 = (
            2
            * metrics.path_precision
            * metrics.path_recall
            / (metrics.path_precision + metrics.path_recall)
        )

    node_ids, role_by_id, name_by_id = build_node_metadata(document)
    adjacency = build_adjacency(document, node_ids)
    source_value = document.get("task_source_node_id")
    target_value = document.get("task_target_node_id")
    source_id = str(source_value) if source_value is not None else None
    target_id = str(target_value) if target_value is not None else None
    valid_count = sum(
        is_valid_shortest_path(
            path,
            source_id,
            target_id,
            gold_length,
            node_ids,
            adjacency,
        )
        for path in normalized_paths
    )
    raw_path_count = len(raw_paths) if isinstance(raw_paths, list) else 0
    metrics.path_valid_rate = valid_count / raw_path_count if raw_path_count else 0.0

    duplicate_free = len(normalized_paths) == len(predicted_path_set)
    all_paths_well_formed = malformed_count == 0 and isinstance(
        prediction.get("paths"), list
    )
    metrics.path_exact_match_rate = float(
        metrics.path_length_accuracy == 1.0
        and all_paths_well_formed
        and duplicate_free
        and bool(gold_paths)
        and predicted_path_set == gold_paths
    )

    metrics.role_accuracy = annotation_accuracy(
        prediction.get("paths"),
        prediction.get("path_role_sequences"),
        role_by_id,
    )
    metrics.device_name_accuracy = annotation_accuracy(
        prediction.get("paths"),
        prediction.get("path_device_names"),
        name_by_id,
    )
    return metrics, {
        "predicted_path_count": raw_path_count,
        "gold_path_count": len(gold_paths),
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
    }


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    result_root = args.result_root.resolve()
    output_dir = args.output_dir.resolve()
    splits = ["train", "val"] if args.split == "all" else [args.split]

    sample_items: list[tuple[str, Path]] = []
    for split in splits:
        split_root = result_root / split
        if not split_root.is_dir():
            raise FileNotFoundError(f"推理结果目录不存在: {split_root}")
        sample_items.extend(
            (split, path)
            for path in sorted(split_root.rglob("*.json"))
            if path.is_file()
        )
    if not sample_items:
        raise FileNotFoundError(f"没有找到推理结果 JSON: {result_root}")

    rows: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    metric_sums = {name: 0.0 for name in METRIC_NAMES}
    successful_model_returns = 0

    for index, (split, path) in enumerate(sample_items, start=1):
        relative_path = str(path.relative_to(result_root / split))
        metrics = SampleMetrics()
        counts = {
            "predicted_path_count": 0,
            "gold_path_count": 0,
            "true_positive": 0,
            "false_positive": 0,
            "false_negative": 0,
        }
        model_returned = False
        error_reason = ""
        try:
            document = load_json_object(path)
            run_info = document.get("vllm-run")
            model_returned = bool(
                isinstance(run_info, dict)
                and run_info.get("success") is True
                and isinstance(document.get("model-output"), dict)
            )
            if model_returned:
                successful_model_returns += 1
            elif isinstance(run_info, dict):
                error_reason = str(run_info.get("error") or "model-output unavailable")
            else:
                error_reason = "missing vllm-run"
            metrics, counts = evaluate_document(document)
        except Exception as error:  # noqa: BLE001 - 坏结果记零并继续。
            error_reason = f"{type(error).__name__}: {error}"

        metric_values = asdict(metrics)
        for name in METRIC_NAMES:
            metric_sums[name] += metric_values[name]
        row = {
            "split": split,
            "source_file": relative_path,
            "model_returned": model_returned,
            "error_reason": error_reason,
            **counts,
            **{name: round(metric_values[name], 8) for name in METRIC_NAMES},
        }
        rows.append(row)
        if error_reason:
            errors.append(
                {"split": split, "source_file": relative_path, "error": error_reason}
            )

        if args.progress_interval > 0 and (
            index % args.progress_interval == 0 or index == len(sample_items)
        ):
            print(f"评价进度 {index}/{len(sample_items)}", flush=True)

    sample_count = len(rows)
    aggregate_metrics = {
        name: round(metric_sums[name] / sample_count, 8) for name in METRIC_NAMES
    }
    summary = {
        "result_root": str(result_root),
        "output_dir": str(output_dir),
        "splits": splits,
        "aggregation": "macro: evaluate each sample, then average",
        "sample_count": sample_count,
        "successful_model_returns": successful_model_returns,
        "failed_model_returns": sample_count - successful_model_returns,
        "metrics": aggregate_metrics,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(
        output_dir / "per_file_metrics.csv",
        [
            "split",
            "source_file",
            "model_returned",
            "error_reason",
            "predicted_path_count",
            "gold_path_count",
            "true_positive",
            "false_positive",
            "false_negative",
            *METRIC_NAMES,
        ],
        rows,
    )
    write_csv(
        output_dir / "evaluation_errors.csv",
        ["split", "source_file", "error"],
        errors,
    )
    (output_dir / "evaluation_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
