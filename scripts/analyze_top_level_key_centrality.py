#!/usr/bin/env python3
"""Analyze top-level key distributions over node centrality.

For each graph JSON under the dataset root, the script:
- reads `nodes` and `links`
- treats links as an undirected graph
- computes degree centrality and betweenness centrality for every node
- maps each top-level key found in node `config`/`configs` to the nodes that expose it
- aggregates centrality statistics per top-level key

The script intentionally keeps its defaults local and uses only the standard library.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean, median
from typing import Any, DefaultDict, Dict, Iterable, Iterator, List, Optional, Sequence, Set, Tuple


DEFAULT_DATASET_ROOT = Path("/data/my_dataset")
DEFAULT_OUTPUT_DIR = Path("/tmp/top_level_key_centrality")
DEFAULT_SPLITS = "train,val"
DEFAULT_PROGRESS_INTERVAL = 500


PER_NODE_FIELDS = [
    "split",
    "file",
    "node_id",
    "top_level_key",
    "degree_centrality",
    "betweenness_centrality",
]

SUMMARY_FIELDS = [
    "split",
    "top_level_key",
    "node_occurrences",
    "file_count",
    "degree_mean",
    "degree_median",
    "degree_min",
    "degree_max",
    "betweenness_mean",
    "betweenness_median",
    "betweenness_min",
    "betweenness_max",
]


@dataclass
class KeyCentralityStats:
    degree_values: list[float] = field(default_factory=list)
    betweenness_values: list[float] = field(default_factory=list)
    files: set[str] = field(default_factory=set)
    node_occurrences: int = 0


def parse_csv_values(text: str) -> List[str]:
    return [item.strip() for item in text.split(",") if item.strip()]


def iter_json_files(dataset_root: Path, splits: Iterable[str]) -> Iterator[Tuple[str, Path]]:
    for split in splits:
        split_dir = dataset_root / split
        if not split_dir.exists():
            continue
        for path in sorted(split_dir.rglob("*.json")):
            if path.is_file():
                yield split, path


def load_json(path: Path) -> Tuple[Optional[Dict[str, Any]], str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return None, "bad_json: %s" % exc
    if not isinstance(data, dict):
        return None, "json_not_object"
    return data, ""


def node_config_items(node: Any) -> List[Any]:
    if not isinstance(node, dict):
        return []
    items = node.get("configs") if "configs" in node else node.get("config", [])
    return items if isinstance(items, list) else []


def node_top_level_keys(node: Any) -> List[str]:
    keys: set[str] = set()
    for item in node_config_items(node):
        if isinstance(item, dict):
            keys.update(str(key) for key in item.keys())
    return sorted(keys)


def build_graph(nodes: Any, links: Any) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Set[str]]]:
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


def degree_centrality(adjacency: Dict[str, Set[str]]) -> Dict[str, float]:
    node_count = len(adjacency)
    if node_count <= 1:
        return {node_id: 0.0 for node_id in adjacency}
    scale = 1.0 / (node_count - 1)
    return {node_id: len(neighbors) * scale for node_id, neighbors in adjacency.items()}


def betweenness_centrality(adjacency: Dict[str, Set[str]]) -> Dict[str, float]:
    """Compute normalized betweenness centrality for an undirected graph.

    The result is normalized to [0, 1] using the usual undirected maximum:
    2 / ((n - 1) * (n - 2)) for n > 2.
    """

    nodes = list(adjacency)
    centrality = {node: 0.0 for node in nodes}
    if len(nodes) <= 2:
        return centrality

    for source in nodes:
        stack: list[str] = []
        predecessors: Dict[str, list[str]] = {node: [] for node in nodes}
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

    scale = 1.0 / ((len(nodes) - 1) * (len(nodes) - 2))
    return {node: value * scale for node, value in centrality.items()}


def write_csv(path: Path, rows: Sequence[Dict[str, Any]], fieldnames: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def collect_rows(dataset_root: Path, splits: List[str], progress_interval: int) -> Tuple[List[Dict[str, Any]], Dict[Tuple[str, str], KeyCentralityStats], Dict[str, Any]]:
    files = list(iter_json_files(dataset_root, splits))
    total = len(files)
    started_at = time.time()
    rows: List[Dict[str, Any]] = []
    summary: Dict[str, Any] = {
        "dataset_root": str(dataset_root),
        "splits": splits,
        "total_files": total,
        "bad_json_files": 0,
        "files_without_nodes": 0,
        "files_without_links": 0,
        "missing_split_dirs": [split for split in splits if not (dataset_root / split).exists()],
    }
    per_key_stats: Dict[Tuple[str, str], KeyCentralityStats] = defaultdict(KeyCentralityStats)

    print("[key-centrality] start: %s files" % total, flush=True)
    for index, (split, path) in enumerate(files, start=1):
        graph, error = load_json(path)
        if error or graph is None:
            summary["bad_json_files"] += 1
            continue

        nodes = graph.get("nodes")
        links = graph.get("links")
        if not isinstance(nodes, list):
            summary["files_without_nodes"] += 1
        if not isinstance(links, list):
            summary["files_without_links"] += 1

        node_map, adjacency = build_graph(nodes, links)
        degree = degree_centrality(adjacency)
        betweenness = betweenness_centrality(adjacency)
        file_name = str(path.relative_to(dataset_root))

        for node_id, node in node_map.items():
            keys = node_top_level_keys(node)
            if not keys:
                continue
            for key in keys:
                degree_value = degree.get(node_id, 0.0)
                betweenness_value = betweenness.get(node_id, 0.0)
                rows.append(
                    {
                        "split": split,
                        "file": file_name,
                        "node_id": node_id,
                        "top_level_key": key,
                        "degree_centrality": degree_value,
                        "betweenness_centrality": betweenness_value,
                    }
                )
                bucket = per_key_stats[(split, key)]
                bucket.node_occurrences += 1
                bucket.degree_values.append(degree_value)
                bucket.betweenness_values.append(betweenness_value)
                bucket.files.add(file_name)

        if progress_interval > 0 and (index % progress_interval == 0 or index == total):
            elapsed = max(0.001, time.time() - started_at)
            speed = index / elapsed
            eta = (total - index) / speed if speed > 0 else 0.0
            percent = index / total * 100 if total else 100.0
            print(
                "[key-centrality] %s/%s files (%.2f%%), elapsed %.1fs, %.2f files/s, eta %.1fs"
                % (index, total, percent, elapsed, speed, eta),
                flush=True,
            )

    return rows, per_key_stats, summary


def summarize(values: List[float]) -> Dict[str, Any]:
    if not values:
        return {
            "count": 0,
            "min": None,
            "max": None,
            "mean": None,
            "median": None,
        }
    return {
        "count": len(values),
        "min": min(values),
        "max": max(values),
        "mean": round(mean(values), 6),
        "median": round(median(values), 6),
    }


def summary_rows(per_key_stats: Dict[Tuple[str, str], KeyCentralityStats]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for (split, key), stats in sorted(per_key_stats.items(), key=lambda item: (item[0][0], item[0][1])):
        degree_summary = summarize(stats.degree_values)
        betweenness_summary = summarize(stats.betweenness_values)
        rows.append(
            {
                "split": split,
                "top_level_key": key,
                "node_occurrences": stats.node_occurrences,
                "file_count": len(stats.files),
                "degree_mean": degree_summary["mean"],
                "degree_median": degree_summary["median"],
                "degree_min": degree_summary["min"],
                "degree_max": degree_summary["max"],
                "betweenness_mean": betweenness_summary["mean"],
                "betweenness_median": betweenness_summary["median"],
                "betweenness_min": betweenness_summary["min"],
                "betweenness_max": betweenness_summary["max"],
            }
        )
    return rows


def run(args: argparse.Namespace) -> None:
    splits = parse_csv_values(args.splits)
    rows, per_key_stats, summary = collect_rows(args.dataset_root, splits, args.progress_interval)
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    write_csv(output_dir / "per_node_top_level_key_centrality.csv", rows, PER_NODE_FIELDS)
    top_key_rows = summary_rows(per_key_stats)
    write_csv(output_dir / "top_level_key_centrality_summary.csv", top_key_rows, SUMMARY_FIELDS)

    summary.update(
        {
            "per_node_rows": len(rows),
            "unique_keys": len({key for _, key in per_key_stats}),
            "top_keys_by_split": {
                split: len([key for current_split, key in per_key_stats if current_split == split])
                for split in splits
            },
        }
    )
    write_json(output_dir / "summary.json", summary)
    print("[key-centrality] done. output: %s" % output_dir, flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze top-level key centrality distribution in graph datasets.")
    parser.add_argument("--dataset-root", type=Path, default=DEFAULT_DATASET_ROOT, help="Dataset root containing train/ and val/ directories.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Directory to write analysis outputs.")
    parser.add_argument("--splits", default=DEFAULT_SPLITS, help="Comma-separated split names, e.g. train,val.")
    parser.add_argument("--progress-interval", type=int, default=DEFAULT_PROGRESS_INTERVAL, help="Print progress every N files. Use 0 to disable.")
    return parser.parse_args()


def main() -> None:
    run(parse_args())


if __name__ == "__main__":
    main()
