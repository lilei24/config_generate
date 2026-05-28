#!/usr/bin/env python3
"""Batch evaluation with SwanLab aggregate metric logging."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

import batch_evaluate_qa
from batch_evaluate_qa import (
    DEFAULT_GOLD_KEY,
    DEFAULT_OUTPUT_ROOT,
    DEFAULT_PRED_KEYS,
    DEFAULT_PROGRESS_INTERVAL,
    DEFAULT_RESULT_ROOT,
    DEFAULT_SPLITS,
    DEFAULT_TASKS,
)
from swanlab_utils import base_runtime_config, finish_swanlab, import_swanlab, metric_log_values


DEFAULT_SWANLAB_PROJECT = "config-generation"
DEFAULT_SWANLAB_EXPERIMENT = "qwen3-8b-evaluation"
DEFAULT_SWANLAB_MODE = "cloud"


def read_summary(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def log_summary(swanlab: Any, summary: Dict[str, Any]) -> None:
    payload: Dict[str, Any] = {
        "summary/total_files": summary.get("total_files", 0),
        "summary/evaluated_files": summary.get("evaluated_files", 0),
        "summary/model_error_files": summary.get("model_error_files", 0),
        "summary/eval_error_files": summary.get("eval_error_files", 0),
    }
    total_files = payload["summary/total_files"]
    payload["summary/model_error_rate"] = payload["summary/model_error_files"] / total_files if total_files else 0.0
    payload["summary/eval_error_rate"] = payload["summary/eval_error_files"] / total_files if total_files else 0.0

    for split_task, item in summary.get("by_split_task", {}).items():
        prefix = split_task.replace("/", "/")
        payload["%s/total_files" % prefix] = item.get("total_files", 0)
        payload["%s/evaluated_files" % prefix] = item.get("evaluated_files", 0)
        payload["%s/model_error_files" % prefix] = item.get("model_error_files", 0)
        payload["%s/eval_error_files" % prefix] = item.get("eval_error_files", 0)
        metrics = item.get("metrics")
        if metrics:
            payload.update(metric_log_values(metrics, prefix=prefix))

    swanlab.log(payload, step=0)


def run(args: argparse.Namespace) -> None:
    swanlab = import_swanlab()
    swanlab.init(
        project=args.swanlab_project,
        experiment_name=args.swanlab_experiment,
        mode=args.swanlab_mode,
        config=base_runtime_config(args),
    )
    batch_evaluate_qa.run(args)
    summary = read_summary(args.output_root / "summary.json")
    log_summary(swanlab, summary)
    finish_swanlab(swanlab)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Batch evaluate inference results and log aggregate metrics to SwanLab.")
    parser.add_argument("--result-root", type=Path, default=DEFAULT_RESULT_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--splits", default=DEFAULT_SPLITS)
    parser.add_argument("--tasks", default=DEFAULT_TASKS)
    parser.add_argument("--pred-keys", default=",".join(DEFAULT_PRED_KEYS))
    parser.add_argument("--gold-key", default=DEFAULT_GOLD_KEY)
    parser.add_argument("--array-mode", choices=["wildcard", "index"], default="wildcard")
    parser.add_argument("--progress-interval", type=int, default=DEFAULT_PROGRESS_INTERVAL)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--swanlab-project", default=DEFAULT_SWANLAB_PROJECT)
    parser.add_argument("--swanlab-experiment", default=DEFAULT_SWANLAB_EXPERIMENT)
    parser.add_argument("--swanlab-mode", default=DEFAULT_SWANLAB_MODE)
    return parser.parse_args()


def main() -> None:
    run(parse_args())


if __name__ == "__main__":
    main()
