#!/usr/bin/env python3
"""评估指定 VLAN 下的交换机约束最短路径推理结果。"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from task_evaluation_common import (
    PATH_DETAIL_NAMES,
    PATH_METRIC_NAMES,
    add_evaluation_arguments,
    evaluate_path_document,
    run_evaluation,
    validate_evaluation_arguments,
)


DEFAULT_RESULT_PATH = Path("vllm-results/vlan_constrained_shortest_path")
DEFAULT_OUTPUT_DIR = Path(
    "vllm-results/vlan_constrained_shortest_path-evaluation"
)

METRIC_NAMES = ("vlan_id_accuracy", *PATH_METRIC_NAMES)
DETAIL_NAMES = PATH_DETAIL_NAMES


def evaluate_document(
    document: dict[str, Any],
) -> tuple[dict[str, float], dict[str, int]]:
    path_metrics, details = evaluate_path_document(document)
    metrics = {"vlan_id_accuracy": 0.0, **path_metrics}
    answer = document.get("task_answer")
    prediction = document.get("model-output")
    if not isinstance(answer, dict) or not isinstance(prediction, dict):
        return metrics, details

    gold_vlan_id = answer.get("vlan_id")
    predicted_vlan_id = prediction.get("vlan_id")
    metrics["vlan_id_accuracy"] = float(
        not isinstance(gold_vlan_id, bool)
        and isinstance(gold_vlan_id, int)
        and not isinstance(predicted_vlan_id, bool)
        and isinstance(predicted_vlan_id, int)
        and predicted_vlan_id == gold_vlan_id
    )
    return metrics, details


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    add_evaluation_arguments(
        parser,
        default_result_path=DEFAULT_RESULT_PATH,
        default_output_dir=DEFAULT_OUTPUT_DIR,
        default_project="topology-vlan-constrained-path",
        default_experiment="vlan-constrained-path-evaluation",
    )
    args = parser.parse_args()
    validate_evaluation_arguments(parser, args)
    return args


def main() -> None:
    run_evaluation(
        parse_args(),
        task_name="vlan_constrained_shortest_path_detour",
        metric_names=METRIC_NAMES,
        detail_names=DETAIL_NAMES,
        evaluate_document=evaluate_document,
    )


if __name__ == "__main__":
    main()
