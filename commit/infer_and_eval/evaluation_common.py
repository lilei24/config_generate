#!/usr/bin/env python3
"""七类任务的公共指标计算、结果扫描和 SwanLab 记录逻辑。"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from task_specs import TaskSpec


@dataclass(frozen=True)
class EvaluationResult:
    metrics: dict[str, float]
    details: dict[str, int]


def load_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("JSON 顶层必须是对象")
    return value


def metric_names(spec: TaskSpec) -> tuple[str, ...]:
    if spec.answer_kind == "extended_path":
        return (
            "path_length_accuracy",
            "path_valid_rate",
            "path_precision",
            "path_recall",
            "path_f1",
            "path_exact_match_rate",
            "role_accuracy",
            "device_name_accuracy",
        )
    if spec.answer_kind == "path":
        return (
            "path_length_accuracy",
            "path_precision",
            "path_recall",
            "path_f1",
        )
    if spec.answer_field == "impacted_ap_ids":
        return (
            "impacted_ap_precision",
            "impacted_ap_recall",
            "impacted_ap_f1",
        )
    return (
        "terminal_precision",
        "terminal_recall",
        "terminal_f1",
        "terminal_exact_match_rate",
    )


def normalize_paths(value: Any) -> tuple[set[tuple[str, ...]], int, int]:
    if not isinstance(value, list):
        return set(), 0, 1
    normalized: set[tuple[str, ...]] = set()
    malformed = 0
    for path in value:
        if (
            isinstance(path, list)
            and path
            and all(isinstance(node_id, str) and node_id for node_id in path)
        ):
            item = tuple(path)
            if item in normalized:
                malformed += 1
            normalized.add(item)
        else:
            malformed += 1
    return normalized, len(value), malformed


def prf(
    predicted: set[Any],
    gold: set[Any],
    malformed: int = 0,
) -> tuple[float, float, float, int, int, int]:
    true_positive = len(predicted & gold)
    false_positive = len(predicted - gold) + malformed
    false_negative = len(gold - predicted)
    precision_denominator = true_positive + false_positive
    recall_denominator = true_positive + false_negative
    precision = (
        true_positive / precision_denominator if precision_denominator else 0.0
    )
    recall = true_positive / recall_denominator if recall_denominator else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0
    )
    return precision, recall, f1, true_positive, false_positive, false_negative


def build_graph(document: dict[str, Any]) -> tuple[set[str], dict[str, set[str]]]:
    nodes = document.get("nodes")
    node_ids = (
        {
            str(node["id"])
            for node in nodes
            if isinstance(node, dict) and node.get("id") is not None
        }
        if isinstance(nodes, list)
        else set()
    )
    adjacency = {node_id: set() for node_id in node_ids}
    links = document.get("links")
    if not isinstance(links, list):
        return node_ids, adjacency
    directed = bool(document.get("directed", False))
    for link in links:
        if not isinstance(link, dict):
            continue
        source = str(link.get("source"))
        target = str(link.get("target"))
        if source not in node_ids or target not in node_ids:
            continue
        adjacency[source].add(target)
        if not directed:
            adjacency[target].add(source)
    return node_ids, adjacency


def path_is_valid(
    path: tuple[str, ...],
    document: dict[str, Any],
    expected_length: int,
) -> bool:
    node_ids, adjacency = build_graph(document)
    source = document.get("task_source_node_id")
    target = document.get("task_target_node_id")
    if source is None:
        source = document.get("task_source_ap_node_id")
    if target is None:
        target = document.get("task_target_ap_node_id")
    return bool(
        len(path) == expected_length + 1
        and (source is None or path[0] == str(source))
        and (target is None or path[-1] == str(target))
        and all(node_id in node_ids for node_id in path)
        and all(right in adjacency.get(left, set()) for left, right in zip(path, path[1:]))
    )


def aligned_sequence_accuracy(
    gold: dict[str, Any],
    prediction: dict[str, Any],
    field_name: str,
) -> float:
    gold_paths = gold.get("paths")
    predicted_paths = prediction.get("paths")
    gold_sequences = gold.get(field_name)
    predicted_sequences = prediction.get(field_name)
    if not all(
        isinstance(value, list)
        for value in (gold_paths, predicted_paths, gold_sequences, predicted_sequences)
    ):
        return 0.0
    gold_map = {
        tuple(path): sequence
        for path, sequence in zip(gold_paths, gold_sequences)
        if isinstance(path, list) and isinstance(sequence, list)
    }
    correct = total = 0
    for path, predicted_sequence in zip(predicted_paths, predicted_sequences):
        if not isinstance(path, list) or not isinstance(predicted_sequence, list):
            total += 1
            continue
        expected = gold_map.get(tuple(path))
        total += max(len(path), len(predicted_sequence), 1)
        if not isinstance(expected, list):
            continue
        correct += sum(
            predicted_value == expected_value
            for predicted_value, expected_value in zip(predicted_sequence, expected)
        )
    return correct / total if total else 0.0


def evaluate_path(document: dict[str, Any], extended: bool) -> EvaluationResult:
    gold = document.get("task_answer")
    prediction = document.get("model-output")
    if not isinstance(gold, dict) or not isinstance(prediction, dict):
        raise ValueError("缺少 task_answer 或有效 model-output")
    gold_length = gold.get("path_length")
    predicted_length = prediction.get("path_length")
    length_correct = float(
        isinstance(gold_length, int)
        and not isinstance(gold_length, bool)
        and isinstance(predicted_length, int)
        and not isinstance(predicted_length, bool)
        and predicted_length == gold_length
    )
    gold_paths, _, _ = normalize_paths(gold.get("paths"))
    predicted_paths, predicted_count, malformed = normalize_paths(
        prediction.get("paths")
    )
    precision, recall, f1, tp, fp, fn = prf(
        predicted_paths,
        gold_paths,
        malformed,
    )
    metrics = {
        "path_length_accuracy": length_correct,
        "path_precision": precision,
        "path_recall": recall,
        "path_f1": f1,
    }
    if extended:
        valid_count = (
            sum(
                path_is_valid(path, document, int(gold_length))
                for path in predicted_paths
            )
            if isinstance(gold_length, int) and not isinstance(gold_length, bool)
            else 0
        )
        metrics.update(
            path_valid_rate=(
                valid_count / predicted_count if predicted_count else 0.0
            ),
            path_exact_match_rate=float(
                malformed == 0
                and predicted_paths == gold_paths
                and bool(length_correct)
            ),
            role_accuracy=aligned_sequence_accuracy(
                gold, prediction, "path_role_sequences"
            ),
            device_name_accuracy=aligned_sequence_accuracy(
                gold, prediction, "path_device_names"
            ),
        )
    details = {
        "predicted_count": predicted_count,
        "gold_count": len(gold_paths),
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "malformed_count": malformed,
    }
    return EvaluationResult(metrics, details)


def normalize_ids(value: Any) -> tuple[set[str], int, int]:
    if not isinstance(value, list):
        return set(), 0, 1
    normalized: set[str] = set()
    malformed = 0
    for item in value:
        if not isinstance(item, str) or not item or item in normalized:
            malformed += 1
        else:
            normalized.add(item)
    return normalized, len(value), malformed


def evaluate_node_set(document: dict[str, Any], spec: TaskSpec) -> EvaluationResult:
    gold = document.get("task_answer")
    prediction = document.get("model-output")
    if not isinstance(gold, dict) or not isinstance(prediction, dict):
        raise ValueError("缺少 task_answer 或有效 model-output")
    field = spec.answer_field
    if not field:
        raise ValueError("任务未配置集合答案字段")
    gold_ids, _, malformed_gold = normalize_ids(gold.get(field))
    predicted_ids, predicted_count, malformed = normalize_ids(prediction.get(field))
    if malformed_gold:
        raise ValueError(f"task_answer.{field} 结构不合法")
    precision, recall, f1, tp, fp, fn = prf(predicted_ids, gold_ids, malformed)
    if field == "impacted_ap_ids":
        metrics = {
            "impacted_ap_precision": precision,
            "impacted_ap_recall": recall,
            "impacted_ap_f1": f1,
        }
    else:
        metrics = {
            "terminal_precision": precision,
            "terminal_recall": recall,
            "terminal_f1": f1,
            "terminal_exact_match_rate": float(
                malformed == 0 and predicted_ids == gold_ids
            ),
        }
    details = {
        "predicted_count": predicted_count,
        "gold_count": len(gold_ids),
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "malformed_count": malformed,
    }
    return EvaluationResult(metrics, details)


def evaluate_document(document: dict[str, Any], spec: TaskSpec) -> EvaluationResult:
    if spec.answer_kind == "extended_path":
        return evaluate_path(document, extended=True)
    if spec.answer_kind == "path":
        return evaluate_path(document, extended=False)
    return evaluate_node_set(document, spec)


def collect_result_files(result_root: Path, split: str) -> list[tuple[str, Path, str]]:
    if result_root.is_file():
        return [("single", result_root, result_root.name)]
    selected_splits = ("train", "val") if split == "all" else (split,)
    items: list[tuple[str, Path, str]] = []
    for split_name in selected_splits:
        split_root = result_root / split_name
        if not split_root.is_dir():
            raise FileNotFoundError(f"结果目录不存在: {split_root}")
        items.extend(
            (split_name, path, str(path.relative_to(split_root)))
            for path in sorted(split_root.rglob("*.json"))
            if path.is_file()
        )
    return items


def inference_success(document: dict[str, Any]) -> tuple[bool, str]:
    metadata = document.get("inference_metadata")
    if not isinstance(metadata, dict):
        metadata = document.get("vllm-run")
    if not isinstance(metadata, dict):
        return False, "missing inference metadata"
    if metadata.get("success") is not True:
        return False, str(metadata.get("error") or "inference failed")
    if not isinstance(document.get("model-output"), dict):
        return False, "model-output is not an object"
    return True, ""


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
