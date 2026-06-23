#!/usr/bin/env python3
"""Analyze target node topology position vs generation metrics."""

from __future__ import annotations

import argparse
import csv
import json
import math
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
DEFAULT_OUTPUT_ROOT = Path("metric-results/topology-position")
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
    "hop1_neighbor_count",
    "hop2_neighbor_count",
    "hop3_neighbor_count",
    "connected_component_size",
    "is_isolated",
    "betweenness_centrality",
    "betweenness_centrality_group",
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


def target_node_id(qa_sample: Dict[str, Any]) -> str:
    metadata = qa_sample.get("metadata")
    target = metadata.get("target") if isinstance(metadata, dict) else None
    node_id = target.get("node_id") if isinstance(target, dict) else None
    return str(node_id) if node_id is not None else ""


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


def shortest_distances(adjacency: Dict[str, Set[str]], source: str) -> Dict[str, int]:
    if source not in adjacency:
        return {}
    distances = {source: 0}
    queue = deque([source])
    while queue:
        current = queue.popleft()
        for neighbor in adjacency[current]:
            if neighbor in distances:
                continue
            distances[neighbor] = distances[current] + 1
            queue.append(neighbor)
    return distances


def component_nodes(adjacency: Dict[str, Set[str]], source: str) -> Set[str]:
    return set(shortest_distances(adjacency, source))


def betweenness_centrality(adjacency: Dict[str, Set[str]]) -> Dict[str, float]:
    nodes = list(adjacency)
    centrality = {node: 0.0 for node in nodes}
    for source in nodes:
        stack: List[str] = []
        predecessors: Dict[str, List[str]] = {node: [] for node in nodes}
        sigma = dict.fromkeys(nodes, 0.0)
        sigma[source] = 1.0
        distance = dict.fromkeys(nodes, -1)
        distance[source] = 0
        queue = deque([source])
        while queue:
            current = queue.popleft()
            stack.append(current)
            for neighbor in adjacency[current]:
                if distance[neighbor] < 0:
                    queue.append(neighbor)
                    distance[neighbor] = distance[current] + 1
                if distance[neighbor] == distance[current] + 1:
                    sigma[neighbor] += sigma[current]
                    predecessors[neighbor].append(current)

        delta = dict.fromkeys(nodes, 0.0)
        while stack:
            node = stack.pop()
            for predecessor in predecessors[node]:
                if sigma[node]:
                    delta[predecessor] += (sigma[predecessor] / sigma[node]) * (1.0 + delta[node])
            if node != source:
                centrality[node] += delta[node]

    node_count = len(nodes)
    if node_count <= 2:
        return centrality
    scale = 1.0 / ((node_count - 1) * (node_count - 2))
    return {node: value * scale for node, value in centrality.items()}


def betweenness_group(value: float) -> str:
    clipped = max(0.0, min(1.0, value))
    if math.isclose(clipped, 1.0):
        return "0.9-1.0"
    lower_index = int(clipped / 0.1)
    lower = lower_index / 10
    upper = (lower_index + 1) / 10
    return "%.1f-%.1f" % (lower, upper)


def topology_values(input_value: Any, target_id: str) -> Dict[str, Any]:
    node_map, adjacency = graph_parts(input_value)
    distances = shortest_distances(adjacency, target_id)
    component = component_nodes(adjacency, target_id)
    centrality = betweenness_centrality(adjacency)
    betweenness = centrality.get(target_id, 0.0)
    return {
        "target_node_found": target_id in node_map,
        "hop1_neighbor_count": sum(1 for value in distances.values() if 0 < value <= 1),
        "hop2_neighbor_count": sum(1 for value in distances.values() if 0 < value <= 2),
        "hop3_neighbor_count": sum(1 for value in distances.values() if 0 < value <= 3),
        "connected_component_size": len(component),
        "is_isolated": int(target_id in adjacency and len(adjacency[target_id]) == 0),
        "betweenness_centrality": betweenness,
        "betweenness_centrality_group": betweenness_group(betweenness),
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
    print("[topology-position] start: %s files" % total, flush=True)

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
            "hop1_neighbor_count": 0,
            "hop2_neighbor_count": 0,
            "hop3_neighbor_count": 0,
            "connected_component_size": 0,
            "is_isolated": 0,
            "betweenness_centrality": 0.0,
            "betweenness_centrality_group": "0.0-0.1",
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
        base.update(topology_values(input_value, base["target_node_id"]))

        record, result_error = read_json(result_path)
        if result_error or record is None:
            base["error"] = result_error
            rows.append(base)
            continue
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
                "[topology-position] %s/%s files (%.2f%%), %.2f files/s, eta %.1fs"
                % (index, total, index / total * 100 if total else 100.0, speed, eta),
                flush=True,
            )
    return rows


def numeric_group_sort_key(value: str) -> Tuple[int, Any]:
    try:
        return 0, int(value)
    except ValueError:
        pass
    if "-" in value:
        try:
            return 1, float(value.split("-", 1)[0])
        except ValueError:
            pass
    return 2, value


def group_rows(rows: List[Dict[str, Any]], factor: str) -> List[Dict[str, Any]]:
    grouped: DefaultDict[Tuple[str, str, str], List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(row["split"], row["task"], str(row.get(factor, "")))].append(row)

    output: List[Dict[str, Any]] = []
    for (split, task, group), items in sorted(grouped.items(), key=lambda item: (item[0][0], item[0][1], numeric_group_sort_key(item[0][2]))):
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
    write_csv(output_root / "per_file_topology_position.csv", strip_internal_fields(rows), PER_FILE_FIELDS)
    for factor in (
        "hop1_neighbor_count",
        "hop2_neighbor_count",
        "hop3_neighbor_count",
        "connected_component_size",
        "is_isolated",
        "betweenness_centrality_group",
    ):
        write_csv(output_root / ("%s_metrics.csv" % factor), group_rows(rows, factor), GROUP_FIELDS)
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
            "neighbor_count_rule": "hop2 includes hop1; hop3 includes hop1 and hop2; target node itself is excluded.",
            "betweenness_rule": "undirected normalized betweenness centrality grouped by 0.1 buckets.",
        },
    )
    print("[topology-position] done. output: %s" % output_root, flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze target node topology position vs metrics.")
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
