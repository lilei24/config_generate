#!/usr/bin/env python3
"""评估链路 LEFTPORT、RIGHTPORT 预测结果。"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from task_evaluation_common import (
    add_evaluation_arguments,
    run_evaluation,
    validate_evaluation_arguments,
)


DEFAULT_RESULT_PATH = Path("vllm-results/link_port_prediction")
DEFAULT_OUTPUT_DIR = Path("vllm-results/link_port_prediction-evaluation")

METRIC_NAMES = (
    "leftport_accuracy",
    "rightport_accuracy",
    "port_pair_exact_match",
)
DETAIL_NAMES = (
    "leftport_correct",
    "rightport_correct",
    "port_pair_correct",
)


def valid_port(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return value


def evaluate_document(
    document: dict[str, Any],
) -> tuple[dict[str, float], dict[str, int]]:
    metrics = {name: 0.0 for name in METRIC_NAMES}
    details = {name: 0 for name in DETAIL_NAMES}
    answer = document.get("task_answer")
    prediction = document.get("model-output")
    if not isinstance(answer, dict) or not isinstance(prediction, dict):
        return metrics, details

    gold_left = valid_port(answer.get("LEFTPORT"))
    gold_right = valid_port(answer.get("RIGHTPORT"))
    predicted_left = valid_port(prediction.get("LEFTPORT"))
    predicted_right = valid_port(prediction.get("RIGHTPORT"))
    left_correct = int(
        gold_left is not None
        and predicted_left is not None
        and predicted_left == gold_left
    )
    right_correct = int(
        gold_right is not None
        and predicted_right is not None
        and predicted_right == gold_right
    )
    pair_correct = int(left_correct == 1 and right_correct == 1)
    metrics.update(
        leftport_accuracy=float(left_correct),
        rightport_accuracy=float(right_correct),
        port_pair_exact_match=float(pair_correct),
    )
    details.update(
        leftport_correct=left_correct,
        rightport_correct=right_correct,
        port_pair_correct=pair_correct,
    )
    return metrics, details


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    add_evaluation_arguments(
        parser,
        default_result_path=DEFAULT_RESULT_PATH,
        default_output_dir=DEFAULT_OUTPUT_DIR,
        default_project="topology-link-port-prediction",
        default_experiment="link-port-prediction-evaluation",
    )
    args = parser.parse_args()
    validate_evaluation_arguments(parser, args)
    return args


def main() -> None:
    run_evaluation(
        parse_args(),
        task_name="link_port_prediction",
        metric_names=METRIC_NAMES,
        detail_names=DETAIL_NAMES,
        evaluate_document=evaluate_document,
    )


if __name__ == "__main__":
    main()
