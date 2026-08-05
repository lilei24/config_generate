#!/usr/bin/env python3
"""评估单链路故障后的连通性和全部最短绕行路径。"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from task_evaluation_common import (
    add_evaluation_arguments,
    normalize_path_set,
    run_evaluation,
    validate_evaluation_arguments,
)


DEFAULT_RESULT_PATH = Path("vllm-results/link_failure_reroute")
DEFAULT_OUTPUT_DIR = Path("vllm-results/link_failure_reroute-evaluation")

METRIC_NAMES = (
    "connectivity_accuracy",
    "path_length_accuracy",
    "path_precision",
    "path_recall",
    "path_f1",
)
DETAIL_NAMES = (
    "predicted_path_count",
    "gold_path_count",
    "true_positive",
    "false_positive",
    "false_negative",
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

    gold_connected = answer.get("connected")
    predicted_connected = prediction.get("connected")
    valid_connected = isinstance(gold_connected, bool) and isinstance(
        predicted_connected, bool
    )
    connectivity_correct = valid_connected and predicted_connected == gold_connected
    metrics["connectivity_accuracy"] = float(connectivity_correct)

    gold_length = answer.get("path_length")
    predicted_length = prediction.get("path_length")
    if gold_connected is False:
        metrics["path_length_accuracy"] = float(
            connectivity_correct and predicted_length is None
        )
    else:
        metrics["path_length_accuracy"] = float(
            connectivity_correct
            and not isinstance(gold_length, bool)
            and isinstance(gold_length, int)
            and not isinstance(predicted_length, bool)
            and isinstance(predicted_length, int)
            and predicted_length == gold_length
        )

    gold_paths, _, _ = normalize_path_set(answer.get("paths"))
    predicted_paths, predicted_count, malformed = normalize_path_set(
        prediction.get("paths")
    )
    true_positive = len(predicted_paths & gold_paths)
    false_positive = len(predicted_paths - gold_paths) + malformed
    false_negative = len(gold_paths - predicted_paths)

    if gold_connected is False and connectivity_correct:
        # 正确判断失联且没有虚构路径，空路径集合视为完全正确。
        empty_prediction = predicted_count == 0 and not predicted_paths and not malformed
        precision = recall = f1 = float(empty_prediction)
    else:
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
        path_precision=precision,
        path_recall=recall,
        path_f1=f1,
    )
    details.update(
        predicted_path_count=predicted_count,
        gold_path_count=len(gold_paths),
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
        default_project="topology-link-failure-reroute",
        default_experiment="link-failure-reroute-evaluation",
    )
    args = parser.parse_args()
    validate_evaluation_arguments(parser, args)
    return args


def main() -> None:
    run_evaluation(
        parse_args(),
        task_name="link_failure_reroute",
        metric_names=METRIC_NAMES,
        detail_names=DETAIL_NAMES,
        evaluate_document=evaluate_document,
    )


if __name__ == "__main__":
    main()
