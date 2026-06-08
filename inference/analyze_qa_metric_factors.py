#!/usr/bin/env python3
"""Analyze relationships between QA context factors and generation metrics."""

from __future__ import annotations

import argparse
import csv
import json
import math
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, DefaultDict, Dict, Iterable, List, Optional, Sequence, Tuple
from xml.sax.saxutils import escape

from batch_evaluate_qa import (
    add_metric,
    empty_metric_accumulator,
    evaluate_one_record,
    finalize_accumulator,
    metric_row_values,
    read_json,
)


DEFAULT_RESULT_ROOT = Path("inference-results")
DEFAULT_QA_ROOT = Path("520QA")
DEFAULT_OUTPUT_ROOT = Path("metric-results/qa-factor-analysis")
DEFAULT_SPLITS = "train"
DEFAULT_TASKS = "node_config_qa"
DEFAULT_PRED_KEYS = "model-ouput,model-output,model_output"
DEFAULT_GOLD_KEY = "answer"
DEFAULT_PROGRESS_INTERVAL = 500
DEFAULT_PATH_OCCURRENCE_BINS = "0,1,2,5,10,20,50,100,200,500,1000"
DEFAULT_NODE_COUNT_BINS = "0,1,2,5,10,20,50,100,200,500,1000"
DEFAULT_TOP_KEY_COUNT_BINS = "0,1,2,5,10,20,50,100,200,500,1000,2000"


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


SAMPLE_FIELDS = [
    "split",
    "task",
    "file",
    "qa_file",
    "status",
    "error",
    "target_top_level_key",
    "answer_field_path_count",
    "answer_paths_found_in_input",
    "answer_path_occurrence_total",
    "answer_path_occurrence_mean",
    "input_node_count",
    "target_node_id",
    "target_node_found",
    "target_node_visible_top_key_count",
    "all_nodes_visible_top_key_count",
] + METRIC_FIELDS


GROUP_FIELDS = [
    "split",
    "task",
    "factor",
    "group",
    "range_min_exclusive",
    "range_max_inclusive",
    "total_files",
    "evaluated_files",
    "model_error_files",
    "eval_error_files",
    "error_rate",
] + METRIC_FIELDS


TOP_KEY_GROUP_FIELDS = [
    "split",
    "task",
    "target_top_level_key",
    "factor",
    "group",
    "range_min_exclusive",
    "range_max_inclusive",
    "total_files",
    "evaluated_files",
    "model_error_files",
    "eval_error_files",
    "error_rate",
] + METRIC_FIELDS


PATH_DETAIL_FIELDS = [
    "split",
    "task",
    "file",
    "status",
    "error",
    "target_top_level_key",
    "answer_path",
    "input_occurrence_count",
] + METRIC_FIELDS


def parse_csv_values(text: str) -> List[str]:
    return [item.strip() for item in text.split(",") if item.strip()]


def parse_int_csv(text: str) -> List[int]:
    values: List[int] = []
    for item in parse_csv_values(text):
        value = int(item)
        if value >= 0:
            values.append(value)
    return sorted(set(values))


def iter_result_files(
    result_root: Path,
    splits: Iterable[str],
    tasks: Iterable[str],
) -> Iterable[Tuple[str, str, Path]]:
    for split in splits:
        for task in tasks:
            task_root = result_root / split / task
            if not task_root.exists():
                continue
            for path in sorted(task_root.rglob("*.json")):
                if path.is_file():
                    yield split, task, path


def qa_path_for_result(
    result_root: Path,
    qa_root: Path,
    split: str,
    task: str,
    result_path: Path,
) -> Path:
    relative_path = result_path.relative_to(result_root / split / task)
    return qa_root / split / task / relative_path


def normalize_json_value(value: Any) -> Tuple[Optional[Any], str]:
    if not isinstance(value, str):
        return value, ""
    try:
        return json.loads(value), ""
    except json.JSONDecodeError as exc:
        return None, "invalid_json_string: %s" % exc


def answer_value(record: Dict[str, Any], qa_sample: Dict[str, Any], gold_key: str) -> Tuple[Optional[Any], str]:
    if gold_key in record:
        return normalize_json_value(record[gold_key])
    if "output" in qa_sample:
        return qa_sample["output"], ""
    return None, "missing_answer"


PathParts = Tuple[str, ...]


def collect_field_paths(value: Any) -> Counter:
    """Collect field paths as key tuples; array positions use the [] marker."""

    paths: Counter = Counter()

    def walk(current: Any, parts: PathParts) -> None:
        if isinstance(current, dict):
            for key, child in current.items():
                child_parts = parts + (str(key),)
                paths[child_parts] += 1
                walk(child, child_parts)
        elif isinstance(current, list):
            for item in current:
                walk(item, parts + ("[]",))

    walk(value, ())
    return paths


def path_text(parts: PathParts) -> str:
    text = ""
    for part in parts:
        if part == "[]":
            text += "[]"
        else:
            text += "/" + part.replace("~", "~0").replace("/", "~1")
    return text or "/"


def path_endswith(full_path: PathParts, suffix: PathParts) -> bool:
    return len(full_path) >= len(suffix) and full_path[-len(suffix) :] == suffix


def answer_path_occurrences(answer: Any, input_value: Any) -> Tuple[Dict[str, Any], List[Tuple[str, int]]]:
    answer_paths = collect_field_paths(answer)
    input_paths = collect_field_paths(input_value)
    detail: List[Tuple[str, int]] = []
    found_count = 0
    occurrence_total = 0

    for answer_path, answer_multiplicity in sorted(answer_paths.items(), key=lambda item: path_text(item[0])):
        matching_count = sum(
            input_multiplicity
            for input_path, input_multiplicity in input_paths.items()
            if path_endswith(input_path, answer_path)
        )
        for _ in range(answer_multiplicity):
            detail.append((path_text(answer_path), matching_count))
            if matching_count > 0:
                found_count += 1
            occurrence_total += matching_count

    answer_path_count = sum(answer_paths.values())
    return {
        "answer_field_path_count": answer_path_count,
        "answer_paths_found_in_input": found_count,
        "answer_path_occurrence_total": occurrence_total,
        "answer_path_occurrence_mean": occurrence_total / answer_path_count if answer_path_count else 0.0,
    }, detail


def top_level_keys(value: Any) -> List[str]:
    return [str(key) for key in value] if isinstance(value, dict) else []


def config_items(node: Any) -> Any:
    if not isinstance(node, dict):
        return []
    if "configs" in node:
        return node.get("configs")
    return node.get("config", [])


def visible_top_key_count(node: Any) -> int:
    items = config_items(node)
    if not isinstance(items, list):
        return 0
    return sum(len(item) for item in items if isinstance(item, dict))


def node_factor_values(qa_sample: Dict[str, Any]) -> Dict[str, Any]:
    input_value = qa_sample.get("input")
    nodes = input_value.get("nodes") if isinstance(input_value, dict) else None
    node_list = nodes if isinstance(nodes, list) else []
    metadata = qa_sample.get("metadata")
    target = metadata.get("target") if isinstance(metadata, dict) else None
    target_node_id = target.get("node_id") if isinstance(target, dict) else None
    target_node_id_text = str(target_node_id) if target_node_id is not None else ""

    target_node = None
    for node in node_list:
        if not isinstance(node, dict) or node.get("id") is None:
            continue
        if str(node["id"]) == target_node_id_text:
            target_node = node
            break

    return {
        "input_node_count": len(node_list),
        "target_node_id": target_node_id_text,
        "target_node_found": bool(target_node is not None),
        "target_node_visible_top_key_count": visible_top_key_count(target_node),
        "all_nodes_visible_top_key_count": sum(visible_top_key_count(node) for node in node_list),
    }


def empty_metric_values() -> Dict[str, Any]:
    return metric_row_values(None)


def bin_label(value: int, thresholds: Sequence[int]) -> Tuple[str, int, int]:
    lower = -1
    for threshold in thresholds:
        if value <= threshold:
            if lower < 0:
                return "0-%s" % threshold, -1, threshold
            return "%s-%s" % (lower + 1, threshold), lower, threshold
        lower = threshold
    if thresholds:
        return ">%s" % thresholds[-1], thresholds[-1], -1
    return "all", -1, -1


def collect_rows(args: argparse.Namespace) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    splits = parse_csv_values(args.splits)
    tasks = parse_csv_values(args.tasks)
    pred_keys = parse_csv_values(args.pred_keys)
    files = list(iter_result_files(args.result_root, splits, tasks))
    if args.limit:
        files = files[: args.limit]

    rows: List[Dict[str, Any]] = []
    path_detail_rows: List[Dict[str, Any]] = []
    started_at = time.time()
    total = len(files)
    print("[qa-factor] start: %s files" % total, flush=True)

    for index, (split, task, result_path) in enumerate(files, start=1):
        qa_path = qa_path_for_result(args.result_root, args.qa_root, split, task, result_path)
        base: Dict[str, Any] = {
            "split": split,
            "task": task,
            "file": str(result_path.relative_to(args.result_root)),
            "qa_file": str(qa_path),
            "status": "eval_error",
            "error": "",
            "target_top_level_key": "",
            "answer_field_path_count": 0,
            "answer_paths_found_in_input": 0,
            "answer_path_occurrence_total": 0,
            "answer_path_occurrence_mean": 0.0,
            "input_node_count": 0,
            "target_node_id": "",
            "target_node_found": False,
            "target_node_visible_top_key_count": 0,
            "all_nodes_visible_top_key_count": 0,
            **empty_metric_values(),
        }

        qa_sample, qa_error = read_json(qa_path)
        if qa_error or qa_sample is None:
            base["error"] = "qa_%s" % qa_error
            rows.append(base)
            continue

        input_value = qa_sample.get("input")
        if not isinstance(input_value, dict):
            base["error"] = "qa_missing_or_invalid_input"
            rows.append(base)
            continue

        base.update(node_factor_values(qa_sample))
        record, result_error = read_json(result_path)
        if result_error or record is None:
            base["error"] = result_error
            rows.append(base)
            continue

        answer, answer_error = answer_value(record, qa_sample, args.gold_key)
        if answer_error:
            base["error"] = answer_error
            rows.append(base)
            continue

        answer_keys = top_level_keys(answer)
        base["target_top_level_key"] = "|".join(answer_keys) if answer_keys else "<non_object_answer>"
        path_stats, path_details = answer_path_occurrences(answer, input_value)
        base.update(path_stats)
        for answer_path, occurrence_count in path_details:
            path_detail_rows.append(
                {
                    "split": split,
                    "task": task,
                    "file": base["file"],
                    "target_top_level_key": base["target_top_level_key"],
                    "answer_path": answer_path,
                    "input_occurrence_count": occurrence_count,
                }
            )

        if record.get("error"):
            base["status"] = "model_error"
            base["error"] = str(record["error"])
            rows.append(base)
            continue

        metric, metric_error = evaluate_one_record(record, pred_keys, args.gold_key, args.array_mode)
        if metric_error:
            base["error"] = metric_error
            rows.append(base)
            continue

        base["status"] = "ok"
        base.update(metric_row_values(metric))
        base["_metric"] = metric
        rows.append(base)

        if args.progress_interval > 0 and (index % args.progress_interval == 0 or index == total):
            elapsed = max(0.001, time.time() - started_at)
            speed = index / elapsed
            eta = (total - index) / speed if speed > 0 else 0.0
            print(
                "[qa-factor] %s/%s files (%.2f%%), %.2f files/s, eta %.1fs"
                % (index, total, index / total * 100 if total else 100.0, speed, eta),
                flush=True,
            )

    return rows, path_detail_rows


def group_rows(
    rows: List[Dict[str, Any]],
    factor: str,
    grouper: Any,
) -> List[Dict[str, Any]]:
    grouped: DefaultDict[Tuple[str, str, str, int, int], List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        group_name, lower, upper = grouper(row)
        grouped[(row["split"], row["task"], str(group_name), lower, upper)].append(row)

    output: List[Dict[str, Any]] = []
    def group_sort_key(
        item: Tuple[Tuple[str, str, str, int, int], List[Dict[str, Any]]],
    ) -> Tuple[Any, ...]:
        split, task, group_name, lower, upper = item[0]
        # 数值分桶按下界从小到大排列；精确字符串分组的上下界都是 -1，
        # 因此继续按名称排序。最后一个 ``>最大阈值`` 桶的 lower 最大，
        # 会自然排在所有有限区间之后。
        if lower == -1 and upper == -1:
            return split, task, 0, group_name
        return split, task, 1, lower, upper, group_name

    for (split, task, group_name, lower, upper), group_items in sorted(
        grouped.items(),
        key=group_sort_key,
    ):
        accumulator = empty_metric_accumulator()
        for item in group_items:
            if item["status"] == "ok":
                add_metric(accumulator, item["_metric"])
        evaluated = sum(1 for item in group_items if item["status"] == "ok")
        model_errors = sum(1 for item in group_items if item["status"] == "model_error")
        eval_errors = sum(1 for item in group_items if item["status"] == "eval_error")
        if evaluated:
            aggregate_metric = finalize_accumulator(accumulator)
            metric_values = metric_row_values(aggregate_metric)
            metric_values["top_level_exact_match"] = aggregate_metric["top_level_config"]["exact_match_rate"]
        else:
            metric_values = empty_metric_values()
        output.append(
            {
                "split": split,
                "task": task,
                "factor": factor,
                "group": group_name,
                "range_min_exclusive": lower,
                "range_max_inclusive": upper,
                "total_files": len(group_items),
                "evaluated_files": evaluated,
                "model_error_files": model_errors,
                "eval_error_files": eval_errors,
                "error_rate": (model_errors + eval_errors) / len(group_items) if group_items else 0.0,
                **metric_values,
            }
        )
    return output


def group_rows_by_top_level_key(
    rows: List[Dict[str, Any]],
    factor: str,
    grouper: Any,
) -> List[Dict[str, Any]]:
    grouped: DefaultDict[Tuple[str, str, str, str, int, int], List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        group_name, lower, upper = grouper(row)
        top_key = str(row.get("target_top_level_key", ""))
        grouped[(row["split"], row["task"], top_key, str(group_name), lower, upper)].append(row)

    def group_sort_key(
        item: Tuple[Tuple[str, str, str, str, int, int], List[Dict[str, Any]]],
    ) -> Tuple[Any, ...]:
        split, task, top_key, group_name, lower, upper = item[0]
        if lower == -1 and upper == -1:
            return split, task, top_key, 0, group_name
        return split, task, top_key, 1, lower, upper, group_name

    output: List[Dict[str, Any]] = []
    for (split, task, top_key, group_name, lower, upper), group_items in sorted(
        grouped.items(),
        key=group_sort_key,
    ):
        accumulator = empty_metric_accumulator()
        for item in group_items:
            if item["status"] == "ok":
                add_metric(accumulator, item["_metric"])
        evaluated = sum(1 for item in group_items if item["status"] == "ok")
        model_errors = sum(1 for item in group_items if item["status"] == "model_error")
        eval_errors = sum(1 for item in group_items if item["status"] == "eval_error")
        if evaluated:
            aggregate_metric = finalize_accumulator(accumulator)
            metric_values = metric_row_values(aggregate_metric)
            metric_values["top_level_exact_match"] = aggregate_metric["top_level_config"]["exact_match_rate"]
        else:
            metric_values = empty_metric_values()
        output.append(
            {
                "split": split,
                "task": task,
                "target_top_level_key": top_key,
                "factor": factor,
                "group": group_name,
                "range_min_exclusive": lower,
                "range_max_inclusive": upper,
                "total_files": len(group_items),
                "evaluated_files": evaluated,
                "model_error_files": model_errors,
                "eval_error_files": eval_errors,
                "error_rate": (model_errors + eval_errors) / len(group_items) if group_items else 0.0,
                **metric_values,
            }
        )
    return output


def exact_grouper(field: str) -> Any:
    return lambda row: (row.get(field, ""), -1, -1)


def numeric_bin_grouper(field: str, thresholds: Sequence[int]) -> Any:
    return lambda row: bin_label(int(row.get(field, 0)), thresholds)


def write_csv(path: Path, rows: List[Dict[str, Any]], fieldnames: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_metric_svg(path: Path, title: str, rows: List[Dict[str, Any]], max_groups: int = 80) -> None:
    plot_rows = [row for row in rows if row["evaluated_files"] > 0][:max_groups]
    if not plot_rows:
        return

    width = max(960, 90 * len(plot_rows))
    height = 520
    left = 70
    right = 30
    top = 45
    bottom = 150
    plot_width = width - left - right
    plot_height = height - top - bottom
    step = plot_width / max(1, len(plot_rows))
    metrics = [
        ("field_path_f1", "#2563eb"),
        ("leaf_triple_f1", "#16a34a"),
        ("value_accuracy", "#dc2626"),
    ]

    def y(value: float) -> float:
        return top + (1.0 - max(0.0, min(1.0, value))) * plot_height

    elements = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="%s" height="%s" viewBox="0 0 %s %s">' % (width, height, width, height),
        '<rect width="100%" height="100%" fill="white"/>',
        '<text x="%s" y="25" font-size="18" font-family="Arial" fill="#111827">%s</text>' % (left, escape(title)),
    ]
    for tick in range(6):
        value = tick / 5
        tick_y = y(value)
        elements.append('<line x1="%s" y1="%s" x2="%s" y2="%s" stroke="#e5e7eb"/>' % (left, tick_y, left + plot_width, tick_y))
        elements.append('<text x="%s" y="%s" font-size="11" text-anchor="end" font-family="Arial">%.1f</text>' % (left - 8, tick_y + 4, value))

    for metric_name, color in metrics:
        points: List[Tuple[float, float, Dict[str, Any]]] = []
        for index, row in enumerate(plot_rows):
            value = row.get(metric_name, "")
            if value == "":
                continue
            x_pos = left + (index + 0.5) * step
            points.append((x_pos, y(float(value)), row))
        if len(points) > 1:
            elements.append(
                '<polyline fill="none" stroke="%s" stroke-width="2" points="%s"/>'
                % (color, " ".join("%.2f,%.2f" % (x_pos, y_pos) for x_pos, y_pos, _ in points))
            )
        for x_pos, y_pos, row in points:
            tooltip = "%s=%s group=%s files=%s" % (
                metric_name,
                row[metric_name],
                row["group"],
                row["evaluated_files"],
            )
            elements.append(
                '<circle cx="%.2f" cy="%.2f" r="4" fill="%s"><title>%s</title></circle>'
                % (x_pos, y_pos, color, escape(tooltip))
            )

    for index, row in enumerate(plot_rows):
        x_pos = left + (index + 0.5) * step
        label_y = top + plot_height + 18
        elements.append(
            '<text x="%.2f" y="%s" font-size="10" text-anchor="end" transform="rotate(-50 %.2f %s)" font-family="Arial">%s</text>'
            % (x_pos, label_y, x_pos, label_y, escape(str(row["group"])))
        )

    for index, (metric_name, color) in enumerate(metrics):
        legend_x = left + plot_width - 190
        legend_y = top + 15 + index * 21
        elements.append('<rect x="%s" y="%s" width="11" height="11" fill="%s"/>' % (legend_x, legend_y - 9, color))
        elements.append('<text x="%s" y="%s" font-size="12" font-family="Arial">%s</text>' % (legend_x + 17, legend_y, metric_name))
    elements.append("</svg>")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(elements) + "\n", encoding="utf-8")


def strip_internal_fields(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [{key: value for key, value in row.items() if not key.startswith("_")} for row in rows]


def remove_deprecated_outputs(output_root: Path) -> None:
    deprecated_names = [
        "answer_path_key_metrics.csv",
        "answer_path_key_metrics.svg",
        "answer_path_single_occurrence_metrics.csv",
        "answer_path_single_occurrence_metrics.svg",
        "target_node_visible_top_key_count_metrics.csv",
        "target_node_visible_top_key_count_metrics.svg",
        "all_nodes_visible_top_key_count_metrics.csv",
        "all_nodes_visible_top_key_count_metrics.svg",
    ]
    for name in deprecated_names:
        path = output_root / name
        if path.exists() and path.is_file():
            path.unlink()


def run(args: argparse.Namespace) -> None:
    rows, path_detail_rows = collect_rows(args)
    path_bins = parse_int_csv(args.path_occurrence_bins)
    node_bins = parse_int_csv(args.node_count_bins)
    key_bins = parse_int_csv(args.top_key_count_bins)

    top_key_rows = group_rows(rows, "target_top_level_key", exact_grouper("target_top_level_key"))
    path_occurrence_rows = group_rows(
        rows,
        "answer_path_occurrence_total",
        numeric_bin_grouper("answer_path_occurrence_total", path_bins),
    )
    top_key_path_occurrence_rows = group_rows_by_top_level_key(
        rows,
        "answer_path_occurrence_total",
        numeric_bin_grouper("answer_path_occurrence_total", path_bins),
    )
    node_count_rows = group_rows(rows, "input_node_count", numeric_bin_grouper("input_node_count", node_bins))
    node_task_rows = [row for row in rows if row["task"] == "node_config_qa"]
    target_key_count_rows = group_rows_by_top_level_key(
        node_task_rows,
        "target_node_visible_top_key_count",
        numeric_bin_grouper("target_node_visible_top_key_count", key_bins),
    )
    all_key_count_rows = group_rows_by_top_level_key(
        node_task_rows,
        "all_nodes_visible_top_key_count",
        numeric_bin_grouper("all_nodes_visible_top_key_count", key_bins),
    )
    sample_by_file = {(row["split"], row["task"], row["file"]): row for row in rows}
    enriched_path_detail_rows: List[Dict[str, Any]] = []
    for detail in path_detail_rows:
        sample = sample_by_file[(detail["split"], detail["task"], detail["file"])]
        enriched_path_detail_rows.append(
            {
                **detail,
                "status": sample["status"],
                "error": sample["error"],
                **{field: sample[field] for field in METRIC_FIELDS},
                "_metric": sample.get("_metric"),
            }
        )

    output_root = args.output_root
    remove_deprecated_outputs(output_root)
    write_csv(output_root / "per_file_factor_metrics.csv", strip_internal_fields(rows), SAMPLE_FIELDS)
    write_csv(
        output_root / "answer_path_input_occurrences.csv",
        strip_internal_fields(enriched_path_detail_rows),
        PATH_DETAIL_FIELDS,
    )
    write_csv(output_root / "top_level_key_metrics.csv", top_key_rows, GROUP_FIELDS)
    write_csv(output_root / "answer_path_occurrence_metrics.csv", path_occurrence_rows, GROUP_FIELDS)
    write_csv(
        output_root / "top_level_key_answer_path_occurrence_metrics.csv",
        top_key_path_occurrence_rows,
        TOP_KEY_GROUP_FIELDS,
    )
    write_csv(output_root / "node_count_metrics.csv", node_count_rows, GROUP_FIELDS)
    write_csv(
        output_root / "top_level_key_target_node_visible_top_key_count_metrics.csv",
        target_key_count_rows,
        TOP_KEY_GROUP_FIELDS,
    )
    write_csv(
        output_root / "top_level_key_all_nodes_visible_top_key_count_metrics.csv",
        all_key_count_rows,
        TOP_KEY_GROUP_FIELDS,
    )

    write_metric_svg(output_root / "top_level_key_metrics.svg", "Top-level key vs metrics", top_key_rows)
    write_metric_svg(
        output_root / "answer_path_occurrence_metrics.svg",
        "Answer path occurrences in input vs metrics",
        path_occurrence_rows,
    )
    write_metric_svg(
        output_root / "top_level_key_answer_path_occurrence_metrics.svg",
        "Top-level key: answer path occurrences in input vs metrics",
        top_key_path_occurrence_rows,
    )
    write_metric_svg(output_root / "node_count_metrics.svg", "Input node count vs metrics", node_count_rows)
    write_metric_svg(
        output_root / "top_level_key_target_node_visible_top_key_count_metrics.svg",
        "Top-level key: target node visible top-level key count vs metrics",
        target_key_count_rows,
    )
    write_metric_svg(
        output_root / "top_level_key_all_nodes_visible_top_key_count_metrics.svg",
        "Top-level key: all nodes visible top-level key count vs metrics",
        all_key_count_rows,
    )

    errors = Counter((row["split"], row["task"], row["status"], row["error"]) for row in rows if row["status"] != "ok")
    write_json(
        output_root / "summary.json",
        {
            "result_root": str(args.result_root),
            "qa_root": str(args.qa_root),
            "splits": parse_csv_values(args.splits),
            "tasks": parse_csv_values(args.tasks),
            "array_mode": args.array_mode,
            "path_occurrence_definition": (
                "For each sample, collect answer field paths and input field paths. "
                "For every answer field path in that sample, count input field paths in the same sample whose key "
                "sequence ends with that answer path. Array positions use []. "
                "answer_path_occurrence_total is the sum of those per-answer-path counts inside one sample."
            ),
            "top_key_count_definition": (
                "For node_config_qa only, locate the target node by metadata.target.node_id inside that sample's "
                "input.nodes. Count visible top-level config keys in that target node and in all input nodes. "
                "Grouping is then performed within each target_top_level_key."
            ),
            "total_files": len(rows),
            "evaluated_files": sum(1 for row in rows if row["status"] == "ok"),
            "model_error_files": sum(1 for row in rows if row["status"] == "model_error"),
            "eval_error_files": sum(1 for row in rows if row["status"] == "eval_error"),
            "errors": [
                {"split": split, "task": task, "status": status, "error": error, "count": count}
                for (split, task, status, error), count in errors.most_common()
            ],
            "outputs": {
                "top_level_key_groups": len(top_key_rows),
                "answer_path_occurrence_groups": len(path_occurrence_rows),
                "top_level_key_answer_path_occurrence_groups": len(top_key_path_occurrence_rows),
                "node_count_groups": len(node_count_rows),
                "top_level_key_target_node_visible_top_key_count_groups": len(target_key_count_rows),
                "top_level_key_all_nodes_visible_top_key_count_groups": len(all_key_count_rows),
            },
        },
    )
    print("[qa-factor] done. output: %s" % output_root, flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze QA factors and generation metrics.")
    parser.add_argument("--result-root", type=Path, default=DEFAULT_RESULT_ROOT)
    parser.add_argument("--qa-root", type=Path, default=DEFAULT_QA_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--splits", default=DEFAULT_SPLITS, help="Comma-separated splits, e.g. train,val.")
    parser.add_argument(
        "--tasks",
        default=DEFAULT_TASKS,
        help="Comma-separated tasks, e.g. node_config_qa,device_config_qa.",
    )
    parser.add_argument("--pred-keys", default=DEFAULT_PRED_KEYS)
    parser.add_argument("--gold-key", default=DEFAULT_GOLD_KEY)
    parser.add_argument("--array-mode", choices=["wildcard", "index"], default="wildcard")
    parser.add_argument("--path-occurrence-bins", default=DEFAULT_PATH_OCCURRENCE_BINS)
    parser.add_argument("--node-count-bins", default=DEFAULT_NODE_COUNT_BINS)
    parser.add_argument("--top-key-count-bins", default=DEFAULT_TOP_KEY_COUNT_BINS)
    parser.add_argument("--progress-interval", type=int, default=DEFAULT_PROGRESS_INTERVAL)
    parser.add_argument("--limit", type=int, default=0)
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
