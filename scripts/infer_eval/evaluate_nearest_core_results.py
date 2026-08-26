#!/usr/bin/env python3
"""评估“上行节点路径查询”的全部最短路径推理结果。"""

from __future__ import annotations

import argparse
from pathlib import Path

from task_evaluation_common import (
    PATH_DETAIL_NAMES,
    PATH_METRIC_NAMES,
    add_evaluation_arguments,
    evaluate_path_document,
    run_evaluation,
    validate_evaluation_arguments,
)


DEFAULT_RESULT_PATH = Path("vllm-results/uplink_node_path")
DEFAULT_OUTPUT_DIR = Path("vllm-results/uplink_node_path-evaluation")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    add_evaluation_arguments(
        parser,
        default_result_path=DEFAULT_RESULT_PATH,
        default_output_dir=DEFAULT_OUTPUT_DIR,
        default_project="topology-uplink-node-path",
        default_experiment="uplink-node-path-evaluation",
    )
    args = parser.parse_args()
    validate_evaluation_arguments(parser, args)
    return args


def main() -> None:
    run_evaluation(
        parse_args(),
        task_name="uplink_node_path_query",
        metric_names=PATH_METRIC_NAMES,
        detail_names=PATH_DETAIL_NAMES,
        evaluate_document=evaluate_path_document,
    )


if __name__ == "__main__":
    main()
