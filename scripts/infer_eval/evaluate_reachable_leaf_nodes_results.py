#!/usr/bin/env python3
"""评估可达叶子节点集合推理结果。"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from task_evaluation_common import (
    add_evaluation_arguments,
    run_evaluation,
    validate_evaluation_arguments,
)


DEFAULT_RESULT_PATH = Path("vllm-results/reachable_leaf_nodes")
DEFAULT_OUTPUT_DIR = Path("vllm-results/reachable_leaf_nodes-evaluation")

METRIC_NAMES = (
    "leaf_precision",
    "leaf_recall",
    "leaf_f1",
    "exact_match_rate",
)
DETAIL_NAMES = (
    "predicted_leaf_count",
    "gold_leaf_count",
    "leaf_true_positive",
    "leaf_false_positive",
    "leaf_false_negative",
    "malformed_prediction_count",
)


def normalize_node_ids(value: Any) -> tuple[set[str], int, int]:
    """返回节点集合、原始数量和非法或重复元素数量。"""

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


def evaluate_document(
    document: dict[str, Any],
) -> tuple[dict[str, float], dict[str, int]]:
    metrics = {name: 0.0 for name in METRIC_NAMES}
    details = {name: 0 for name in DETAIL_NAMES}
    answer = document.get("task_answer")
    prediction = document.get("model-output")
    if not isinstance(answer, dict) or not isinstance(prediction, dict):
        return metrics, details

    gold, _, malformed_gold = normalize_node_ids(
        answer.get("reachable_leaf_node_ids")
    )
    predicted, predicted_count, malformed_prediction = normalize_node_ids(
        prediction.get("reachable_leaf_node_ids")
    )
    if malformed_gold:
        return metrics, details

    true_positive = len(gold & predicted)
    false_positive = len(predicted - gold) + malformed_prediction
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

    metrics.update(
        leaf_precision=precision,
        leaf_recall=recall,
        leaf_f1=f1,
        exact_match_rate=float(
            malformed_prediction == 0 and predicted == gold
        ),
    )
    details.update(
        predicted_leaf_count=predicted_count,
        gold_leaf_count=len(gold),
        leaf_true_positive=true_positive,
        leaf_false_positive=false_positive,
        leaf_false_negative=false_negative,
        malformed_prediction_count=malformed_prediction,
    )
    return metrics, details


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    add_evaluation_arguments(
        parser,
        default_result_path=DEFAULT_RESULT_PATH,
        default_output_dir=DEFAULT_OUTPUT_DIR,
        default_project="topology-reachable-leaf-nodes",
        default_experiment="reachable-leaf-nodes-evaluation",
    )
    args = parser.parse_args()
    validate_evaluation_arguments(parser, args)
    return args


def main() -> None:
    run_evaluation(
        parse_args(),
        task_name="reachable_leaf_nodes",
        metric_names=METRIC_NAMES,
        detail_names=DETAIL_NAMES,
        evaluate_document=evaluate_document,
    )


if __name__ == "__main__":
    main()
