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
DEFAULT_SWANLAB_LOG_STEP = 0
DEFAULT_SWANLAB_LOG_PREFIX = "eval"


def read_summary(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_resume(value: str) -> Any:
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    return value


def join_metric_name(prefix: str, name: str) -> str:
    clean_prefix = prefix.strip("/")
    clean_name = name.strip("/")
    return "%s/%s" % (clean_prefix, clean_name) if clean_prefix else clean_name


def log_summary(swanlab: Any, summary: Dict[str, Any], step: int, log_prefix: str) -> None:
    payload: Dict[str, Any] = {
        join_metric_name(log_prefix, "summary/total_files"): summary.get("total_files", 0),
        join_metric_name(log_prefix, "summary/evaluated_files"): summary.get("evaluated_files", 0),
        join_metric_name(log_prefix, "summary/model_error_files"): summary.get("model_error_files", 0),
        join_metric_name(log_prefix, "summary/eval_error_files"): summary.get("eval_error_files", 0),
    }
    total_files = summary.get("total_files", 0)
    model_error_files = summary.get("model_error_files", 0)
    eval_error_files = summary.get("eval_error_files", 0)
    payload[join_metric_name(log_prefix, "summary/model_error_rate")] = (
        model_error_files / total_files if total_files else 0.0
    )
    payload[join_metric_name(log_prefix, "summary/eval_error_rate")] = (
        eval_error_files / total_files if total_files else 0.0
    )

    for split_task, item in summary.get("by_split_task", {}).items():
        prefix = join_metric_name(log_prefix, split_task.replace("/", "/"))
        payload["%s/total_files" % prefix] = item.get("total_files", 0)
        payload["%s/evaluated_files" % prefix] = item.get("evaluated_files", 0)
        payload["%s/model_error_files" % prefix] = item.get("model_error_files", 0)
        payload["%s/eval_error_files" % prefix] = item.get("eval_error_files", 0)
        metrics = item.get("metrics")
        if metrics:
            payload.update(metric_log_values(metrics, prefix=prefix))

    swanlab.log(payload, step=step)


def run(args: argparse.Namespace) -> None:
    swanlab = import_swanlab()
    init_kwargs: Dict[str, Any] = {
        "project": args.swanlab_project,
        "experiment_name": args.swanlab_experiment,
        "mode": args.swanlab_mode,
        "config": base_runtime_config(args),
    }
    if args.swanlab_run_id:
        init_kwargs["id"] = args.swanlab_run_id
        init_kwargs["resume"] = normalize_resume(args.swanlab_resume or "must")
    elif args.swanlab_resume:
        init_kwargs["resume"] = normalize_resume(args.swanlab_resume)
    swanlab.init(**init_kwargs)
    batch_evaluate_qa.run(args)
    summary = read_summary(args.output_root / "summary.json")
    log_summary(swanlab, summary, step=args.swanlab_log_step, log_prefix=args.swanlab_log_prefix)
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
    parser.add_argument("--swanlab-run-id", default="", help="Existing SwanLab experiment ID to resume.")
    parser.add_argument(
        "--swanlab-resume",
        default="",
        choices=["", "must", "allow", "never", "true", "false"],
        help="SwanLab resume mode. If --swanlab-run-id is set, default is must.",
    )
    parser.add_argument(
        "--swanlab-log-step",
        type=int,
        default=DEFAULT_SWANLAB_LOG_STEP,
        help="Step used when logging aggregate evaluation metrics.",
    )
    parser.add_argument(
        "--swanlab-log-prefix",
        default=DEFAULT_SWANLAB_LOG_PREFIX,
        help="Metric namespace prefix for evaluation logs. Default: eval.",
    )
    return parser.parse_args()


def main() -> None:
    run(parse_args())


if __name__ == "__main__":
    main()
