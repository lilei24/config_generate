#!/usr/bin/env python3
"""评估指定节点故障后到目标节点的路径受到影响的 AP 集合。"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from task_evaluation_common import (
    add_evaluation_arguments,
    run_evaluation,
    validate_evaluation_arguments,
)


DEFAULT_RESULT_PATH = Path("vllm-results/node_failure_ap_impact")
DEFAULT_OUTPUT_DIR = Path("vllm-results/node_failure_ap_impact-evaluation")

METRIC_NAMES = (
    "impacted_ap_precision",
    "impacted_ap_recall",
    "impacted_ap_f1",
)
DETAIL_NAMES = (
    "predicted_ap_count",
    "gold_ap_count",
    "true_positive",
    "false_positive",
    "false_negative",
)


def normalize_ap_ids(value: Any) -> tuple[set[str], int, int]:
    if not isinstance(value, list):
        return set(), 0, 0
    ap_ids: set[str] = set()
    malformed = 0
    for item in value:
        if isinstance(item, str) and item:
            ap_ids.add(item)
        else:
            malformed += 1
    return ap_ids, len(value), malformed


def evaluate_document(
    document: dict[str, Any],
) -> tuple[dict[str, float], dict[str, int]]:
    metrics = {name: 0.0 for name in METRIC_NAMES}
    details = {name: 0 for name in DETAIL_NAMES}
    answer = document.get("task_answer")
    prediction = document.get("model-output")
    if not isinstance(answer, dict) or not isinstance(prediction, dict):
        return metrics, details

    gold_ids, _, _ = normalize_ap_ids(answer.get("impacted_ap_ids"))
    predicted_ids, predicted_count, malformed = normalize_ap_ids(
        prediction.get("impacted_ap_ids")
    )
    true_positive = len(predicted_ids & gold_ids)
    false_positive = len(predicted_ids - gold_ids) + malformed
    false_negative = len(gold_ids - predicted_ids)
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
        impacted_ap_precision=precision,
        impacted_ap_recall=recall,
        impacted_ap_f1=f1,
    )
    details.update(
        predicted_ap_count=predicted_count,
        gold_ap_count=len(gold_ids),
        true_positive=true_positive,
        false_positive=false_positive,
        false_negative=false_negative,
    )
    return metrics, details


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    add_evaluation_arguments(
        parser,
        default_result_path=DEFAULT_RESULT_PATH,
        default_output_dir=DEFAULT_OUTPUT_DIR,
        default_project="topology-node-failure-ap-impact",
        default_experiment="node-failure-ap-impact-evaluation",
    )
    args = parser.parse_args()
    validate_evaluation_arguments(parser, args)
    return args


def main() -> None:
    run_evaluation(
        parse_args(),
        task_name="node_failure_ap_impact",
        metric_names=METRIC_NAMES,
        detail_names=DETAIL_NAMES,
        evaluate_document=evaluate_document,
    )


if __name__ == "__main__":
    main()
