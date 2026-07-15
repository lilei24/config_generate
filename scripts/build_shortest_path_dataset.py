#!/usr/bin/env python3
"""构造两个节点之间最短链路任务数据集。

输入数据集目录结构默认是：

datasets/
  train/*.json
  val/*.json

输出数据集会保留 train/val 结构。每个输出 JSON 保留原始图结构，并在顶层新增：

- task_source_node: 源节点 id
- task_target_node: 目标节点 id
- task_answer: 所有最短路径答案

如果一张图无法找到连通的源/目标节点对，则跳过该 JSON，并把原因写入
build_issues.jsonl。
"""

from __future__ import annotations

import argparse
import copy
import json
import random
from collections import defaultdict, deque
from pathlib import Path
from typing import Any


DEFAULT_DATASET_ROOT = Path("datasets")
DEFAULT_OUTPUT_ROOT = Path("shortest_path_dataset")
DEFAULT_RANDOM_SEED = 20260715
DEFAULT_SPLITS = ("train", "val")
DEFAULT_MAX_ATTEMPTS_PER_GRAPH = 100
DEFAULT_PROGRESS_INTERVAL = 100


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset-root",
        type=Path,
        default=DEFAULT_DATASET_ROOT,
        help=f"原始数据集根目录，默认: {DEFAULT_DATASET_ROOT}",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help=f"输出任务数据集根目录，默认: {DEFAULT_OUTPUT_ROOT}",
    )
    parser.add_argument(
        "--splits",
        nargs="+",
        default=list(DEFAULT_SPLITS),
        help="需要处理的数据划分，默认: train val",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_RANDOM_SEED,
        help=f"随机种子，默认: {DEFAULT_RANDOM_SEED}",
    )
    parser.add_argument(
        "--max-attempts-per-graph",
        type=int,
        default=DEFAULT_MAX_ATTEMPTS_PER_GRAPH,
        help=f"每张图最多随机尝试多少组节点对，默认: {DEFAULT_MAX_ATTEMPTS_PER_GRAPH}",
    )
    parser.add_argument(
        "--progress-interval",
        type=int,
        default=DEFAULT_PROGRESS_INTERVAL,
        help=f"每处理多少个文件打印一次进度，默认: {DEFAULT_PROGRESS_INTERVAL}",
    )
    parser.add_argument(
        "--indent",
        type=int,
        default=2,
        help="输出 JSON 缩进，默认: 2",
    )
    return parser.parse_args()


def iter_json_files(dataset_root: Path, split: str) -> list[Path]:
    split_dir = dataset_root / split
    if not split_dir.exists():
        return []
    return sorted(path for path in split_dir.rglob("*.json") if path.is_file())


def load_json(path: Path) -> tuple[dict[str, Any] | None, str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - 坏文件需要记录并跳过。
        return None, str(exc)
    if not isinstance(data, dict):
        return None, f"top-level JSON type is {type(data).__name__}, expected object"
    return data, ""


def get_node_ids(graph: dict[str, Any]) -> list[str]:
    nodes = graph.get("nodes")
    if not isinstance(nodes, list):
        return []

    node_ids: list[str] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_id = node.get("id")
        if node_id is not None:
            node_ids.append(str(node_id))
    return node_ids


def build_adjacency(
    graph: dict[str, Any],
    node_id_set: set[str],
) -> tuple[dict[str, set[str]], dict[tuple[str, str], list[dict[str, Any]]]]:
    """根据 links 构造邻接表和边信息索引。

    directed=false 时按无向图处理，并为反向路径保存同一条原始 link。
    """

    directed = bool(graph.get("directed", False))
    adjacency: dict[str, set[str]] = {node_id: set() for node_id in node_id_set}
    link_lookup: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)

    links = graph.get("links")
    if not isinstance(links, list):
        return adjacency, link_lookup

    for index, link_item in enumerate(links):
        if not isinstance(link_item, dict):
            continue
        source = link_item.get("source")
        target = link_item.get("target")
        if source is None or target is None:
            continue
        source_id = str(source)
        target_id = str(target)
        if source_id not in node_id_set or target_id not in node_id_set:
            continue

        normalized_link = {
            "path_source": source_id,
            "path_target": target_id,
            "source": source_id,
            "target": target_id,
            "link_index": index,
            "link": link_item.get("link", {}),
        }
        adjacency[source_id].add(target_id)
        link_lookup[(source_id, target_id)].append(normalized_link)

        if not directed:
            adjacency[target_id].add(source_id)
            reverse_link = copy.deepcopy(normalized_link)
            reverse_link["path_source"] = target_id
            reverse_link["path_target"] = source_id
            link_lookup[(target_id, source_id)].append(reverse_link)

    return adjacency, link_lookup


def all_shortest_node_paths(
    adjacency: dict[str, set[str]],
    source: str,
    target: str,
) -> list[list[str]]:
    """用 BFS 返回 source 到 target 的全部最短节点路径。"""

    if source == target:
        return [[source]]
    if source not in adjacency or target not in adjacency:
        return []

    distances = {source: 0}
    parents: dict[str, list[str]] = defaultdict(list)
    queue: deque[str] = deque([source])

    while queue:
        current = queue.popleft()
        current_distance = distances[current]
        for neighbor in sorted(adjacency[current]):
            next_distance = current_distance + 1
            if neighbor not in distances:
                distances[neighbor] = next_distance
                parents[neighbor].append(current)
                queue.append(neighbor)
            elif distances[neighbor] == next_distance:
                parents[neighbor].append(current)

    if target not in distances:
        return []

    paths: list[list[str]] = []

    def backtrack(node_id: str, suffix: list[str]) -> None:
        if node_id == source:
            paths.append([source, *suffix])
            return
        for parent in sorted(parents[node_id]):
            backtrack(parent, [node_id, *suffix])

    backtrack(target, [])
    return sorted(paths)


def links_for_node_path(
    node_path: list[str],
    link_lookup: dict[tuple[str, str], list[dict[str, Any]]],
) -> list[list[dict[str, Any]]]:
    """把一条节点路径展开为链路路径。

    如果两个相邻节点之间存在多条平行链路，会输出所有链路组合。
    """

    if len(node_path) <= 1:
        return [[]]

    link_paths: list[list[dict[str, Any]]] = [[]]
    for left, right in zip(node_path, node_path[1:]):
        candidate_links = link_lookup.get((left, right), [])
        if not candidate_links:
            return []
        next_link_paths: list[list[dict[str, Any]]] = []
        for existing_path in link_paths:
            for link_item in candidate_links:
                next_link_paths.append([*existing_path, copy.deepcopy(link_item)])
        link_paths = next_link_paths
    return link_paths


def build_answer(
    node_paths: list[list[str]],
    link_lookup: dict[tuple[str, str], list[dict[str, Any]]],
) -> dict[str, Any]:
    shortest_paths = []
    for node_path in node_paths:
        for link_path in links_for_node_path(node_path, link_lookup):
            shortest_paths.append(
                {
                    "nodes": node_path,
                    "links": link_path,
                }
            )
    shortest_paths = sorted(shortest_paths, key=lambda item: json.dumps(item, sort_keys=True))
    return {
        "path_length": len(node_paths[0]) - 1 if node_paths else None,
        "shortest_paths": shortest_paths,
    }


def choose_connected_node_pair(
    node_ids: list[str],
    adjacency: dict[str, set[str]],
    rng: random.Random,
    max_attempts: int,
) -> tuple[str | None, str | None, list[list[str]]]:
    if len(node_ids) < 2:
        return None, None, []

    for _ in range(max_attempts):
        source, target = rng.sample(node_ids, 2)
        node_paths = all_shortest_node_paths(adjacency, source, target)
        if node_paths:
            return source, target, node_paths
    return None, None, []


def write_json(path: Path, data: dict[str, Any], indent: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=indent) + "\n",
        encoding="utf-8",
    )


def append_issue(output_root: Path, issue: dict[str, Any]) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    issue_path = output_root / "build_issues.jsonl"
    with issue_path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(issue, ensure_ascii=False) + "\n")


def process_file(
    input_path: Path,
    output_path: Path,
    split: str,
    rng: random.Random,
    max_attempts: int,
    indent: int,
) -> tuple[bool, str]:
    graph, error = load_json(input_path)
    if graph is None:
        return False, f"load-json-error: {error}"

    node_ids = get_node_ids(graph)
    if len(node_ids) < 2:
        return False, "not-enough-nodes"

    adjacency, link_lookup = build_adjacency(graph, set(node_ids))
    if not any(adjacency.values()):
        return False, "no-valid-links"

    source, target, node_paths = choose_connected_node_pair(
        node_ids=node_ids,
        adjacency=adjacency,
        rng=rng,
        max_attempts=max_attempts,
    )
    if source is None or target is None or not node_paths:
        return False, "no-connected-node-pair-found"

    task_graph = copy.deepcopy(graph)
    task_graph["task_source_node"] = source
    task_graph["task_target_node"] = target
    task_graph["task_answer"] = build_answer(node_paths, link_lookup)
    task_graph["task_metadata"] = {
        "task_name": "shortest_path_between_two_nodes",
        "split": split,
        "source_file": input_path.name,
    }
    write_json(output_path, task_graph, indent=indent)
    return True, ""


def build_dataset(args: argparse.Namespace) -> dict[str, Any]:
    rng = random.Random(args.seed)
    args.output_root.mkdir(parents=True, exist_ok=True)
    issue_path = args.output_root / "build_issues.jsonl"
    if issue_path.exists():
        issue_path.unlink()

    summary: dict[str, Any] = {
        "dataset_root": str(args.dataset_root),
        "output_root": str(args.output_root),
        "splits": {},
        "seed": args.seed,
        "max_attempts_per_graph": args.max_attempts_per_graph,
    }

    for split in args.splits:
        input_files = iter_json_files(args.dataset_root, split)
        split_summary = {
            "input_files": len(input_files),
            "built_files": 0,
            "skipped_files": 0,
        }
        print(f"[{split}] found {len(input_files)} json files")

        for index, input_path in enumerate(input_files, start=1):
            relative_path = input_path.relative_to(args.dataset_root / split)
            output_path = args.output_root / split / relative_path
            ok, reason = process_file(
                input_path=input_path,
                output_path=output_path,
                split=split,
                rng=rng,
                max_attempts=args.max_attempts_per_graph,
                indent=args.indent,
            )
            if ok:
                split_summary["built_files"] += 1
            else:
                split_summary["skipped_files"] += 1
                append_issue(
                    args.output_root,
                    {
                        "split": split,
                        "file": str(input_path),
                        "issue": reason,
                    },
                )

            if args.progress_interval > 0 and index % args.progress_interval == 0:
                print(
                    f"[{split}] processed {index}/{len(input_files)}, "
                    f"built={split_summary['built_files']}, "
                    f"skipped={split_summary['skipped_files']}"
                )

        summary["splits"][split] = split_summary

    write_json(args.output_root / "build_summary.json", summary, indent=2)
    return summary


def main() -> None:
    args = parse_args()
    summary = build_dataset(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
