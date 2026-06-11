#!/usr/bin/env python3
"""Batch evaluate inference result JSON files."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median
from typing import Any, Dict, Iterable, List, Optional, Tuple
from xml.sax.saxutils import escape

from metric import evaluate_json


DEFAULT_RESULT_ROOT = Path("inference-results")
DEFAULT_OUTPUT_ROOT = Path("metric-results/token-metric-analysis")
DEFAULT_QA_ROOT = Path("520QA")
DEFAULT_SPLITS = "train"
DEFAULT_TASKS = "node_config_qa"
DEFAULT_PRED_KEYS = ("model-output", "model_output", "model-ouput")
DEFAULT_GOLD_KEY = "answer"
DEFAULT_PROGRESS_INTERVAL = 500
DEFAULT_TOKEN_BINS = "4096,8192,16384,32768,65536,131072,262144,524288,1048576,2097152"


TOKEN_METRIC_CSV_FIELDS = [
    "split",
    "task",
    "file",
    "qa_file",
    "status",
    "error",
    "input_token_count",
    "input_char_count",
    "input_byte_count",
    "input_node_count",
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


TOKEN_BIN_CSV_FIELDS = [
    "split",
    "task",
    "token_bin",
    "token_min_exclusive",
    "token_max_inclusive",
    "total_files",
    "evaluated_files",
    "model_error_files",
    "eval_error_files",
    "input_token_mean",
    "input_token_median",
    "field_path_precision",
    "field_path_recall",
    "field_path_f1",
    "leaf_triple_precision",
    "leaf_triple_recall",
    "leaf_triple_f1",
    "value_accuracy",
    "hallucinated_rate",
    "missing_rate",
]


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


def stable_json_text(value: Any) -> str:
    """把 input 字段转成稳定 JSON 文本，并保留原字段顺序。"""

    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def rough_bpe_token_count(text: str) -> int:
    """粗略估算 BPE token 数。

    规则与 scripts/analyze_qa_tokens.py 保持一致，用于比较样本输入长短和指标
    的关系，不等价于某个具体模型的真实 tokenizer。
    """

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


def input_node_count(input_value: Any) -> int:
    if not isinstance(input_value, dict):
        return 0
    nodes = input_value.get("nodes")
    return len(nodes) if isinstance(nodes, list) else 0


def qa_path_for_result(result_root: Path, qa_root: Path, split: str, task: str, result_path_value: Path) -> Path:
    rel = result_path_value.relative_to(result_root / split / task)
    return qa_root / split / task / rel


def load_qa_input_stats(qa_path: Path) -> Tuple[Dict[str, Any], str]:
    sample, error = read_json(qa_path)
    if error:
        return {
            "qa_file": str(qa_path),
            "input_token_count": 0,
            "input_char_count": 0,
            "input_byte_count": 0,
            "input_node_count": 0,
        }, "qa_%s" % error
    if sample is None or "input" not in sample:
        return {
            "qa_file": str(qa_path),
            "input_token_count": 0,
            "input_char_count": 0,
            "input_byte_count": 0,
            "input_node_count": 0,
        }, "qa_missing_input"

    input_value = sample["input"]
    text = stable_json_text(input_value)
    return {
        "qa_file": str(qa_path),
        "input_token_count": rough_bpe_token_count(text),
        "input_char_count": len(text),
        "input_byte_count": len(text.encode("utf-8")),
        "input_node_count": input_node_count(input_value),
    }, ""


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


def write_csv(path: Path, rows: List[Dict[str, Any]], fieldnames: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def parse_token_bins(text: str) -> List[int]:
    bins = sorted({int(item.strip()) for item in text.split(",") if item.strip()})
    return [value for value in bins if value > 0]


def token_bin_label(token_count: int, thresholds: List[int]) -> Tuple[str, int, int]:
    lower = 0
    for threshold in thresholds:
        if token_count <= threshold:
            return "0-%s" % threshold if lower == 0 else "%s-%s" % (lower + 1, threshold), lower, threshold
        lower = threshold
    return ">%s" % thresholds[-1] if thresholds else "all", thresholds[-1] if thresholds else 0, -1


def metric_row_values(metric: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not metric:
        return {
            "field_path_precision": "",
            "field_path_recall": "",
            "field_path_f1": "",
            "leaf_triple_precision": "",
            "leaf_triple_recall": "",
            "leaf_triple_f1": "",
            "value_accuracy": "",
            "hallucinated_rate": "",
            "missing_rate": "",
            "top_level_exact_match": "",
        }
    return {
        "field_path_precision": metric["field_path"]["precision"],
        "field_path_recall": metric["field_path"]["recall"],
        "field_path_f1": metric["field_path"]["f1"],
        "leaf_triple_precision": metric["leaf_triple"]["precision"],
        "leaf_triple_recall": metric["leaf_triple"]["recall"],
        "leaf_triple_f1": metric["leaf_triple"]["f1"],
        "value_accuracy": metric["value_accuracy"]["accuracy"],
        "hallucinated_rate": metric["hallucination_missing"]["hallucinated_rate"],
        "missing_rate": metric["hallucination_missing"]["missing_rate"],
        "top_level_exact_match": int(bool(metric["top_level_config"].get("exact_match"))),
    }


def token_summary(values: List[int]) -> Dict[str, Any]:
    if not values:
        return {
            "count": 0,
            "min": 0,
            "max": 0,
            "mean": 0,
            "median": 0,
        }
    return {
        "count": len(values),
        "min": min(values),
        "max": max(values),
        "mean": mean(values),
        "median": median(values),
    }


def summarize_token_metric_bins(
    rows: List[Dict[str, Any]],
    bin_accumulators: Dict[Tuple[str, str, str], Dict[str, Any]],
    thresholds: List[int],
) -> List[Dict[str, Any]]:
    row_groups: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        row_groups[(row["split"], row["task"], row["token_bin"])].append(row)

    output_rows: List[Dict[str, Any]] = []
    for key in sorted(row_groups):
        split, task, token_bin = key
        group_rows = row_groups[key]
        token_counts = [int(row["input_token_count"]) for row in group_rows]
        _, lower, upper = token_bin_label(token_counts[0], thresholds) if token_counts else (token_bin, 0, 0)
        evaluated_rows = [row for row in group_rows if row["status"] == "ok"]
        model_error_rows = [row for row in group_rows if row["status"] == "model_error"]
        eval_error_rows = [row for row in group_rows if row["status"] == "eval_error"]
        bin_metrics = finalize_accumulator(bin_accumulators[key]) if key in bin_accumulators else {}
        row = {
            "split": split,
            "task": task,
            "token_bin": token_bin,
            "token_min_exclusive": lower,
            "token_max_inclusive": upper,
            "total_files": len(group_rows),
            "evaluated_files": len(evaluated_rows),
            "model_error_files": len(model_error_rows),
            "eval_error_files": len(eval_error_rows),
            "input_token_mean": mean(token_counts) if token_counts else 0,
            "input_token_median": median(token_counts) if token_counts else 0,
        }
        row.update(metric_row_values(bin_metrics if bin_metrics else None))
        output_rows.append(row)
    return output_rows


def write_token_metric_svg(path: Path, bin_rows: List[Dict[str, Any]]) -> None:
    """写一张轻量 SVG，用于观察 token 分桶和核心指标的关系。"""

    plot_rows = [row for row in bin_rows if row.get("evaluated_files", 0) and row.get("token_max_inclusive", -1) != -1]
    if not plot_rows:
        return

    width = 980
    height = 520
    margin_left = 80
    margin_right = 40
    margin_top = 40
    margin_bottom = 95
    plot_width = width - margin_left - margin_right
    plot_height = height - margin_top - margin_bottom
    max_x = max(float(row["token_max_inclusive"]) for row in plot_rows) or 1.0
    metrics = [
        ("field_path_f1", "#2563eb", "field_path_f1"),
        ("leaf_triple_f1", "#16a34a", "leaf_triple_f1"),
        ("value_accuracy", "#dc2626", "value_accuracy"),
    ]

    def x_pos(token_value: float) -> float:
        return margin_left + (token_value / max_x) * plot_width

    def y_pos(value: float) -> float:
        return margin_top + (1.0 - max(0.0, min(1.0, value))) * plot_height

    elements = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="%s" height="%s" viewBox="0 0 %s %s">' % (width, height, width, height),
        '<rect width="100%" height="100%" fill="white"/>',
        '<text x="%s" y="24" font-size="18" font-family="Arial" fill="#111827">Token bins vs metrics</text>' % margin_left,
        '<line x1="%s" y1="%s" x2="%s" y2="%s" stroke="#111827" stroke-width="1"/>'
        % (margin_left, margin_top + plot_height, margin_left + plot_width, margin_top + plot_height),
        '<line x1="%s" y1="%s" x2="%s" y2="%s" stroke="#111827" stroke-width="1"/>'
        % (margin_left, margin_top, margin_left, margin_top + plot_height),
    ]
    for tick in range(0, 6):
        value = tick / 5
        y = y_pos(value)
        elements.append('<line x1="%s" y1="%s" x2="%s" y2="%s" stroke="#e5e7eb"/>' % (margin_left, y, margin_left + plot_width, y))
        elements.append('<text x="%s" y="%s" font-size="12" text-anchor="end" font-family="Arial" fill="#374151">%.1f</text>' % (margin_left - 8, y + 4, value))

    for metric_name, color, label in metrics:
        points = []
        for row in plot_rows:
            value = row.get(metric_name, "")
            if value == "":
                continue
            x = x_pos(float(row["token_max_inclusive"]))
            y = y_pos(float(value))
            points.append((x, y, row))
        if len(points) >= 2:
            elements.append(
                '<polyline fill="none" stroke="%s" stroke-width="2" points="%s"/>'
                % (color, " ".join("%.2f,%.2f" % (x, y) for x, y, _ in points))
            )
        for x, y, row in points:
            title = "%s %s %s=%s tokens=%s files=%s" % (
                row["split"],
                row["task"],
                metric_name,
                row.get(metric_name, ""),
                row["token_bin"],
                row["evaluated_files"],
            )
            elements.append(
                '<circle cx="%.2f" cy="%.2f" r="4" fill="%s"><title>%s</title></circle>'
                % (x, y, color, escape(title))
            )

    for row in plot_rows:
        x = x_pos(float(row["token_max_inclusive"]))
        label = str(row["token_max_inclusive"])
        elements.append(
            '<text x="%.2f" y="%s" font-size="11" text-anchor="end" transform="rotate(-35 %.2f %s)" font-family="Arial" fill="#374151">%s</text>'
            % (x, margin_top + plot_height + 24, x, margin_top + plot_height + 24, escape(label))
        )

    legend_x = margin_left + plot_width - 190
    for idx, (_, color, label) in enumerate(metrics):
        y = margin_top + 18 + idx * 22
        elements.append('<rect x="%s" y="%s" width="12" height="12" fill="%s"/>' % (legend_x, y - 10, color))
        elements.append('<text x="%s" y="%s" font-size="13" font-family="Arial" fill="#111827">%s</text>' % (legend_x + 18, y, escape(label)))
    elements.append('<text x="%s" y="%s" font-size="13" text-anchor="middle" font-family="Arial" fill="#111827">input token upper bound</text>' % (margin_left + plot_width / 2, height - 18))
    elements.append('<text x="18" y="%s" font-size="13" text-anchor="middle" transform="rotate(-90 18 %s)" font-family="Arial" fill="#111827">metric value</text>' % (margin_top + plot_height / 2, margin_top + plot_height / 2))
    elements.append("</svg>")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(elements) + "\n", encoding="utf-8")


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
    token_bins = parse_token_bins(args.token_bins)

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
        "qa_root": str(args.qa_root),
        "token_estimator": "rough_bpe",
        "token_bins": token_bins,
        "total_files": len(all_files),
        "evaluated_files": 0,
        "model_error_files": 0,
        "eval_error_files": 0,
        "by_split_task": {},
    }
    accumulators = defaultdict(empty_metric_accumulator)
    bin_accumulators = defaultdict(empty_metric_accumulator)
    error_counter: Counter = Counter()
    token_metric_rows: List[Dict[str, Any]] = []
    token_values_by_key: Dict[str, List[int]] = defaultdict(list)

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
        qa_path = qa_path_for_result(args.result_root, args.qa_root, split, task, path)
        input_stats, input_error = load_qa_input_stats(qa_path)
        token_count = int(input_stats["input_token_count"])
        token_bin, _, _ = token_bin_label(token_count, token_bins)
        token_values_by_key[key_text].append(token_count)
        base_row: Dict[str, Any] = {
            "split": split,
            "task": task,
            "file": str(path),
            **input_stats,
            "token_bin": token_bin,
        }

        record, read_error = read_json(path)
        if read_error:
            summary["eval_error_files"] += 1
            task_summary["eval_error_files"] += 1
            error_counter[(split, task, read_error)] += 1
            append_jsonl(eval_error_path, {"file": str(path), "split": split, "task": task, "error": read_error})
            token_metric_rows.append(
                {
                    **base_row,
                    "status": "eval_error",
                    "error": read_error,
                    **metric_row_values(None),
                }
            )
            if should_print_progress(index, len(all_files), args.progress_interval):
                print_progress(index, len(all_files))
            continue

        if record.get("error") or input_error:
            error = str(record.get("error") or input_error)
            if record.get("error"):
                summary["model_error_files"] += 1
                task_summary["model_error_files"] += 1
                status = "model_error"
            else:
                summary["eval_error_files"] += 1
                task_summary["eval_error_files"] += 1
                status = "eval_error"
            error_counter[(split, task, error)] += 1
            token_metric_rows.append(
                {
                    **base_row,
                    "status": status,
                    "error": error,
                    **metric_row_values(None),
                }
            )
            if should_print_progress(index, len(all_files), args.progress_interval):
                print_progress(index, len(all_files))
            continue

        metric, eval_error = evaluate_one_record(record, pred_keys, args.gold_key, args.array_mode)
        if eval_error:
            summary["eval_error_files"] += 1
            task_summary["eval_error_files"] += 1
            error_counter[(split, task, eval_error)] += 1
            append_jsonl(eval_error_path, {"file": str(path), "split": split, "task": task, "error": eval_error})
            token_metric_rows.append(
                {
                    **base_row,
                    "status": "eval_error",
                    "error": eval_error,
                    **metric_row_values(None),
                }
            )
            if should_print_progress(index, len(all_files), args.progress_interval):
                print_progress(index, len(all_files))
            continue

        add_metric(accumulators[key_text], metric)
        add_metric(bin_accumulators[(split, task, token_bin)], metric)
        summary["evaluated_files"] += 1
        task_summary["evaluated_files"] += 1
        token_metric_rows.append(
            {
                **base_row,
                "status": "ok",
                "error": "",
                **metric_row_values(metric),
            }
        )
        append_jsonl(
            per_file_path,
            {
                "file": str(path),
                "split": split,
                "task": task,
                "qa_file": str(qa_path),
                "input_token_count": token_count,
                "input_node_count": input_stats["input_node_count"],
                "metrics": metric,
            },
        )

        if should_print_progress(index, len(all_files), args.progress_interval):
            print_progress(index, len(all_files))

    for key_text, acc in accumulators.items():
        summary["by_split_task"][key_text]["metrics"] = finalize_accumulator(acc)
    for key_text, values in token_values_by_key.items():
        summary["by_split_task"][key_text]["input_token"] = token_summary(values)

    summary["error_summary"] = [
        {"split": split, "task": task, "error": error, "count": count}
        for (split, task, error), count in error_counter.most_common()
    ]
    token_bin_rows = summarize_token_metric_bins(token_metric_rows, bin_accumulators, token_bins)
    write_csv(args.output_root / "per_file_token_metrics.csv", token_metric_rows, TOKEN_METRIC_CSV_FIELDS + ["token_bin"])
    write_csv(args.output_root / "token_metric_bins.csv", token_bin_rows, TOKEN_BIN_CSV_FIELDS)
    write_token_metric_svg(args.output_root / "token_metric_bins.svg", token_bin_rows)
    write_json(args.output_root / "summary.json", summary)
    write_error_summary_csv(args.output_root / "error_summary.csv", summary["error_summary"])
    print("[metric] done. output: %s" % args.output_root, flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Batch evaluate inference result JSON files.")
    parser.add_argument("--result-root", type=Path, default=DEFAULT_RESULT_ROOT)
    parser.add_argument("--qa-root", type=Path, default=DEFAULT_QA_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--splits", default=DEFAULT_SPLITS)
    parser.add_argument("--tasks", default=DEFAULT_TASKS)
    parser.add_argument("--pred-keys", default=",".join(DEFAULT_PRED_KEYS))
    parser.add_argument("--gold-key", default=DEFAULT_GOLD_KEY)
    parser.add_argument("--array-mode", choices=["wildcard", "index"], default="wildcard")
    parser.add_argument(
        "--token-bins",
        default=DEFAULT_TOKEN_BINS,
        help="Comma-separated token bin upper bounds. Default: %(default)s",
    )
    parser.add_argument("--progress-interval", type=int, default=DEFAULT_PROGRESS_INTERVAL)
    parser.add_argument("--limit", type=int, default=0)
    return parser.parse_args()


def main() -> None:
    run(parse_args())


if __name__ == "__main__":
    main()
