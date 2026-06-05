#!/usr/bin/env python3
"""Analyze token distribution of model outputs in inference result JSON files."""

from __future__ import annotations

import argparse
import csv
import json
import math
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import mean, median
from typing import Any, DefaultDict, Dict, Iterable, List, Optional, Tuple
from xml.sax.saxutils import escape


DEFAULT_RESULT_ROOT = Path("inference-results")
DEFAULT_OUTPUT_ROOT = Path("model-output-token-analysis")
DEFAULT_SPLITS = "train"
DEFAULT_TASKS = "node_config_qa"
DEFAULT_PRED_KEYS = ("model-ouput", "model-output", "model_output")
DEFAULT_PROGRESS_INTERVAL = 500
DEFAULT_THRESHOLDS = "4096,8192,16384,32768,65536,131072,262144,524288,1048576,2097152"
DEFAULT_HISTOGRAM_BINS = 40


COUNT_FIELDS = [
    "split",
    "task",
    "file",
    "status",
    "error",
    "prediction_key",
    "token_count",
    "char_count",
    "byte_count",
    "value_type",
]


SUMMARY_FIELDS = [
    "split",
    "task",
    "status",
    "count",
    "min",
    "max",
    "mean",
    "median",
    "p50",
    "p75",
    "p90",
    "p95",
    "p99",
    "p100",
    "error_files",
    "model_error_files",
]


THRESHOLD_FIELDS = [
    "split",
    "task",
    "threshold",
    "sample_count",
    "ratio",
    "total_ok_samples",
]


HISTOGRAM_FIELDS = [
    "split",
    "task",
    "bin_start",
    "bin_end",
    "count",
]


QUANTILE_FIELDS = [
    "split",
    "task",
    "quantile",
    "token_count",
]


QUANTILES = [
    ("p50", 0.50),
    ("p75", 0.75),
    ("p90", 0.90),
    ("p95", 0.95),
    ("p99", 0.99),
    ("p100", 1.00),
]


@dataclass(frozen=True)
class TokenRow:
    split: str
    task: str
    file: str
    status: str
    error: str
    prediction_key: str
    token_count: int
    char_count: int
    byte_count: int
    value_type: str


def iter_result_files(result_root: Path, splits: Iterable[str], tasks: Iterable[str]) -> Iterable[Tuple[str, str, Path]]:
    """Enumerate result JSON files as result_root/<split>/<task>/*.json."""

    for split in splits:
        for task in tasks:
            task_root = result_root / split / task
            if not task_root.exists():
                continue
            for path in sorted(task_root.rglob("*.json")):
                if path.is_file():
                    yield split, task, path


def read_json(path: Path) -> Tuple[Optional[Dict[str, Any]], str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - bad result files are recorded.
        return None, "bad_json: %s" % exc
    if not isinstance(data, dict):
        return None, "result_not_object"
    return data, ""


def find_prediction_key(record: Dict[str, Any], pred_keys: Iterable[str]) -> Optional[str]:
    for key in pred_keys:
        if key in record:
            return key
    return None


def model_output_text(value: Any) -> str:
    """Convert a model output value to text for token estimation."""

    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def value_type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def rough_bpe_token_count(text: str) -> int:
    """Rough BPE-like token estimate, aligned with the existing QA token analysis."""

    count = 0
    index = 0
    while index < len(text):
        char = text[index]
        code = ord(char)
        if char.isspace():
            index += 1
            continue
        if 0x4E00 <= code <= 0x9FFF:
            count += 1
            index += 1
            continue
        if char.isascii() and (char.isalnum() or char in "_-./"):
            start = index
            while index < len(text):
                current = text[index]
                if current.isascii() and (current.isalnum() or current in "_-./"):
                    index += 1
                    continue
                break
            count += max(1, math.ceil((index - start) / 4))
            continue
        count += 1
        index += 1
    return count


def parse_csv_values(text: str) -> List[str]:
    return [item.strip() for item in text.split(",") if item.strip()]


def parse_int_csv(text: str) -> List[int]:
    return sorted({int(item) for item in parse_csv_values(text) if int(item) > 0})


def quantile(sorted_values: List[int], q: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    pos = (len(sorted_values) - 1) * q
    lower = math.floor(pos)
    upper = math.ceil(pos)
    if lower == upper:
        return float(sorted_values[lower])
    weight = pos - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def token_stats(values: List[int]) -> Dict[str, Any]:
    if not values:
        return {
            "count": 0,
            "min": 0,
            "max": 0,
            "mean": 0,
            "median": 0,
            "p50": 0,
            "p75": 0,
            "p90": 0,
            "p95": 0,
            "p99": 0,
            "p100": 0,
        }
    sorted_values = sorted(values)
    return {
        "count": len(values),
        "min": min(values),
        "max": max(values),
        "mean": mean(values),
        "median": median(values),
        "p50": quantile(sorted_values, 0.50),
        "p75": quantile(sorted_values, 0.75),
        "p90": quantile(sorted_values, 0.90),
        "p95": quantile(sorted_values, 0.95),
        "p99": quantile(sorted_values, 0.99),
        "p100": float(sorted_values[-1]),
    }


def write_csv(path: Path, rows: List[Dict[str, Any]], fieldnames: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def row_to_dict(row: TokenRow) -> Dict[str, Any]:
    return {
        "split": row.split,
        "task": row.task,
        "file": row.file,
        "status": row.status,
        "error": row.error,
        "prediction_key": row.prediction_key,
        "token_count": row.token_count,
        "char_count": row.char_count,
        "byte_count": row.byte_count,
        "value_type": row.value_type,
    }


def collect_rows(
    result_root: Path,
    splits: List[str],
    tasks: List[str],
    pred_keys: List[str],
    progress_interval: int,
) -> List[TokenRow]:
    result_files = list(iter_result_files(result_root, splits, tasks))
    rows: List[TokenRow] = []
    total = len(result_files)
    started_at = time.time()

    if progress_interval > 0:
        print("[model-output-token] start: %s files" % total, flush=True)
        if total == 0:
            print("[model-output-token] 0/0 files (100.00%), elapsed 0.0s, 0.00 files/s, eta 0.0s", flush=True)

    for index, (split, task, path) in enumerate(result_files, start=1):
        file_name = str(path.relative_to(result_root))
        record, read_error = read_json(path)
        if read_error:
            rows.append(TokenRow(split, task, file_name, "error", read_error, "", 0, 0, 0, ""))
        elif record is not None and record.get("error"):
            rows.append(TokenRow(split, task, file_name, "model_error", str(record["error"]), "", 0, 0, 0, ""))
        else:
            assert record is not None
            pred_key = find_prediction_key(record, pred_keys)
            if pred_key is None:
                rows.append(TokenRow(split, task, file_name, "error", "missing_prediction_key", "", 0, 0, 0, ""))
            else:
                value = record[pred_key]
                text = model_output_text(value)
                rows.append(
                    TokenRow(
                        split=split,
                        task=task,
                        file=file_name,
                        status="ok",
                        error="",
                        prediction_key=pred_key,
                        token_count=rough_bpe_token_count(text),
                        char_count=len(text),
                        byte_count=len(text.encode("utf-8")),
                        value_type=value_type_name(value),
                    )
                )

        if progress_interval > 0 and (index % progress_interval == 0 or index == total):
            elapsed = max(0.001, time.time() - started_at)
            speed = index / elapsed
            remaining = max(0, total - index)
            eta = remaining / speed if speed > 0 else 0.0
            percent = index / total * 100 if total else 100.0
            print(
                "[model-output-token] %s/%s files (%.2f%%), elapsed %.1fs, %.2f files/s, eta %.1fs"
                % (index, total, percent, elapsed, speed, eta),
                flush=True,
            )
    return rows


def grouped_ok_values(rows: List[TokenRow]) -> Dict[Tuple[str, str], List[int]]:
    groups: DefaultDict[Tuple[str, str], List[int]] = defaultdict(list)
    for row in rows:
        if row.status == "ok":
            groups[(row.split, row.task)].append(row.token_count)
    return dict(groups)


def error_counts(rows: List[TokenRow]) -> Counter:
    counter: Counter = Counter()
    for row in rows:
        if row.status != "ok":
            counter[(row.split, row.task, row.status, row.error)] += 1
    return counter


def build_summary_rows(rows: List[TokenRow]) -> List[Dict[str, Any]]:
    groups = grouped_ok_values(rows)
    errors = error_counts(rows)
    output_rows: List[Dict[str, Any]] = []
    keys = sorted({(row.split, row.task) for row in rows})
    for split, task in keys:
        values = groups.get((split, task), [])
        stats = token_stats(values)
        error_files = sum(count for (s, t, status, _), count in errors.items() if s == split and t == task and status == "error")
        model_error_files = sum(
            count for (s, t, status, _), count in errors.items() if s == split and t == task and status == "model_error"
        )
        output_rows.append(
            {
                "split": split,
                "task": task,
                "status": "ok",
                **stats,
                "error_files": error_files,
                "model_error_files": model_error_files,
            }
        )
    return output_rows


def build_threshold_rows(rows: List[TokenRow], thresholds: List[int]) -> List[Dict[str, Any]]:
    output_rows: List[Dict[str, Any]] = []
    for (split, task), values in sorted(grouped_ok_values(rows).items()):
        total = len(values)
        for threshold in thresholds:
            sample_count = sum(1 for value in values if value <= threshold)
            output_rows.append(
                {
                    "split": split,
                    "task": task,
                    "threshold": threshold,
                    "sample_count": sample_count,
                    "ratio": sample_count / total if total else 0.0,
                    "total_ok_samples": total,
                }
            )
    return output_rows


def build_quantile_rows(rows: List[TokenRow]) -> List[Dict[str, Any]]:
    output_rows: List[Dict[str, Any]] = []
    for (split, task), values in sorted(grouped_ok_values(rows).items()):
        sorted_values = sorted(values)
        for label, value in QUANTILES:
            output_rows.append(
                {
                    "split": split,
                    "task": task,
                    "quantile": label,
                    "token_count": quantile(sorted_values, value),
                }
            )
    return output_rows


def build_histogram_rows(rows: List[TokenRow], histogram_bins: int) -> List[Dict[str, Any]]:
    output_rows: List[Dict[str, Any]] = []
    for (split, task), values in sorted(grouped_ok_values(rows).items()):
        if not values:
            continue
        max_value = max(values)
        bin_count = max(1, histogram_bins)
        bin_width = max(1, math.ceil((max_value + 1) / bin_count))
        counts = [0 for _ in range(bin_count)]
        for value in values:
            index = min(value // bin_width, bin_count - 1)
            counts[index] += 1
        for index, count in enumerate(counts):
            start = index * bin_width
            end = (index + 1) * bin_width - 1
            output_rows.append(
                {
                    "split": split,
                    "task": task,
                    "bin_start": start,
                    "bin_end": end,
                    "count": count,
                }
            )
    return output_rows


def write_histogram_svg(path: Path, histogram_rows: List[Dict[str, Any]]) -> None:
    if not histogram_rows:
        return
    groups: DefaultDict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for row in histogram_rows:
        groups[(str(row["split"]), str(row["task"]))].append(row)

    panel_width = 880
    panel_height = 260
    margin_left = 70
    margin_right = 25
    margin_top = 45
    margin_bottom = 55
    width = panel_width
    height = panel_height * len(groups)
    elements = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="%s" height="%s" viewBox="0 0 %s %s">' % (width, height, width, height),
        '<rect width="100%" height="100%" fill="white"/>',
    ]

    for panel_index, ((split, task), rows) in enumerate(sorted(groups.items())):
        y_offset = panel_index * panel_height
        plot_width = panel_width - margin_left - margin_right
        plot_height = panel_height - margin_top - margin_bottom
        max_count = max(int(row["count"]) for row in rows) or 1
        bar_width = plot_width / max(1, len(rows))
        elements.append(
            '<text x="%s" y="%s" font-size="16" font-family="Arial" fill="#111827">%s / %s</text>'
            % (margin_left, y_offset + 24, escape(split), escape(task))
        )
        elements.append(
            '<line x1="%s" y1="%s" x2="%s" y2="%s" stroke="#111827"/>'
            % (margin_left, y_offset + margin_top + plot_height, margin_left + plot_width, y_offset + margin_top + plot_height)
        )
        elements.append(
            '<line x1="%s" y1="%s" x2="%s" y2="%s" stroke="#111827"/>'
            % (margin_left, y_offset + margin_top, margin_left, y_offset + margin_top + plot_height)
        )
        for index, row in enumerate(rows):
            count = int(row["count"])
            bar_height = count / max_count * plot_height if max_count else 0
            x = margin_left + index * bar_width
            y = y_offset + margin_top + plot_height - bar_height
            title = "tokens %s-%s count %s" % (row["bin_start"], row["bin_end"], count)
            elements.append(
                '<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" fill="#2563eb"><title>%s</title></rect>'
                % (x, y, max(1.0, bar_width - 1), bar_height, escape(title))
            )
        elements.append(
            '<text x="%s" y="%s" font-size="12" text-anchor="end" font-family="Arial" fill="#374151">%s</text>'
            % (margin_left - 8, y_offset + margin_top + 4, max_count)
        )
        elements.append(
            '<text x="%s" y="%s" font-size="12" text-anchor="middle" font-family="Arial" fill="#111827">model-output token count</text>'
            % (margin_left + plot_width / 2, y_offset + panel_height - 16)
        )
    elements.append("</svg>")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(elements) + "\n", encoding="utf-8")


def write_outputs(
    output_root: Path,
    rows: List[TokenRow],
    thresholds: List[int],
    histogram_bins: int,
    config: Dict[str, Any],
) -> None:
    row_dicts = [row_to_dict(row) for row in rows]
    summary_rows = build_summary_rows(rows)
    quantile_rows = build_quantile_rows(rows)
    threshold_rows = build_threshold_rows(rows, thresholds)
    histogram_rows = build_histogram_rows(rows, histogram_bins)
    errors = [
        {"split": split, "task": task, "status": status, "error": error, "count": count}
        for (split, task, status, error), count in error_counts(rows).most_common()
    ]
    summary = {
        **config,
        "total_files": len(rows),
        "ok_files": sum(1 for row in rows if row.status == "ok"),
        "error_files": sum(1 for row in rows if row.status == "error"),
        "model_error_files": sum(1 for row in rows if row.status == "model_error"),
        "by_split_task": summary_rows,
        "errors": errors,
    }

    write_csv(output_root / "model_output_token_counts.csv", row_dicts, COUNT_FIELDS)
    write_csv(output_root / "model_output_token_summary.csv", summary_rows, SUMMARY_FIELDS)
    write_csv(output_root / "model_output_token_quantiles.csv", quantile_rows, QUANTILE_FIELDS)
    write_csv(output_root / "model_output_token_context_thresholds.csv", threshold_rows, THRESHOLD_FIELDS)
    write_csv(output_root / "model_output_token_histogram.csv", histogram_rows, HISTOGRAM_FIELDS)
    write_json(output_root / "model_output_token_summary.json", summary)
    write_histogram_svg(output_root / "model_output_token_histogram.svg", histogram_rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze model-output token counts from inference result JSON files.")
    parser.add_argument("--result-root", type=Path, default=DEFAULT_RESULT_ROOT, help="Inference result root.")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT, help="Analysis output directory.")
    parser.add_argument("--splits", default=DEFAULT_SPLITS, help="Comma-separated splits, e.g. train,val.")
    parser.add_argument("--tasks", default=DEFAULT_TASKS, help="Comma-separated task dirs, e.g. node_config_qa,device_config_qa.")
    parser.add_argument("--pred-keys", default=",".join(DEFAULT_PRED_KEYS), help="Comma-separated prediction field names.")
    parser.add_argument("--thresholds", default=DEFAULT_THRESHOLDS, help="Comma-separated token thresholds.")
    parser.add_argument("--histogram-bins", type=int, default=DEFAULT_HISTOGRAM_BINS)
    parser.add_argument("--progress-interval", type=int, default=DEFAULT_PROGRESS_INTERVAL)
    parser.add_argument("--limit", type=int, default=0, help="Only analyze first N files after sorting. 0 means all.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    splits = parse_csv_values(args.splits)
    tasks = parse_csv_values(args.tasks)
    pred_keys = parse_csv_values(args.pred_keys)
    thresholds = parse_int_csv(args.thresholds)
    rows = collect_rows(args.result_root, splits, tasks, pred_keys, args.progress_interval)
    if args.limit:
        rows = rows[: args.limit]
    write_outputs(
        output_root=args.output_root,
        rows=rows,
        thresholds=thresholds,
        histogram_bins=args.histogram_bins,
        config={
            "result_root": str(args.result_root),
            "output_root": str(args.output_root),
            "splits": splits,
            "tasks": tasks,
            "prediction_keys": pred_keys,
            "token_estimator": "rough_bpe",
            "thresholds": thresholds,
        },
    )
    print("[model-output-token] done. output: %s" % args.output_root, flush=True)


if __name__ == "__main__":
    main()
