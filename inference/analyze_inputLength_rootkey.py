#!/usr/bin/env python3
"""Analyze input context length × root key vs generation metrics.

This script is intentionally standalone: command-line defaults, JSON metric
logic, token estimation, grouping, and CSV output are all defined here.

Typical inputs:
  inference-results/val/node_config_qa/*.json
  520QA/val/node_config_qa/*.json

The "input length" means the serialized QA sample's ``input`` field, not the
model output length.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import time
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median
from typing import Any, DefaultDict, Dict, Iterable, List, Optional, Tuple
from xml.sax.saxutils import escape


DEFAULT_RESULT_ROOT = Path("inference-results")
DEFAULT_QA_ROOT = Path("520QA")
DEFAULT_OUTPUT_ROOT = Path("metric-results/input-length-rootkey")
DEFAULT_SPLITS = "val"
DEFAULT_TASKS = "node_config_qa"
DEFAULT_PRED_KEYS = "model-output,model_output,model-ouput"
DEFAULT_GOLD_KEY = "answer"
DEFAULT_PROGRESS_INTERVAL = 500
DEFAULT_INPUT_LENGTH_THRESHOLDS = "4096,8192,16384,32768,65536,131072,262144,524288"
DEFAULT_PLOT_METRIC = "leaf_triple_f1"


METRIC_FIELDS = [
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


PER_FILE_FIELDS = [
    "split",
    "task",
    "file",
    "qa_file",
    "status",
    "error",
    "input_token_count",
    "input_char_count",
    "input_byte_count",
    "input_token_group",
    "target_top_level_key",
] + METRIC_FIELDS


GROUP_FIELDS = [
    "split",
    "task",
    "input_token_group",
    "range_min",
    "range_max",
    "total_files",
    "evaluated_files",
    "model_error_files",
    "eval_error_files",
    "error_rate",
] + METRIC_FIELDS


ROOTKEY_GROUP_FIELDS = [
    "split",
    "task",
    "input_token_group",
    "range_min",
    "range_max",
    "target_top_level_key",
    "total_files",
    "evaluated_files",
    "model_error_files",
    "eval_error_files",
    "error_rate",
] + METRIC_FIELDS


TOP_KEY_FIELDS = [
    "split",
    "task",
    "target_top_level_key",
    "total_files",
    "evaluated_files",
    "model_error_files",
    "eval_error_files",
    "error_rate",
    "input_token_min",
    "input_token_max",
    "input_token_mean",
    "input_token_median",
    "input_token_p90",
    "input_token_p95",
    "input_token_p99",
] + METRIC_FIELDS


# ---------------------------------------------------------------------------
# JSON metric utilities
# ---------------------------------------------------------------------------


def _load_json(x: Any) -> Any:
    if isinstance(x, str):
        return json.loads(x)
    return x


def _json_type(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int):
        return "int"
    if isinstance(v, float):
        return "float"
    if isinstance(v, str):
        return "string"
    if isinstance(v, list):
        return "array"
    if isinstance(v, dict):
        return "object"
    return type(v).__name__


def _normalize_value(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False, sort_keys=True)


def _is_leaf(v: Any) -> bool:
    return not isinstance(v, (dict, list))


def _escape_path_key(key: str) -> str:
    return str(key).replace("~", "~0").replace("/", "~1")


def _counter_prf(pred: Counter, gold: Counter) -> Dict[str, Any]:
    pred_total = sum(pred.values())
    gold_total = sum(gold.values())
    correct = sum((pred & gold).values())
    precision = correct / pred_total if pred_total else 0.0
    recall = correct / gold_total if gold_total else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return {
        "correct": correct,
        "pred_total": pred_total,
        "gold_total": gold_total,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def _collect_json_features(obj: Any, base_path: str = "", array_mode: str = "wildcard") -> Dict[str, Counter]:
    field_paths: Counter = Counter()
    field_names: Counter = Counter()
    leaf_paths: Counter = Counter()
    leaf_triples: Counter = Counter()
    leaf_path_values: Counter = Counter()

    def walk(x: Any, path: str) -> None:
        if isinstance(x, dict):
            for key, value in x.items():
                key_str = _escape_path_key(key)
                child_path = f"{path}/{key_str}" if path else f"/{key_str}"
                field_paths[child_path] += 1
                field_names[key_str] += 1
                if _is_leaf(value):
                    value_type = _json_type(value)
                    value_norm = _normalize_value(value)
                    leaf_paths[child_path] += 1
                    leaf_triples[(child_path, value_type, value_norm)] += 1
                    leaf_path_values[(child_path, value_norm)] += 1
                else:
                    walk(value, child_path)
        elif isinstance(x, list):
            for idx, item in enumerate(x):
                item_path = f"{path}[{idx}]" if array_mode == "index" else f"{path}[]"
                if _is_leaf(item):
                    value_type = _json_type(item)
                    value_norm = _normalize_value(item)
                    leaf_paths[item_path] += 1
                    leaf_triples[(item_path, value_type, value_norm)] += 1
                    leaf_path_values[(item_path, value_norm)] += 1
                else:
                    walk(item, item_path)

    walk(obj, base_path)
    return {
        "field_paths": field_paths,
        "field_names": field_names,
        "leaf_paths": leaf_paths,
        "leaf_triples": leaf_triples,
        "leaf_path_values": leaf_path_values,
    }


def _top_level_config_metric(pred: Any, gold: Any) -> Dict[str, Any]:
    pred_keys = Counter(pred.keys()) if isinstance(pred, dict) else Counter()
    gold_keys = Counter(gold.keys()) if isinstance(gold, dict) else Counter()
    prf = _counter_prf(pred_keys, gold_keys)
    return {
        **prf,
        "exact_match": pred_keys == gold_keys,
        "pred_keys": list(pred_keys.keys()),
        "gold_keys": list(gold_keys.keys()),
        "missing_top_keys": list((gold_keys - pred_keys).keys()),
        "extra_top_keys": list((pred_keys - gold_keys).keys()),
    }


def _value_accuracy_metric(pred_features: Dict[str, Counter], gold_features: Dict[str, Counter]) -> Dict[str, Any]:
    pred_leaf_paths = pred_features["leaf_paths"]
    gold_leaf_paths = gold_features["leaf_paths"]
    matched_path_count = sum((pred_leaf_paths & gold_leaf_paths).values())
    pred_path_values = pred_features["leaf_path_values"]
    gold_path_values = gold_features["leaf_path_values"]
    correct_value_count = sum((pred_path_values & gold_path_values).values())
    accuracy = correct_value_count / matched_path_count if matched_path_count > 0 else 0.0
    return {
        "correct_value_count": correct_value_count,
        "matched_leaf_path_count": matched_path_count,
        "accuracy": accuracy,
    }


def _hallucination_missing_metric(pred_counter: Counter, gold_counter: Counter) -> Dict[str, Any]:
    hallucinated = pred_counter - gold_counter
    missing = gold_counter - pred_counter
    pred_total = sum(pred_counter.values())
    gold_total = sum(gold_counter.values())
    hallucinated_count = sum(hallucinated.values())
    missing_count = sum(missing.values())
    return {
        "hallucinated_count": hallucinated_count,
        "missing_count": missing_count,
        "pred_total": pred_total,
        "gold_total": gold_total,
        "hallucinated_rate": hallucinated_count / pred_total if pred_total else 0.0,
        "missing_rate": missing_count / gold_total if gold_total else 0.0,
    }


def evaluate_json(pred: Any, gold: Any, array_mode: str = "wildcard") -> Dict[str, Any]:
    pred = _load_json(pred)
    gold = _load_json(gold)
    pred_features = _collect_json_features(pred, array_mode=array_mode)
    gold_features = _collect_json_features(gold, array_mode=array_mode)
    return {
        "top_level_config": _top_level_config_metric(pred, gold),
        "field_path": _counter_prf(pred_features["field_paths"], gold_features["field_paths"]),
        "leaf_triple": _counter_prf(pred_features["leaf_triples"], gold_features["leaf_triples"]),
        "value_accuracy": _value_accuracy_metric(pred_features, gold_features),
        "field_name": _counter_prf(pred_features["field_names"], gold_features["field_names"]),
        "hallucination_missing": _hallucination_missing_metric(
            pred_features["field_paths"], gold_features["field_paths"]
        ),
    }


# ---------------------------------------------------------------------------
# Metric accumulation utilities
# ---------------------------------------------------------------------------


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


def _add_prf_counter(target: Counter, metric: Dict[str, Any]) -> None:
    target["correct"] += metric.get("correct", 0)
    target["pred_total"] += metric.get("pred_total", 0)
    target["gold_total"] += metric.get("gold_total", 0)


def add_metric(acc: Dict[str, Any], metric: Dict[str, Any]) -> None:
    acc["sample_count"] += 1
    top = metric["top_level_config"]
    if top.get("exact_match"):
        acc["top_level_exact_match"] += 1
    _add_prf_counter(acc["top_level"], top)
    _add_prf_counter(acc["field_path"], metric["field_path"])
    _add_prf_counter(acc["leaf_triple"], metric["leaf_triple"])
    _add_prf_counter(acc["field_name"], metric["field_name"])
    value_accuracy = metric["value_accuracy"]
    acc["value_accuracy"]["correct_value_count"] += value_accuracy.get("correct_value_count", 0)
    acc["value_accuracy"]["matched_leaf_path_count"] += value_accuracy.get("matched_leaf_path_count", 0)
    hm = metric["hallucination_missing"]
    acc["hallucination_missing"]["hallucinated_count"] += hm.get("hallucinated_count", 0)
    acc["hallucination_missing"]["missing_count"] += hm.get("missing_count", 0)
    acc["hallucination_missing"]["pred_total"] += hm.get("pred_total", 0)
    acc["hallucination_missing"]["gold_total"] += hm.get("gold_total", 0)


def _prf_from_counts(counts: Counter) -> Dict[str, Any]:
    correct = counts["correct"]
    pred_total = counts["pred_total"]
    gold_total = counts["gold_total"]
    precision = correct / pred_total if pred_total else 0.0
    recall = correct / gold_total if gold_total else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
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
            **_prf_from_counts(acc["top_level"]),
            "exact_match_count": acc["top_level_exact_match"],
            "exact_match_rate": acc["top_level_exact_match"] / sample_count if sample_count else 0.0,
        },
        "field_path": _prf_from_counts(acc["field_path"]),
        "leaf_triple": _prf_from_counts(acc["leaf_triple"]),
        "field_name": _prf_from_counts(acc["field_name"]),
        "value_accuracy": {
            "correct_value_count": value_counts["correct_value_count"],
            "matched_leaf_path_count": matched_leaf_path_count,
            "accuracy": (
                value_counts["correct_value_count"] / matched_leaf_path_count if matched_leaf_path_count else 0.0
            ),
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


# ---------------------------------------------------------------------------
# General utilities
# ---------------------------------------------------------------------------


def parse_csv_values(text: str) -> List[str]:
    return [item.strip() for item in text.split(",") if item.strip()]


def parse_int_csv(text: str) -> List[int]:
    values: List[int] = []
    for item in parse_csv_values(text):
        value = int(item)
        if value > 0:
            values.append(value)
    return sorted(set(values))


def read_json(path: Path) -> Tuple[Optional[Dict[str, Any]], str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - bad files are recorded.
        return None, "bad_json: %s" % exc
    if not isinstance(data, dict):
        return None, "json_not_object"
    return data, ""


def write_csv(path: Path, rows: List[Dict[str, Any]], fieldnames: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def iter_result_files(result_root: Path, splits: Iterable[str], tasks: Iterable[str]) -> Iterable[Tuple[str, str, Path]]:
    for split in splits:
        for task in tasks:
            task_root = result_root / split / task
            if not task_root.exists():
                continue
            for path in sorted(task_root.rglob("*.json")):
                if path.is_file():
                    yield split, task, path


def qa_path_for_result(result_root: Path, qa_root: Path, split: str, task: str, result_path: Path) -> Path:
    relative = result_path.relative_to(result_root / split / task)
    return qa_root / split / task / relative


def stable_json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def rough_bpe_token_count(text: str) -> int:
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


def numeric_stats(values: List[int]) -> Dict[str, Any]:
    if not values:
        return {
            "input_token_min": "",
            "input_token_max": "",
            "input_token_mean": "",
            "input_token_median": "",
            "input_token_p90": "",
            "input_token_p95": "",
            "input_token_p99": "",
        }
    sorted_values = sorted(values)
    return {
        "input_token_min": min(values),
        "input_token_max": max(values),
        "input_token_mean": mean(values),
        "input_token_median": median(values),
        "input_token_p90": quantile(sorted_values, 0.90),
        "input_token_p95": quantile(sorted_values, 0.95),
        "input_token_p99": quantile(sorted_values, 0.99),
    }


def input_token_group(token_count: int, thresholds: List[int]) -> Tuple[str, int, str]:
    lower = 0
    for threshold in thresholds:
        if token_count <= threshold:
            label = f"{lower}-{threshold}" if lower == 0 else f"{lower + 1}-{threshold}"
            return label, lower, str(threshold)
        lower = threshold
    return f">{lower}", lower + 1, ""


def compact_token_label(value: Any) -> str:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return str(value)
    if number == 0:
        return "0"
    if number % 1000 == 0:
        return f"{number // 1000}k"
    if number >= 1000:
        return f"{number / 1000:.1f}k".rstrip("0").rstrip(".")
    return str(number)


def compact_token_group_label(group: str, range_min: Any, range_max: Any) -> str:
    if str(group).startswith(">"):
        return f">{compact_token_label(str(group)[1:])}"
    if range_max in ("", None):
        return str(group)
    return f"{compact_token_label(range_min)}-{compact_token_label(range_max)}"


def input_length_values(input_value: Any) -> Dict[str, Any]:
    text = stable_json_text(input_value)
    return {
        "input_token_count": rough_bpe_token_count(text),
        "input_char_count": len(text),
        "input_byte_count": len(text.encode("utf-8")),
    }


def _find_pred_key(record: Dict[str, Any], pred_keys: Iterable[str]) -> Optional[str]:
    for key in pred_keys:
        if key in record:
            return key
    return None


def _safe_load_json_value(value: Any) -> Tuple[Optional[Any], str]:
    if not isinstance(value, str):
        return value, ""
    try:
        return json.loads(value), ""
    except json.JSONDecodeError as exc:
        return None, "invalid_json_string: %s" % exc


def evaluate_one_record(record: Dict[str, Any], pred_keys: Iterable[str], gold_key: str, array_mode: str) -> Tuple[Optional[Dict[str, Any]], str]:
    pred_key = _find_pred_key(record, pred_keys)
    if pred_key is None:
        return None, "missing_prediction_key"
    if gold_key not in record:
        return None, "missing_gold_key: %s" % gold_key
    pred, pred_error = _safe_load_json_value(record[pred_key])
    if pred_error:
        return None, pred_error
    gold, gold_error = _safe_load_json_value(record[gold_key])
    if gold_error:
        return None, "bad_gold: %s" % gold_error
    try:
        return evaluate_json(pred, gold, array_mode=array_mode), ""
    except Exception as exc:  # noqa: BLE001 - recorded as eval_error.
        return None, "evaluate_failed: %s" % exc


def answer_value(record: Dict[str, Any], qa_sample: Dict[str, Any], gold_key: str) -> Tuple[Optional[Any], str]:
    if gold_key in record:
        return _safe_load_json_value(record[gold_key])
    if "output" in qa_sample:
        return qa_sample["output"], ""
    return None, "missing_answer"


def output_top_level_keys(value: Any) -> List[str]:
    return [str(key) for key in value] if isinstance(value, dict) else []


def target_top_level_key(record: Dict[str, Any], qa_sample: Dict[str, Any], gold_key: str) -> Tuple[str, str]:
    metadata = qa_sample.get("metadata")
    target = metadata.get("target") if isinstance(metadata, dict) else None
    config_key = target.get("config_key") if isinstance(target, dict) else None
    if config_key is not None:
        return str(config_key), ""
    answer, answer_error = answer_value(record, qa_sample, gold_key)
    if answer_error:
        return "", answer_error
    keys = output_top_level_keys(answer)
    if not keys:
        return "<non_object_answer>", ""
    return "|".join(keys), ""


# ---------------------------------------------------------------------------
# Row collection
# ---------------------------------------------------------------------------


def empty_metric_values() -> Dict[str, Any]:
    return metric_row_values(None)


def _progress(index: int, total: int, started_at: float, interval: int) -> None:
    if interval > 0 and (index % interval == 0 or index == total):
        elapsed = max(0.001, time.time() - started_at)
        speed = index / elapsed
        eta = (total - index) / speed if speed > 0 else 0.0
        print(
            "[input-length-rootkey] %s/%s files (%.2f%%), %.2f files/s, eta %.1fs"
            % (index, total, index / total * 100 if total else 100.0, speed, eta),
            flush=True,
        )


def collect_rows(args: argparse.Namespace, thresholds: List[int]) -> List[Dict[str, Any]]:
    splits = parse_csv_values(args.splits)
    tasks = parse_csv_values(args.tasks)
    pred_keys = parse_csv_values(args.pred_keys)
    files = list(iter_result_files(args.result_root, splits, tasks))
    if args.limit:
        files = files[: args.limit]

    rows: List[Dict[str, Any]] = []
    started_at = time.time()
    total = len(files)
    print("[input-length-rootkey] start: %s files" % total, flush=True)

    for index, (split, task, result_path) in enumerate(files, start=1):
        base: Dict[str, Any] = {
            "split": split,
            "task": task,
            "file": str(result_path.relative_to(args.result_root)),
            "qa_file": "",
            "status": "eval_error",
            "error": "",
            "input_token_count": 0,
            "input_char_count": 0,
            "input_byte_count": 0,
            "input_token_group": "",
            "range_min": "",
            "range_max": "",
            "target_top_level_key": "",
            **empty_metric_values(),
        }

        qa_path = qa_path_for_result(args.result_root, args.qa_root, split, task, result_path)
        base["qa_file"] = str(qa_path)

        qa_sample, qa_error = read_json(qa_path)
        if qa_error or qa_sample is None:
            base["error"] = "qa_%s" % qa_error
            rows.append(base)
            _progress(index, total, started_at, args.progress_interval)
            continue

        input_value = qa_sample.get("input")
        if not isinstance(input_value, dict):
            base["error"] = "qa_missing_or_invalid_input"
            rows.append(base)
            _progress(index, total, started_at, args.progress_interval)
            continue

        base.update(input_length_values(input_value))
        group, range_min, range_max = input_token_group(base["input_token_count"], thresholds)
        base["input_token_group"] = group
        base["range_min"] = range_min
        base["range_max"] = range_max

        record, result_error = read_json(result_path)
        if result_error or record is None:
            base["error"] = result_error
            rows.append(base)
            _progress(index, total, started_at, args.progress_interval)
            continue

        root_key, root_key_error = target_top_level_key(record, qa_sample, args.gold_key)
        base["target_top_level_key"] = root_key
        if root_key_error:
            base["error"] = root_key_error
            rows.append(base)
            _progress(index, total, started_at, args.progress_interval)
            continue

        if record.get("error"):
            base["status"] = "model_error"
            base["error"] = str(record["error"])
            rows.append(base)
            _progress(index, total, started_at, args.progress_interval)
            continue

        metric, metric_error = evaluate_one_record(record, pred_keys, args.gold_key, args.array_mode)
        if metric_error:
            base["error"] = metric_error
            rows.append(base)
            _progress(index, total, started_at, args.progress_interval)
            continue

        base["status"] = "ok"
        base.update(metric_row_values(metric))
        base["_metric"] = metric
        rows.append(base)
        _progress(index, total, started_at, args.progress_interval)

    return rows


# ---------------------------------------------------------------------------
# Grouping
# ---------------------------------------------------------------------------


def _range_sort_key(group: str, range_min: Any) -> Tuple[int, Any]:
    try:
        return 0, int(range_min)
    except (TypeError, ValueError):
        if str(group).startswith(">"):
            return 1, int(str(group)[1:])
        return 2, str(group)


def _accumulate_group(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    accumulator = empty_metric_accumulator()
    for item in items:
        if item["status"] == "ok":
            add_metric(accumulator, item["_metric"])
    evaluated = sum(1 for item in items if item["status"] == "ok")
    model_errors = sum(1 for item in items if item["status"] == "model_error")
    eval_errors = sum(1 for item in items if item["status"] == "eval_error")
    if evaluated:
        metric = finalize_accumulator(accumulator)
        values = metric_row_values(metric)
        values["top_level_exact_match"] = metric["top_level_config"]["exact_match_rate"]
    else:
        values = empty_metric_values()
    return {
        "total_files": len(items),
        "evaluated_files": evaluated,
        "model_error_files": model_errors,
        "eval_error_files": eval_errors,
        "error_rate": (model_errors + eval_errors) / len(items) if items else 0.0,
        **values,
    }


def group_by_input_length(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: DefaultDict[Tuple[str, str, str, Any, Any], List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = (row["split"], row["task"], row["input_token_group"], row["range_min"], row["range_max"])
        grouped[key].append(row)

    output: List[Dict[str, Any]] = []
    for (split, task, group, range_min, range_max), items in sorted(
        grouped.items(), key=lambda item: (item[0][0], item[0][1], _range_sort_key(item[0][2], item[0][3]))
    ):
        output.append(
            {
                "split": split,
                "task": task,
                "input_token_group": group,
                "range_min": range_min,
                "range_max": range_max,
                **_accumulate_group(items),
            }
        )
    return output


def group_by_input_length_rootkey(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: DefaultDict[Tuple[str, str, str, Any, Any, str], List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = (
            row["split"],
            row["task"],
            row["input_token_group"],
            row["range_min"],
            row["range_max"],
            row["target_top_level_key"],
        )
        grouped[key].append(row)

    output: List[Dict[str, Any]] = []
    for (split, task, group, range_min, range_max, root_key), items in sorted(
        grouped.items(),
        key=lambda item: (
            item[0][0],
            item[0][1],
            _range_sort_key(item[0][2], item[0][3]),
            item[0][5],
        ),
    ):
        output.append(
            {
                "split": split,
                "task": task,
                "input_token_group": group,
                "range_min": range_min,
                "range_max": range_max,
                "target_top_level_key": root_key,
                **_accumulate_group(items),
            }
        )
    return output


def group_by_rootkey(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: DefaultDict[Tuple[str, str, str], List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(row["split"], row["task"], row["target_top_level_key"])].append(row)

    output: List[Dict[str, Any]] = []
    for (split, task, root_key), items in sorted(grouped.items()):
        token_values = [int(item["input_token_count"]) for item in items if item.get("input_token_count") not in ("", None)]
        output.append(
            {
                "split": split,
                "task": task,
                "target_top_level_key": root_key,
                **_accumulate_group(items),
                **numeric_stats(token_values),
            }
        )
    return output


def strip_internal_fields(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [{key: value for key, value in row.items() if not key.startswith("_")} for row in rows]


# ---------------------------------------------------------------------------
# Heatmap
# ---------------------------------------------------------------------------


def metric_label(metric: str) -> str:
    labels = {
        "field_path_precision": "Field Path Precision",
        "field_path_recall": "Field Path Recall",
        "field_path_f1": "Field Path F1",
        "leaf_triple_precision": "Leaf Triple Precision",
        "leaf_triple_recall": "Leaf Triple Recall",
        "leaf_triple_f1": "Leaf Triple F1",
        "value_accuracy": "Value Accuracy",
        "hallucinated_rate": "Hallucinated Rate",
        "missing_rate": "Missing Rate",
        "top_level_exact_match": "Top-Level Exact Match",
    }
    return labels.get(metric, metric)


def metric_value(row: Dict[str, Any], metric: str) -> Optional[float]:
    value = row.get(metric)
    if value in ("", None):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number):
        return None
    return number


def color_for_value(value: Optional[float], vmin: float, vmax: float) -> str:
    if value is None:
        return "#f3f4f6"
    if vmax <= vmin:
        ratio = 1.0
    else:
        ratio = max(0.0, min(1.0, (value - vmin) / (vmax - vmin)))
    # Light yellow -> orange-red, close to YlOrRd but dependency-free.
    stops = [
        (255, 247, 188),
        (254, 196, 79),
        (240, 59, 32),
        (153, 0, 13),
    ]
    scaled = ratio * (len(stops) - 1)
    left = int(math.floor(scaled))
    right = min(left + 1, len(stops) - 1)
    weight = scaled - left
    rgb = tuple(
        int(stops[left][idx] * (1 - weight) + stops[right][idx] * weight)
        for idx in range(3)
    )
    return "#%02x%02x%02x" % rgb


def wrap_text(text: str, max_chars: int) -> List[str]:
    words = text.split()
    if not words:
        return []
    lines: List[str] = []
    current = ""
    for word in words:
        if not current:
            current = word
            continue
        if len(current) + 1 + len(word) <= max_chars:
            current = f"{current} {word}"
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def text_color_for_value(value: Optional[float], vmin: float, vmax: float) -> str:
    if value is None:
        return "#6b7280"
    midpoint = (vmin + vmax) / 2 if vmax > vmin else vmin
    return "white" if value >= midpoint else "#111827"


def build_heatmap_matrix(
    grouped_rows: List[Dict[str, Any]],
    metric: str,
    min_files: int,
) -> Tuple[List[str], List[str], Dict[str, str], Dict[Tuple[str, str], Dict[str, Any]]]:
    columns = sorted(
        {
            (str(row["input_token_group"]), row.get("range_min", ""), row.get("range_max", ""))
            for row in grouped_rows
        },
        key=lambda item: _range_sort_key(item[0], item[1]),
    )
    column_labels = [label for label, _, _ in columns]
    column_display_labels = {
        label: compact_token_group_label(label, range_min, range_max)
        for label, range_min, range_max in columns
    }

    row_totals: Counter = Counter()
    cells: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for row in grouped_rows:
        evaluated = int(row.get("evaluated_files", 0) or 0)
        if evaluated < min_files:
            continue
        root_key = str(row.get("target_top_level_key", ""))
        length_group = str(row.get("input_token_group", ""))
        value = metric_value(row, metric)
        row_totals[root_key] += evaluated
        cells[(root_key, length_group)] = {
            "value": value,
            "evaluated_files": evaluated,
            "total_files": int(row.get("total_files", 0) or 0),
        }

    root_keys = sorted(row_totals, key=lambda key: (-row_totals[key], key))
    return root_keys, column_labels, column_display_labels, cells


def write_input_length_rootkey_heatmap(
    path: Path,
    grouped_rows: List[Dict[str, Any]],
    metric: str,
    min_files: int,
    info: str = "",
) -> None:
    if metric not in METRIC_FIELDS:
        raise ValueError("Unknown plot metric '%s'. Available: %s" % (metric, ", ".join(METRIC_FIELDS)))

    root_keys, column_labels, column_display_labels, cells = build_heatmap_matrix(grouped_rows, metric, min_files)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not root_keys or not column_labels:
        path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="720" height="120">'
            '<rect width="100%" height="100%" fill="white"/>'
            '<text x="24" y="64" font-family="Arial" font-size="16" fill="#111827">'
            'No heatmap data. Try lowering --heatmap-min-files.</text></svg>\n',
            encoding="utf-8",
        )
        return

    vmin = 0.0
    vmax = 1.0

    cell_w = 104
    cell_h = 36
    left = 300
    top = 105
    right = 60
    info_lines = wrap_text(info.strip(), 110) if info.strip() else []
    bottom = 82 + len(info_lines) * 16
    width = left + len(column_labels) * cell_w + right
    height = top + len(root_keys) * cell_h + bottom

    elements = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="%s" height="%s" viewBox="0 0 %s %s">'
        % (width, height, width, height),
        '<rect width="100%" height="100%" fill="white"/>',
        '<text x="24" y="32" font-family="Arial" font-size="18" font-weight="700" fill="#111827">%s</text>'
        % escape("Input Length × Root Key Heatmap"),
        '<text x="24" y="56" font-family="Arial" font-size="13" fill="#374151">metric: %s, min evaluated files per cell: %s</text>'
        % (escape(metric_label(metric)), min_files),
    ]

    for col_index, label in enumerate(column_labels):
        x = left + col_index * cell_w + cell_w / 2
        elements.append(
            '<text x="%.1f" y="%s" font-family="Arial" font-size="12" text-anchor="middle" '
            'fill="#111827">%s</text>'
            % (x, top - 14, escape(column_display_labels.get(label, label)))
        )

    for row_index, root_key in enumerate(root_keys):
        y = top + row_index * cell_h
        label = root_key if len(root_key) <= 42 else root_key[:39] + "..."
        elements.append(
            '<text x="%s" y="%.1f" font-family="Arial" font-size="11" text-anchor="end" '
            'dominant-baseline="middle" fill="#111827"><title>%s</title>%s</text>'
            % (left - 8, y + cell_h / 2, escape(root_key), escape(label))
        )
        for col_index, length_group in enumerate(column_labels):
            x = left + col_index * cell_w
            cell = cells.get((root_key, length_group), {})
            value = cell.get("value")
            fill = color_for_value(value, vmin, vmax)
            title = "%s | %s | %s: %s | evaluated=%s | total=%s" % (
                root_key,
                length_group,
                metric,
                "" if value is None else "%.4f" % value,
                cell.get("evaluated_files", 0),
                cell.get("total_files", 0),
            )
            elements.append(
                '<rect x="%s" y="%s" width="%s" height="%s" fill="%s" stroke="white" stroke-width="1">'
                '<title>%s</title></rect>'
                % (x, y, cell_w, cell_h, fill, escape(title))
            )
            if value is not None:
                evaluated_files = int(cell.get("evaluated_files", 0) or 0)
                elements.append(
                    '<text x="%.1f" y="%.1f" font-family="Arial" font-size="11" text-anchor="middle" '
                    'dominant-baseline="middle" fill="%s">%.2f</text>'
                    % (x + cell_w / 2, y + cell_h / 2 - 5, text_color_for_value(value, vmin, vmax), value)
                )
                elements.append(
                    '<text x="%.1f" y="%.1f" font-family="Arial" font-size="9" text-anchor="middle" '
                    'dominant-baseline="middle" fill="%s">(n=%s)</text>'
                    % (
                        x + cell_w / 2,
                        y + cell_h / 2 + 8,
                        text_color_for_value(value, vmin, vmax),
                        evaluated_files,
                    )
                )

    legend_x = left
    legend_y = height - 54
    legend_w = 300
    segments = 50
    for index in range(segments):
        value = vmin + (vmax - vmin) * index / max(1, segments - 1)
        elements.append(
            '<rect x="%.1f" y="%s" width="%.1f" height="12" fill="%s"/>'
            % (
                legend_x + index * legend_w / segments,
                legend_y,
                legend_w / segments,
                color_for_value(value, vmin, vmax),
            )
        )
    elements.append(
        '<text x="%s" y="%s" font-family="Arial" font-size="11" fill="#111827">%s</text>'
        % (legend_x, legend_y - 8, escape(metric_label(metric)))
    )
    for tick in [0.0, 0.25, 0.5, 0.75, 1.0]:
        tick_x = legend_x + tick * legend_w
        elements.append(
            '<line x1="%.1f" y1="%s" x2="%.1f" y2="%s" stroke="#374151" stroke-width="1"/>'
            % (tick_x, legend_y + 12, tick_x, legend_y + 17)
        )
        elements.append(
            '<text x="%.1f" y="%s" font-family="Arial" font-size="10" text-anchor="middle" fill="#374151">%.2g</text>'
            % (tick_x, legend_y + 31, tick)
        )
    elements.append(
        '<text x="%s" y="%s" font-family="Arial" font-size="10" fill="#6b7280">cell text: metric, sample count</text>'
        % (legend_x + legend_w + 30, legend_y + 11)
    )
    if info_lines:
        info_y = legend_y + 50
        elements.append(
            '<text x="%s" y="%s" font-family="Arial" font-size="11" font-weight="700" fill="#111827">Info</text>'
            % (24, info_y)
        )
        for line_index, line in enumerate(info_lines):
            elements.append(
                '<text x="%s" y="%s" font-family="Arial" font-size="11" fill="#374151">%s</text>'
                % (62, info_y + line_index * 16, escape(line))
            )
    elements.append("</svg>")
    path.write_text("\n".join(elements) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run(args: argparse.Namespace) -> None:
    thresholds = parse_int_csv(args.input_length_thresholds)
    rows = collect_rows(args, thresholds)
    output_root = args.output_root
    input_length_rows = group_by_input_length(rows)
    input_length_rootkey_rows = group_by_input_length_rootkey(rows)
    top_level_key_rows = group_by_rootkey(rows)

    write_csv(
        output_root / "per_file_input_length_rootkey.csv",
        strip_internal_fields(rows),
        PER_FILE_FIELDS,
    )
    write_csv(
        output_root / "input_length_metrics.csv",
        input_length_rows,
        GROUP_FIELDS,
    )
    write_csv(
        output_root / "input_length_rootkey_metrics.csv",
        input_length_rootkey_rows,
        ROOTKEY_GROUP_FIELDS,
    )
    write_csv(
        output_root / "top_level_key_input_length_metrics.csv",
        top_level_key_rows,
        TOP_KEY_FIELDS,
    )
    if not args.no_heatmap:
        write_input_length_rootkey_heatmap(
            output_root / "input_length_rootkey_heatmap.svg",
            input_length_rootkey_rows,
            args.plot_metric,
            args.heatmap_min_files,
            args.heatmap_info,
        )
    write_json(
        output_root / "summary.json",
        {
            "result_root": str(args.result_root),
            "qa_root": str(args.qa_root),
            "splits": parse_csv_values(args.splits),
            "tasks": parse_csv_values(args.tasks),
            "input_length_thresholds": thresholds,
            "total_files": len(rows),
            "evaluated_files": sum(1 for row in rows if row["status"] == "ok"),
            "model_error_files": sum(1 for row in rows if row["status"] == "model_error"),
            "eval_error_files": sum(1 for row in rows if row["status"] == "eval_error"),
            "heatmap": None
            if args.no_heatmap
            else {
                "file": str(output_root / "input_length_rootkey_heatmap.svg"),
                "metric": args.plot_metric,
                "min_files": args.heatmap_min_files,
                "info": args.heatmap_info,
            },
            "grouping": (
                "input_token_group is computed from QA sample input serialized as compact JSON. "
                "Metrics are micro-aggregated inside each group by accumulating TP/pred_total/gold_total."
            ),
        },
    )
    print("[input-length-rootkey] done. output: %s" % output_root, flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze input context length × root key vs metrics.")
    parser.add_argument("--result-root", type=Path, default=DEFAULT_RESULT_ROOT)
    parser.add_argument("--qa-root", type=Path, default=DEFAULT_QA_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--splits", default=DEFAULT_SPLITS)
    parser.add_argument("--tasks", default=DEFAULT_TASKS)
    parser.add_argument("--pred-keys", default=DEFAULT_PRED_KEYS)
    parser.add_argument("--gold-key", default=DEFAULT_GOLD_KEY)
    parser.add_argument("--array-mode", choices=["wildcard", "index"], default="wildcard")
    parser.add_argument("--input-length-thresholds", default=DEFAULT_INPUT_LENGTH_THRESHOLDS)
    parser.add_argument("--plot-metric", default=DEFAULT_PLOT_METRIC, help="Metric used in heatmap color.")
    parser.add_argument("--heatmap-min-files", type=int, default=1, help="Minimum evaluated files per heatmap cell.")
    parser.add_argument("--heatmap-info", default="", help="Free-form text rendered in the heatmap bottom whitespace.")
    parser.add_argument("--no-heatmap", action="store_true", help="Disable SVG heatmap output.")
    parser.add_argument("--progress-interval", type=int, default=DEFAULT_PROGRESS_INTERVAL)
    parser.add_argument("--limit", type=int, default=0, help="Only process first N files. 0 means all.")
    return parser.parse_args()


def main() -> None:
    run(parse_args())


if __name__ == "__main__":
    main()
