#!/usr/bin/env python3
"""Upload offline macro metrics from existing inference result JSON files to SwanLab."""

from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from batch_evaluate_qa import (
    DEFAULT_GOLD_KEY,
    DEFAULT_PRED_KEYS,
    DEFAULT_PROGRESS_INTERVAL,
    DEFAULT_RESULT_ROOT,
    evaluate_one_record,
    iter_result_files,
    read_json,
)
from swanlab_utils import (
    base_runtime_config,
    finish_swanlab,
    import_swanlab,
    macro_metric_log_values,
    metric_log_values,
)


DEFAULT_SPLITS = "val"
DEFAULT_TASKS = "node_config_qa"
DEFAULT_SWANLAB_PROJECT = "config-generation"
DEFAULT_SWANLAB_EXPERIMENT = "offline-macro-metrics"
DEFAULT_SWANLAB_MODE = "cloud"


def parse_csv_values(text: str) -> List[str]:
    return [item.strip() for item in text.split(",") if item.strip()]


def ordered_result_files(
    result_root: Path,
    splits: Iterable[str],
    tasks: Iterable[str],
) -> List[Tuple[str, str, Path]]:
    files: List[Tuple[str, str, Path]] = []
    task_list = list(tasks)
    for split in splits:
        for task, path in iter_result_files(result_root, split, task_list):
            files.append((split, task, path))
    return files


def log_sample(
    swanlab: Any,
    index: int,
    metrics: Dict[str, Any],
    error: str,
) -> None:
    payload: Dict[str, Any] = {
        "sample/index": index,
        "sample/has_error": int(bool(error)),
        "sample/metric_failed": int(bool(error) or "error" in metrics),
    }
    if not error and "error" not in metrics:
        payload.update(metric_log_values(metrics, prefix="sample"))
    swanlab.log(payload, step=index)


def print_progress(done: int, total: int, started_at: float) -> None:
    elapsed = max(0.001, time.time() - started_at)
    speed = done / elapsed
    remain = max(0, total - done)
    eta = remain / speed if speed > 0 else 0
    percent = done / total * 100 if total else 100.0
    print(
        "[macro-swanlab] %s/%s files (%.2f%%), elapsed %.1fs, %.2f files/s, eta %.1fs"
        % (done, total, percent, elapsed, speed, eta),
        flush=True,
    )


def run(args: argparse.Namespace) -> None:
    splits = parse_csv_values(args.splits)
    tasks = parse_csv_values(args.tasks)
    pred_keys = parse_csv_values(args.pred_keys)
    files = ordered_result_files(args.result_root, splits, tasks)
    if args.limit:
        files = files[: args.limit]

    swanlab = import_swanlab()
    swanlab.init(
        project=args.swanlab_project,
        experiment_name=args.swanlab_experiment,
        mode=args.swanlab_mode,
        config=base_runtime_config(args),
    )

    total = len(files)
    started_at = time.time()
    success_count = 0
    error_count = 0
    eval_metrics: List[Dict[str, Any]] = []
    print("[macro-swanlab] start: %s files" % total, flush=True)
    swanlab.log({"run/total_files": total}, step=0)

    for index, (split, task, path) in enumerate(files, start=1):
        relative_file = str(path.relative_to(args.result_root))
        metrics: Dict[str, Any] = {}
        error = ""

        record, read_error = read_json(path)
        if read_error:
            error = read_error
        elif record is not None and record.get("error"):
            error = str(record["error"])
        elif record is None:
            error = "empty_record"
        else:
            metric, metric_error = evaluate_one_record(record, pred_keys, args.gold_key, args.array_mode)
            if metric_error:
                error = metric_error
            else:
                metrics = metric or {}
                eval_metrics.append(metrics)
                success_count += 1

        if error:
            error_count += 1

        log_sample(swanlab=swanlab, index=index, metrics=metrics, error=error)
        run_payload = {
            "run/processed_files": index,
            "run/success_files": success_count,
            "run/error_files": error_count,
            "run/error_rate": error_count / index if index else 0.0,
        }
        swanlab.log(run_payload, step=index)
        if eval_metrics:
            swanlab.log(macro_metric_log_values(eval_metrics, prefix="eval"), step=index)

        if error:
            print("[macro-swanlab] skip %s: %s" % (relative_file, error), flush=True)
        if args.progress_interval > 0 and (
            index % args.progress_interval == 0 or index == total
        ):
            print_progress(index, total, started_at)

    finish_swanlab(swanlab)
    print("[macro-swanlab] done. success=%s error=%s" % (success_count, error_count), flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Upload per-sample and running macro metrics from existing inference results to SwanLab."
    )
    parser.add_argument("--result-root", type=Path, default=DEFAULT_RESULT_ROOT)
    parser.add_argument("--splits", default=DEFAULT_SPLITS, help="Comma-separated splits, e.g. train,val.")
    parser.add_argument(
        "--tasks",
        default=DEFAULT_TASKS,
        help="Comma-separated task dirs, e.g. node_config_qa,device_config_qa.",
    )
    parser.add_argument("--pred-keys", default=",".join(DEFAULT_PRED_KEYS))
    parser.add_argument("--gold-key", default=DEFAULT_GOLD_KEY)
    parser.add_argument("--array-mode", choices=["wildcard", "index"], default="wildcard")
    parser.add_argument("--limit", type=int, default=0, help="Only process first N files. 0 means all.")
    parser.add_argument("--progress-interval", type=int, default=DEFAULT_PROGRESS_INTERVAL)
    parser.add_argument("--swanlab-project", default=DEFAULT_SWANLAB_PROJECT)
    parser.add_argument("--swanlab-experiment", default=DEFAULT_SWANLAB_EXPERIMENT)
    parser.add_argument("--swanlab-mode", default=DEFAULT_SWANLAB_MODE)
    return parser.parse_args()


def main() -> None:
    run(parse_args())


if __name__ == "__main__":
    main()
