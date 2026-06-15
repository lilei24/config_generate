#!/usr/bin/env python3
"""Analyze metric trends by inference order."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from statistics import mean
from typing import Any, Dict, Iterable, List, Optional, Tuple
from xml.sax.saxutils import escape

from batch_evaluate_qa import (
    DEFAULT_GOLD_KEY,
    DEFAULT_PRED_KEYS,
    DEFAULT_PROGRESS_INTERVAL,
    DEFAULT_RESULT_ROOT,
    add_metric,
    empty_metric_accumulator,
    evaluate_one_record,
    finalize_accumulator,
    iter_result_files,
    metric_row_values,
    read_json,
)


DEFAULT_OUTPUT_ROOT = Path("metric-results/inference-order-analysis")
DEFAULT_SPLITS = "val"
DEFAULT_TASKS = "node_config_qa"
DEFAULT_GROUP_SIZE = 100


PER_FILE_FIELDS = [
    "sequence_index",
    "group_index",
    "split",
    "task",
    "file",
    "status",
    "error",
    "field_path_precision",
    "field_path_recall",
    "field_path_f1",
    "leaf_triple_precision",
    "leaf_triple_recall",
    "leaf_triple_f1",
    "value_accuracy",
    "hallucinated_rate",
    "missing_rate",
    "top_level_exact_match",
]


GROUP_FIELDS = [
    "group_index",
    "sequence_start",
    "sequence_end",
    "split_task_span",
    "total_files",
    "evaluated_files",
    "model_error_files",
    "eval_error_files",
    "error_rate",
    "micro_field_path_precision",
    "micro_field_path_recall",
    "micro_field_path_f1",
    "micro_leaf_triple_precision",
    "micro_leaf_triple_recall",
    "micro_leaf_triple_f1",
    "micro_value_accuracy",
    "micro_hallucinated_rate",
    "micro_missing_rate",
    "micro_top_level_exact_match",
    "macro_field_path_precision",
    "macro_field_path_recall",
    "macro_field_path_f1",
    "macro_leaf_triple_precision",
    "macro_leaf_triple_recall",
    "macro_leaf_triple_f1",
    "macro_value_accuracy",
    "macro_hallucinated_rate",
    "macro_missing_rate",
    "macro_top_level_exact_match",
]


ERROR_FIELDS = [
    "split",
    "task",
    "status",
    "error",
    "count",
]


def parse_csv_values(text: str) -> List[str]:
    return [item.strip() for item in text.split(",") if item.strip()]


def write_csv(path: Path, rows: List[Dict[str, Any]], fieldnames: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def metric_values_for_prefix(metric: Optional[Dict[str, Any]], prefix: str) -> Dict[str, Any]:
    values = metric_row_values(metric)
    return {
        "%s_%s" % (prefix, key): value
        for key, value in values.items()
    }


def mean_metric_values(rows: List[Dict[str, Any]], prefix: str) -> Dict[str, Any]:
    output: Dict[str, Any] = {}
    metric_keys = PER_FILE_FIELDS[-10:]
    ok_rows = [row for row in rows if row["status"] == "ok"]
    for key in metric_keys:
        values = [float(row[key]) for row in ok_rows if row[key] != ""]
        output["%s_%s" % (prefix, key)] = mean(values) if values else ""
    return output


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


def collect_file_rows(args: argparse.Namespace) -> List[Dict[str, Any]]:
    splits = parse_csv_values(args.splits)
    tasks = parse_csv_values(args.tasks)
    pred_keys = parse_csv_values(args.pred_keys)
    files = ordered_result_files(args.result_root, splits, tasks)
    if args.limit:
        files = files[: args.limit]

    rows: List[Dict[str, Any]] = []
    total = len(files)
    print("[order-metric] start: %s files" % total, flush=True)
    for sequence_index, (split, task, path) in enumerate(files, start=1):
        group_index = (sequence_index - 1) // args.group_size + 1
        base = {
            "sequence_index": sequence_index,
            "group_index": group_index,
            "split": split,
            "task": task,
            "file": str(path.relative_to(args.result_root)),
            "status": "eval_error",
            "error": "",
        }
        base.update(metric_row_values(None))

        record, read_error = read_json(path)
        if read_error:
            base["error"] = read_error
            rows.append(base)
        elif record is not None and record.get("error"):
            base["status"] = "model_error"
            base["error"] = str(record["error"])
            rows.append(base)
        elif record is None:
            base["error"] = "empty_record"
            rows.append(base)
        else:
            metric, metric_error = evaluate_one_record(record, pred_keys, args.gold_key, args.array_mode)
            if metric_error:
                base["error"] = metric_error
                rows.append(base)
            else:
                base["status"] = "ok"
                base["_metric"] = metric
                base.update(metric_row_values(metric))
                rows.append(base)

        if args.progress_interval > 0 and (sequence_index % args.progress_interval == 0 or sequence_index == total):
            percent = sequence_index / total * 100 if total else 100.0
            print("[order-metric] %s/%s files (%.2f%%)" % (sequence_index, total, percent), flush=True)
    return rows


def group_rows(file_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[int, List[Dict[str, Any]]] = {}
    for row in file_rows:
        grouped.setdefault(int(row["group_index"]), []).append(row)

    output: List[Dict[str, Any]] = []
    for group_index in sorted(grouped):
        rows = grouped[group_index]
        accumulator = empty_metric_accumulator()
        for row in rows:
            if row["status"] == "ok":
                add_metric(accumulator, row["_metric"])

        evaluated = sum(1 for row in rows if row["status"] == "ok")
        model_errors = sum(1 for row in rows if row["status"] == "model_error")
        eval_errors = sum(1 for row in rows if row["status"] == "eval_error")
        if evaluated:
            aggregate_metric = finalize_accumulator(accumulator)
            micro_values = metric_values_for_prefix(aggregate_metric, "micro")
            micro_values["micro_top_level_exact_match"] = aggregate_metric["top_level_config"][
                "exact_match_rate"
            ]
        else:
            micro_values = metric_values_for_prefix(None, "micro")
        macro_values = mean_metric_values(rows, "macro")
        split_task_span = ",".join(
            "%s/%s" % (split, task)
            for split, task in sorted({(row["split"], row["task"]) for row in rows})
        )
        output.append(
            {
                "group_index": group_index,
                "sequence_start": rows[0]["sequence_index"],
                "sequence_end": rows[-1]["sequence_index"],
                "split_task_span": split_task_span,
                "total_files": len(rows),
                "evaluated_files": evaluated,
                "model_error_files": model_errors,
                "eval_error_files": eval_errors,
                "error_rate": (model_errors + eval_errors) / len(rows) if rows else 0.0,
                **micro_values,
                **macro_values,
            }
        )
    return output


def error_rows(file_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    counts = Counter(
        (row["split"], row["task"], row["status"], row["error"])
        for row in file_rows
        if row["status"] != "ok"
    )
    return [
        {
            "split": split,
            "task": task,
            "status": status,
            "error": error,
            "count": count,
        }
        for (split, task, status, error), count in counts.most_common()
    ]


def write_metric_svg(path: Path, group_rows_value: List[Dict[str, Any]]) -> None:
    plot_rows = [row for row in group_rows_value if row["evaluated_files"]]
    if not plot_rows:
        return

    width = max(980, len(plot_rows) * 42)
    height = 520
    left = 80
    right = 35
    top = 45
    bottom = 80
    plot_width = width - left - right
    plot_height = height - top - bottom
    max_group = max(int(row["group_index"]) for row in plot_rows) or 1
    metrics = [
        ("micro_field_path_f1", "#2563eb"),
        ("micro_leaf_triple_f1", "#16a34a"),
        ("micro_value_accuracy", "#dc2626"),
        ("macro_field_path_f1", "#7c3aed"),
        ("macro_leaf_triple_f1", "#0891b2"),
        ("macro_value_accuracy", "#ea580c"),
    ]

    def x_pos(group_index: int) -> float:
        if max_group <= 1:
            return left + plot_width / 2
        return left + (group_index - 1) / (max_group - 1) * plot_width

    def y_pos(value: float) -> float:
        return top + (1.0 - max(0.0, min(1.0, value))) * plot_height

    elements = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="%s" height="%s" viewBox="0 0 %s %s">' % (width, height, width, height),
        '<rect width="100%" height="100%" fill="white"/>',
        '<text x="%s" y="25" font-size="18" font-family="Arial" fill="#111827">Inference order metric trend</text>' % left,
    ]
    for tick in range(6):
        value = tick / 5
        y = y_pos(value)
        elements.append('<line x1="%s" y1="%s" x2="%s" y2="%s" stroke="#e5e7eb"/>' % (left, y, left + plot_width, y))
        elements.append('<text x="%s" y="%s" font-size="12" text-anchor="end" font-family="Arial">%.1f</text>' % (left - 8, y + 4, value))

    for metric_name, color in metrics:
        points = []
        for row in plot_rows:
            value = row.get(metric_name, "")
            if value == "":
                continue
            points.append((x_pos(int(row["group_index"])), y_pos(float(value)), row))
        if len(points) >= 2:
            elements.append(
                '<polyline fill="none" stroke="%s" stroke-width="2" points="%s"/>'
                % (color, " ".join("%.2f,%.2f" % (x, y) for x, y, _ in points))
            )
        for x, y, row in points:
            title = "%s=%s group=%s seq=%s-%s files=%s" % (
                metric_name,
                row[metric_name],
                row["group_index"],
                row["sequence_start"],
                row["sequence_end"],
                row["evaluated_files"],
            )
            elements.append('<circle cx="%.2f" cy="%.2f" r="3.5" fill="%s"><title>%s</title></circle>' % (x, y, color, escape(title)))

    legend_x = left + plot_width - 230
    for index, (metric_name, color) in enumerate(metrics):
        legend_y = top + 16 + index * 20
        elements.append('<rect x="%s" y="%s" width="10" height="10" fill="%s"/>' % (legend_x, legend_y - 8, color))
        elements.append('<text x="%s" y="%s" font-size="12" font-family="Arial">%s</text>' % (legend_x + 16, legend_y, escape(metric_name)))
    elements.append('<text x="%s" y="%s" font-size="13" text-anchor="middle" font-family="Arial">group index</text>' % (left + plot_width / 2, height - 18))
    elements.append("</svg>")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(elements) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> None:
    if args.group_size <= 0:
        raise ValueError("--group-size must be positive")

    file_rows = collect_file_rows(args)
    group_rows_value = group_rows(file_rows)
    clean_file_rows = [
        {key: value for key, value in row.items() if not key.startswith("_")}
        for row in file_rows
    ]

    write_csv(args.output_root / "per_file_inference_order_metrics.csv", clean_file_rows, PER_FILE_FIELDS)
    write_csv(args.output_root / "inference_order_group_metrics.csv", group_rows_value, GROUP_FIELDS)
    write_csv(args.output_root / "inference_order_errors.csv", error_rows(file_rows), ERROR_FIELDS)
    write_metric_svg(args.output_root / "inference_order_metric_trend.svg", group_rows_value)
    write_json(
        args.output_root / "summary.json",
        {
            "result_root": str(args.result_root),
            "output_root": str(args.output_root),
            "splits": parse_csv_values(args.splits),
            "tasks": parse_csv_values(args.tasks),
            "group_size": args.group_size,
            "array_mode": args.array_mode,
            "order_definition": (
                "For each split in --splits order, files are read in --tasks order; "
                "inside each task directory, paths use sorted(rglob('*.json')), matching inference order."
            ),
            "total_files": len(file_rows),
            "group_count": len(group_rows_value),
            "evaluated_files": sum(1 for row in file_rows if row["status"] == "ok"),
            "model_error_files": sum(1 for row in file_rows if row["status"] == "model_error"),
            "eval_error_files": sum(1 for row in file_rows if row["status"] == "eval_error"),
        },
    )
    print("[order-metric] done. output: %s" % args.output_root, flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze metric trend by inference order groups.")
    parser.add_argument("--result-root", type=Path, default=DEFAULT_RESULT_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--splits", default=DEFAULT_SPLITS, help="Comma-separated splits, e.g. train,val.")
    parser.add_argument(
        "--tasks",
        default=DEFAULT_TASKS,
        help="Comma-separated task dirs, e.g. node_config_qa,device_config_qa.",
    )
    parser.add_argument("--group-size", type=int, default=DEFAULT_GROUP_SIZE)
    parser.add_argument("--pred-keys", default=",".join(DEFAULT_PRED_KEYS))
    parser.add_argument("--gold-key", default=DEFAULT_GOLD_KEY)
    parser.add_argument("--array-mode", choices=["wildcard", "index"], default="wildcard")
    parser.add_argument("--progress-interval", type=int, default=DEFAULT_PROGRESS_INTERVAL)
    parser.add_argument("--limit", type=int, default=0)
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
