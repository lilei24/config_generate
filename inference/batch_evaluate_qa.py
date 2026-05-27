#!/usr/bin/env python3
"""Batch evaluate inference result JSON files."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from metric import evaluate_json


DEFAULT_RESULT_ROOT = Path("inference-qwen3-8b")
DEFAULT_OUTPUT_ROOT = Path("metric-results/qwen3-8b")
DEFAULT_SPLITS = "train,val"
DEFAULT_TASKS = "device_config_qa,node_config_qa"
DEFAULT_PRED_KEYS = ("model-ouput", "model-output", "model_output")
DEFAULT_GOLD_KEY = "answer"
DEFAULT_PROGRESS_INTERVAL = 500


def iter_result_files(result_root: Path, split: str, tasks: Iterable[str]) -> Iterable[Tuple[str, Path]]:
    for task in tasks:
        task_root = result_root / split / task
        if not task_root.exists():
            continue
        for path in sorted(task_root.rglob("*.json")):
            if path.is_file():
                yield task, path


def read_json(path: Path) -> Tuple[Optional[Dict[str, Any]], str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return None, "bad_json: %s" % exc
    if not isinstance(data, dict):
        return None, "result_not_object"
    return data, ""


def find_pred_key(record: Dict[str, Any], pred_keys: Iterable[str]) -> Optional[str]:
    for key in pred_keys:
        if key in record:
            return key
    return None


def safe_load_json_value(value: Any) -> Tuple[Optional[Any], str]:
    if not isinstance(value, str):
        return value, ""
    try:
        return json.loads(value), ""
    except json.JSONDecodeError as exc:
        return None, "invalid_json_string: %s" % exc


def empty_metric_accumulator() -> Dict[str, Any]:
    return {
        "sample_count": 0,
        "top_level_exact_match": 0,
        "top_level": Counter(),
        "field_path": Counter(),
        "leaf_triple": Counter(),
        "field_name": Counter(),
        "value_accuracy": Counter(),
        "hallucination_missing": Counter(),
    }


def add_prf_counter(target: Counter, metric: Dict[str, Any]) -> None:
    target["correct"] += metric.get("correct", 0)
    target["pred_total"] += metric.get("pred_total", 0)
    target["gold_total"] += metric.get("gold_total", 0)


def add_metric(acc: Dict[str, Any], metric: Dict[str, Any]) -> None:
    acc["sample_count"] += 1
    top = metric["top_level_config"]
    if top.get("exact_match"):
        acc["top_level_exact_match"] += 1
    add_prf_counter(acc["top_level"], top)
    add_prf_counter(acc["field_path"], metric["field_path"])
    add_prf_counter(acc["leaf_triple"], metric["leaf_triple"])
    add_prf_counter(acc["field_name"], metric["field_name"])

    value_accuracy = metric["value_accuracy"]
    acc["value_accuracy"]["correct_value_count"] += value_accuracy.get("correct_value_count", 0)
    acc["value_accuracy"]["matched_leaf_path_count"] += value_accuracy.get("matched_leaf_path_count", 0)

    hm = metric["hallucination_missing"]
    acc["hallucination_missing"]["hallucinated_count"] += hm.get("hallucinated_count", 0)
    acc["hallucination_missing"]["missing_count"] += hm.get("missing_count", 0)
    acc["hallucination_missing"]["pred_total"] += hm.get("pred_total", 0)
    acc["hallucination_missing"]["gold_total"] += hm.get("gold_total", 0)


def prf_from_counts(counts: Counter) -> Dict[str, Any]:
    correct = counts["correct"]
    pred_total = counts["pred_total"]
    gold_total = counts["gold_total"]
    precision = correct / pred_total if pred_total else 0.0
    recall = correct / gold_total if gold_total else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "correct": correct,
        "pred_total": pred_total,
        "gold_total": gold_total,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def finalize_accumulator(acc: Dict[str, Any]) -> Dict[str, Any]:
    sample_count = acc["sample_count"]
    value_counts = acc["value_accuracy"]
    matched_leaf_path_count = value_counts["matched_leaf_path_count"]
    hm = acc["hallucination_missing"]
    return {
        "sample_count": sample_count,
        "top_level_config": {
            **prf_from_counts(acc["top_level"]),
            "exact_match_count": acc["top_level_exact_match"],
            "exact_match_rate": acc["top_level_exact_match"] / sample_count if sample_count else 0.0,
        },
        "field_path": prf_from_counts(acc["field_path"]),
        "leaf_triple": prf_from_counts(acc["leaf_triple"]),
        "field_name": prf_from_counts(acc["field_name"]),
        "value_accuracy": {
            "correct_value_count": value_counts["correct_value_count"],
            "matched_leaf_path_count": matched_leaf_path_count,
            "accuracy": value_counts["correct_value_count"] / matched_leaf_path_count
            if matched_leaf_path_count
            else 0.0,
        },
        "hallucination_missing": {
            "hallucinated_count": hm["hallucinated_count"],
            "missing_count": hm["missing_count"],
            "pred_total": hm["pred_total"],
            "gold_total": hm["gold_total"],
            "hallucinated_rate": hm["hallucinated_count"] / hm["pred_total"] if hm["pred_total"] else 0.0,
            "missing_rate": hm["missing_count"] / hm["gold_total"] if hm["gold_total"] else 0.0,
        },
    }


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def append_jsonl(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(data, ensure_ascii=False) + "\n")


def write_error_summary_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["split", "task", "error", "count"])
        writer.writeheader()
        writer.writerows(rows)


def print_progress(done: int, total: int) -> None:
    percent = done / total * 100 if total else 100
    print("[metric] %s/%s files (%.2f%%)" % (done, total, percent), flush=True)


def should_print_progress(done: int, total: int, interval: int) -> bool:
    return interval > 0 and (done % interval == 0 or done == total)


def evaluate_one_record(
    record: Dict[str, Any],
    pred_keys: Iterable[str],
    gold_key: str,
    array_mode: str,
) -> Tuple[Optional[Dict[str, Any]], str]:
    pred_key = find_pred_key(record, pred_keys)
    if pred_key is None:
        return None, "missing_prediction_key"
    if gold_key not in record:
        return None, "missing_gold_key: %s" % gold_key

    pred, pred_error = safe_load_json_value(record[pred_key])
    if pred_error:
        return None, pred_error
    gold, gold_error = safe_load_json_value(record[gold_key])
    if gold_error:
        return None, "bad_gold: %s" % gold_error

    try:
        return evaluate_json(pred, gold, array_mode=array_mode), ""
    except Exception as exc:  # noqa: BLE001
        return None, "evaluate_failed: %s" % exc


def run(args: argparse.Namespace) -> None:
    splits = [item.strip() for item in args.splits.split(",") if item.strip()]
    tasks = [item.strip() for item in args.tasks.split(",") if item.strip()]
    pred_keys = [item.strip() for item in args.pred_keys.split(",") if item.strip()]

    all_files: List[Tuple[str, str, Path]] = []
    for split in splits:
        for task, path in iter_result_files(args.result_root, split, tasks):
            all_files.append((split, task, path))

    if args.limit:
        all_files = all_files[: args.limit]

    args.output_root.mkdir(parents=True, exist_ok=True)
    per_file_path = args.output_root / "per_file_metrics.jsonl"
    eval_error_path = args.output_root / "eval_errors.jsonl"
    for path in (per_file_path, eval_error_path):
        if path.exists():
            path.unlink()

    summary: Dict[str, Any] = {
        "result_root": str(args.result_root),
        "total_files": len(all_files),
        "evaluated_files": 0,
        "model_error_files": 0,
        "eval_error_files": 0,
        "by_split_task": {},
    }
    accumulators = defaultdict(empty_metric_accumulator)
    error_counter: Counter = Counter()

    print("[metric] start: %s files" % len(all_files), flush=True)
    for index, (split, task, path) in enumerate(all_files, start=1):
        key = (split, task)
        key_text = "%s/%s" % key
        if key_text not in summary["by_split_task"]:
            summary["by_split_task"][key_text] = {
                "total_files": 0,
                "evaluated_files": 0,
                "model_error_files": 0,
                "eval_error_files": 0,
            }
        task_summary = summary["by_split_task"][key_text]
        task_summary["total_files"] += 1

        record, read_error = read_json(path)
        if read_error:
            summary["eval_error_files"] += 1
            task_summary["eval_error_files"] += 1
            error_counter[(split, task, read_error)] += 1
            append_jsonl(eval_error_path, {"file": str(path), "split": split, "task": task, "error": read_error})
            if should_print_progress(index, len(all_files), args.progress_interval):
                print_progress(index, len(all_files))
            continue

        if record.get("error"):
            error = str(record["error"])
            summary["model_error_files"] += 1
            task_summary["model_error_files"] += 1
            error_counter[(split, task, error)] += 1
            if should_print_progress(index, len(all_files), args.progress_interval):
                print_progress(index, len(all_files))
            continue

        metric, eval_error = evaluate_one_record(record, pred_keys, args.gold_key, args.array_mode)
        if eval_error:
            summary["eval_error_files"] += 1
            task_summary["eval_error_files"] += 1
            error_counter[(split, task, eval_error)] += 1
            append_jsonl(eval_error_path, {"file": str(path), "split": split, "task": task, "error": eval_error})
            if should_print_progress(index, len(all_files), args.progress_interval):
                print_progress(index, len(all_files))
            continue

        add_metric(accumulators[key_text], metric)
        summary["evaluated_files"] += 1
        task_summary["evaluated_files"] += 1
        append_jsonl(
            per_file_path,
            {
                "file": str(path),
                "split": split,
                "task": task,
                "metrics": metric,
            },
        )

        if should_print_progress(index, len(all_files), args.progress_interval):
            print_progress(index, len(all_files))

    for key_text, acc in accumulators.items():
        summary["by_split_task"][key_text]["metrics"] = finalize_accumulator(acc)

    summary["error_summary"] = [
        {"split": split, "task": task, "error": error, "count": count}
        for (split, task, error), count in error_counter.most_common()
    ]
    write_json(args.output_root / "summary.json", summary)
    write_error_summary_csv(args.output_root / "error_summary.csv", summary["error_summary"])
    print("[metric] done. output: %s" % args.output_root, flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Batch evaluate inference result JSON files.")
    parser.add_argument("--result-root", type=Path, default=DEFAULT_RESULT_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--splits", default=DEFAULT_SPLITS)
    parser.add_argument("--tasks", default=DEFAULT_TASKS)
    parser.add_argument("--pred-keys", default=",".join(DEFAULT_PRED_KEYS))
    parser.add_argument("--gold-key", default=DEFAULT_GOLD_KEY)
    parser.add_argument("--array-mode", choices=["wildcard", "index"], default="wildcard")
    parser.add_argument("--progress-interval", type=int, default=DEFAULT_PROGRESS_INTERVAL)
    parser.add_argument("--limit", type=int, default=0)
    return parser.parse_args()


def main() -> None:
    run(parse_args())


if __name__ == "__main__":
    main()
