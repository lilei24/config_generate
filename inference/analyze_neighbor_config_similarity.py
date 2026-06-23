#!/usr/bin/env python3
"""Analyze nearest same top-level config key distance vs generation metrics."""

from __future__ import annotations

import argparse
import csv
import json
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, DefaultDict, Dict, Iterable, List, Optional, Set, Tuple

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
DEFAULT_OUTPUT_ROOT = Path("metric-results/neighbor-config-similarity")
DEFAULT_SPLITS = "val"
DEFAULT_TASKS = "node_config_qa"
DEFAULT_PRED_KEYS = "model-output,model_output,model-ouput"
DEFAULT_GOLD_KEY = "answer"
DEFAULT_PROGRESS_INTERVAL = 500


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
    "target_node_id",
    "target_node_found",
    "target_top_level_key",
    "nearest_same_top_key_distance",
    "nearest_same_top_key_group",
    "same_top_key_node_count",
] + METRIC_FIELDS

GROUP_FIELDS = [
    "split",
    "task",
    "factor",
    "group",
    "total_files",
    "evaluated_files",
    "model_error_files",
    "eval_error_files",
    "error_rate",
] + METRIC_FIELDS


def parse_csv_values(text: str) -> List[str]:
    return [item.strip() for item in text.split(",") if item.strip()]


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


def output_top_level_keys(value: Any) -> List[str]:
    return [str(key) for key in value] if isinstance(value, dict) else []


def target_node_id(qa_sample: Dict[str, Any]) -> str:
    metadata = qa_sample.get("metadata")
    target = metadata.get("target") if isinstance(metadata, dict) else None
    node_id = target.get("node_id") if isinstance(target, dict) else None
    return str(node_id) if node_id is not None else ""


def config_items(node: Any) -> List[Any]:
    if not isinstance(node, dict):
        return []
    items = node.get("configs") if "configs" in node else node.get("config", [])
    return items if isinstance(items, list) else []


def node_has_top_key(node: Any, top_key: str) -> bool:
    return any(isinstance(item, dict) and top_key in item for item in config_items(node))


def graph_parts(input_value: Any) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Set[str]]]:
    if not isinstance(input_value, dict):
        return {}, {}
    nodes = input_value.get("nodes")
    links = input_value.get("links")
    node_list = nodes if isinstance(nodes, list) else []
    node_map = {
        str(node["id"]): node
        for node in node_list
        if isinstance(node, dict) and node.get("id") is not None
    }
    adjacency: Dict[str, Set[str]] = {node_id: set() for node_id in node_map}
    if not isinstance(links, list):
        return node_map, adjacency
    for link in links:
        if not isinstance(link, dict):
            continue
        source = link.get("source")
        target = link.get("target")
        if source is None or target is None:
            continue
        source_id = str(source)
        target_id = str(target)
        if source_id == target_id or source_id not in node_map or target_id not in node_map:
            continue
        adjacency[source_id].add(target_id)
        adjacency[target_id].add(source_id)
    return node_map, adjacency


def distances_from_target(adjacency: Dict[str, Set[str]], target_id: str) -> Dict[str, int]:
    if target_id not in adjacency:
        return {}
    distances = {target_id: 0}
    queue = deque([target_id])
    while queue:
        current = queue.popleft()
        for neighbor in adjacency[current]:
            if neighbor in distances:
                continue
            distances[neighbor] = distances[current] + 1
            queue.append(neighbor)
    return distances


def nearest_same_top_key_stats(input_value: Any, target_id: str, target_key: str) -> Dict[str, Any]:
    node_map, adjacency = graph_parts(input_value)
    target_node = node_map.get(target_id)
    distances = distances_from_target(adjacency, target_id)
    matching_distances = [
        distances[node_id]
        for node_id, node in node_map.items()
        if node_id in distances and node_has_top_key(node, target_key)
    ]
    nearest = min(matching_distances) if matching_distances else None
    if nearest is None:
        group = "inf"
        distance_value: Any = "inf"
    else:
        distance_value = nearest
        group = str(nearest) if nearest <= 3 else ">3"
    return {
        "target_node_found": bool(target_node is not None),
        "nearest_same_top_key_distance": distance_value,
        "nearest_same_top_key_group": group,
        "same_top_key_node_count": len(matching_distances),
    }


def empty_metric_values() -> Dict[str, Any]:
    return metric_row_values(None)


def collect_rows(args: argparse.Namespace) -> List[Dict[str, Any]]:
    splits = parse_csv_values(args.splits)
    tasks = parse_csv_values(args.tasks)
    pred_keys = parse_csv_values(args.pred_keys)
    files = list(iter_result_files(args.result_root, splits, tasks))
    if args.limit:
        files = files[: args.limit]

    rows: List[Dict[str, Any]] = []
    started_at = time.time()
    total = len(files)
    print("[neighbor-sim] start: %s files" % total, flush=True)

    for index, (split, task, result_path) in enumerate(files, start=1):
        qa_path = qa_path_for_result(args.result_root, args.qa_root, split, task, result_path)
        base: Dict[str, Any] = {
            "split": split,
            "task": task,
            "file": str(result_path.relative_to(args.result_root)),
            "qa_file": str(qa_path),
            "status": "eval_error",
            "error": "",
            "target_node_id": "",
            "target_node_found": False,
            "target_top_level_key": "",
            "nearest_same_top_key_distance": "",
            "nearest_same_top_key_group": "",
            "same_top_key_node_count": 0,
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
        base["target_node_id"] = target_node_id(qa_sample)

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
        target_keys = output_top_level_keys(answer)
        base["target_top_level_key"] = "|".join(target_keys) if target_keys else "<non_object_answer>"
        if len(target_keys) == 1:
            base.update(nearest_same_top_key_stats(input_value, base["target_node_id"], target_keys[0]))

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
                "[neighbor-sim] %s/%s files (%.2f%%), %.2f files/s, eta %.1fs"
                % (index, total, index / total * 100 if total else 100.0, speed, eta),
                flush=True,
            )

    return rows


def group_sort_key(group: str) -> Tuple[int, Any]:
    if group == "inf":
        return 2, group
    if group == ">3":
        return 1, 4
    try:
        return 0, int(group)
    except ValueError:
        return 3, group


def group_rows(rows: List[Dict[str, Any]], factor: str) -> List[Dict[str, Any]]:
    grouped: DefaultDict[Tuple[str, str, str], List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(row["split"], row["task"], str(row.get(factor, "")))].append(row)

    output: List[Dict[str, Any]] = []
    for (split, task, group), items in sorted(grouped.items(), key=lambda item: (item[0][0], item[0][1], group_sort_key(item[0][2]))):
        accumulator = empty_metric_accumulator()
        for item in items:
            if item["status"] == "ok":
                add_metric(accumulator, item["_metric"])
        evaluated = sum(1 for item in items if item["status"] == "ok")
        model_errors = sum(1 for item in items if item["status"] == "model_error")
        eval_errors = sum(1 for item in items if item["status"] == "eval_error")
        if evaluated:
            metric = finalize_accumulator(accumulator)
            metric_values = metric_row_values(metric)
            metric_values["top_level_exact_match"] = metric["top_level_config"]["exact_match_rate"]
        else:
            metric_values = empty_metric_values()
        output.append(
            {
                "split": split,
                "task": task,
                "factor": factor,
                "group": group,
                "total_files": len(items),
                "evaluated_files": evaluated,
                "model_error_files": model_errors,
                "eval_error_files": eval_errors,
                "error_rate": (model_errors + eval_errors) / len(items) if items else 0.0,
                **metric_values,
            }
        )
    return output


def strip_internal_fields(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [{key: value for key, value in row.items() if not key.startswith("_")} for row in rows]


def write_csv(path: Path, rows: List[Dict[str, Any]], fieldnames: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> None:
    rows = collect_rows(args)
    output_root = args.output_root
    group_values = group_rows(rows, "nearest_same_top_key_group")
    write_csv(output_root / "per_file_neighbor_config_similarity.csv", strip_internal_fields(rows), PER_FILE_FIELDS)
    write_csv(output_root / "nearest_same_top_key_distance_metrics.csv", group_values, GROUP_FIELDS)
    write_json(
        output_root / "summary.json",
        {
            "result_root": str(args.result_root),
            "qa_root": str(args.qa_root),
            "splits": parse_csv_values(args.splits),
            "tasks": parse_csv_values(args.tasks),
            "total_files": len(rows),
            "evaluated_files": sum(1 for row in rows if row["status"] == "ok"),
            "model_error_files": sum(1 for row in rows if row["status"] == "model_error"),
            "eval_error_files": sum(1 for row in rows if row["status"] == "eval_error"),
            "distance_groups": ["0", "1", "2", "3", ">3", "inf"],
        },
    )
    print("[neighbor-sim] done. output: %s" % output_root, flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze nearest same top-level config key distance vs metrics.")
    parser.add_argument("--result-root", type=Path, default=DEFAULT_RESULT_ROOT)
    parser.add_argument("--qa-root", type=Path, default=DEFAULT_QA_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--splits", default=DEFAULT_SPLITS)
    parser.add_argument("--tasks", default=DEFAULT_TASKS)
    parser.add_argument("--pred-keys", default=DEFAULT_PRED_KEYS)
    parser.add_argument("--gold-key", default=DEFAULT_GOLD_KEY)
    parser.add_argument("--array-mode", choices=["wildcard", "index"], default="wildcard")
    parser.add_argument("--progress-interval", type=int, default=DEFAULT_PROGRESS_INTERVAL)
    parser.add_argument("--limit", type=int, default=0, help="Only process first N files. 0 means all.")
    return parser.parse_args()


def main() -> None:
    run(parse_args())


if __name__ == "__main__":
    main()
