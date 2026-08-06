#!/usr/bin/env python3
"""评估节点一阶邻居与全部可达节点集合推理结果。"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from task_evaluation_common import (
    add_evaluation_arguments,
    run_evaluation,
    validate_evaluation_arguments,
)


DEFAULT_RESULT_PATH = Path("vllm-results/node_neighborhood_reachability")
DEFAULT_OUTPUT_DIR = Path(
    "vllm-results/node_neighborhood_reachability-evaluation"
)

METRIC_NAMES = (
    "neighbor_precision",
    "neighbor_recall",
    "neighbor_f1",
    "reachable_precision",
    "reachable_recall",
    "reachable_f1",
    "exact_match_rate",
)
DETAIL_NAMES = (
    "predicted_neighbor_count",
    "gold_neighbor_count",
    "neighbor_true_positive",
    "neighbor_false_positive",
    "neighbor_false_negative",
    "predicted_reachable_count",
    "gold_reachable_count",
    "reachable_true_positive",
    "reachable_false_positive",
    "reachable_false_negative",
)


def normalize_node_ids(value: Any) -> tuple[set[str], int, int]:
    if not isinstance(value, list):
        return set(), 0, 1
    normalized: set[str] = set()
    malformed = 0
    for item in value:
        if not isinstance(item, str) or not item:
            malformed += 1
        elif item in normalized:
            malformed += 1
        else:
            normalized.add(item)
    return normalized, len(value), malformed


def set_metrics(
    gold: set[str],
    predicted: set[str],
    malformed: int,
) -> tuple[float, float, float, int, int, int]:
    true_positive = len(gold & predicted)
    false_positive = len(predicted - gold) + malformed
    false_negative = len(gold - predicted)
    if not gold and not predicted and malformed == 0:
        return 1.0, 1.0, 1.0, 0, 0, 0
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
    return (
        precision,
        recall,
        f1,
        true_positive,
        false_positive,
        false_negative,
    )


def evaluate_document(
    document: dict[str, Any],
) -> tuple[dict[str, float], dict[str, int]]:
    metrics = {name: 0.0 for name in METRIC_NAMES}
    details = {name: 0 for name in DETAIL_NAMES}
    answer = document.get("task_answer")
    prediction = document.get("model-output")
    if not isinstance(answer, dict) or not isinstance(prediction, dict):
        return metrics, details

    gold_neighbors, _, _ = normalize_node_ids(
        answer.get("one_hop_neighbor_node_ids")
    )
    predicted_neighbors, predicted_neighbor_count, malformed_neighbors = (
        normalize_node_ids(prediction.get("one_hop_neighbor_node_ids"))
    )
    neighbor_values = set_metrics(
        gold_neighbors,
        predicted_neighbors,
        malformed_neighbors,
    )

    gold_reachable, _, _ = normalize_node_ids(answer.get("reachable_node_ids"))
    predicted_reachable, predicted_reachable_count, malformed_reachable = (
        normalize_node_ids(prediction.get("reachable_node_ids"))
    )
    reachable_values = set_metrics(
        gold_reachable,
        predicted_reachable,
        malformed_reachable,
    )

    metrics.update(
        neighbor_precision=neighbor_values[0],
        neighbor_recall=neighbor_values[1],
        neighbor_f1=neighbor_values[2],
        reachable_precision=reachable_values[0],
        reachable_recall=reachable_values[1],
        reachable_f1=reachable_values[2],
        exact_match_rate=float(
            malformed_neighbors == 0
            and malformed_reachable == 0
            and predicted_neighbors == gold_neighbors
            and predicted_reachable == gold_reachable
        ),
    )
    details.update(
        predicted_neighbor_count=predicted_neighbor_count,
        gold_neighbor_count=len(gold_neighbors),
        neighbor_true_positive=neighbor_values[3],
        neighbor_false_positive=neighbor_values[4],
        neighbor_false_negative=neighbor_values[5],
        predicted_reachable_count=predicted_reachable_count,
        gold_reachable_count=len(gold_reachable),
        reachable_true_positive=reachable_values[3],
        reachable_false_positive=reachable_values[4],
        reachable_false_negative=reachable_values[5],
    )
    return metrics, details


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    add_evaluation_arguments(
        parser,
        default_result_path=DEFAULT_RESULT_PATH,
        default_output_dir=DEFAULT_OUTPUT_DIR,
        default_project="topology-node-neighborhood-reachability",
        default_experiment="node-neighborhood-reachability-evaluation",
    )
    args = parser.parse_args()
    validate_evaluation_arguments(parser, args)
    return args


def main() -> None:
    run_evaluation(
        parse_args(),
        task_name="node_neighborhood_and_reachability",
        metric_names=METRIC_NAMES,
        detail_names=DETAIL_NAMES,
        evaluate_document=evaluate_document,
    )


if __name__ == "__main__":
    main()
