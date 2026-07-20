#!/usr/bin/env python3
"""构造两个节点之间最短链路任务数据集。

输入数据集目录结构默认是：

datasets/
  train/*.json
  val/*.json

一次运行会生成两套内容一一对应的数据集：

- with_answer: 保留 task_answer，供 Harness 评分使用
- without_answer: 删除 task_answer，供 Agent 执行任务使用

两套数据集都会保留 train/val 结构。每个输出 JSON 保留原始图结构，并在顶层新增：

- task_source_node_id: 源节点 ID
- task_target_node_id: 目标节点 ID
- task_question: 要求输出全部最短路径及对应设备名称、角色序列的问题
- task_answer: 最短路径长度、节点 ID 路径、角色序列和设备名称序列

如果一张图无法找到连通的源/目标节点对，则跳过该 JSON，并把原因写入
build_issues.jsonl。
"""

from __future__ import annotations

import argparse
import copy
import csv
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
WITH_ANSWER_DIR_NAME = "with_answer"
WITHOUT_ANSWER_DIR_NAME = "without_answer"


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


def get_device(node: dict[str, Any]) -> dict[str, Any]:
    device = node.get("device")
    if device is None:
        device = node.get("devices", {})
    return device if isinstance(device, dict) else {}


def get_node_role(node: dict[str, Any]) -> str:
    topology_node = node.get("topologyNode")
    if not isinstance(topology_node, dict):
        return ""
    role = topology_node.get("DEVICEROLE")
    return str(role) if role is not None else ""


def get_node_information(
    graph: dict[str, Any],
) -> tuple[list[str], dict[str, str], dict[str, str]]:
    nodes = graph.get("nodes")
    if not isinstance(nodes, list):
        return [], {}, {}

    node_ids: list[str] = []
    node_name_by_id: dict[str, str] = {}
    node_role_by_id: dict[str, str] = {}
    seen_node_ids: set[str] = set()
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_id = node.get("id")
        if node_id is not None:
            node_id_str = str(node_id)
            if node_id_str in seen_node_ids:
                continue
            seen_node_ids.add(node_id_str)
            device = get_device(node)
            node_name = device.get("NAME")
            node_ids.append(node_id_str)
            node_name_by_id[node_id_str] = (
                str(node_name) if node_name is not None else node_id_str
            )
            node_role_by_id[node_id_str] = get_node_role(node)
    return node_ids, node_name_by_id, node_role_by_id


def build_adjacency(
    graph: dict[str, Any],
    node_id_set: set[str],
) -> dict[str, set[str]]:
    """根据 links 构造邻接表。

    directed=false 时按无向图处理。
    """

    directed = bool(graph.get("directed", False))
    adjacency: dict[str, set[str]] = {node_id: set() for node_id in node_id_set}

    links = graph.get("links")
    if not isinstance(links, list):
        return adjacency

    for link_item in links:
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

        adjacency[source_id].add(target_id)

        if not directed:
            adjacency[target_id].add(source_id)

    return adjacency


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


def build_answer(
    node_paths: list[list[str]],
    node_name_by_id: dict[str, str],
    node_role_by_id: dict[str, str],
) -> dict[str, Any]:
    ordered_paths = sorted(node_paths)
    return {
        "path_length": len(ordered_paths[0]) - 1 if ordered_paths else None,
        "paths": ordered_paths,
        "path_role_sequences": [
            [node_role_by_id.get(node_id, "") for node_id in path]
            for path in ordered_paths
        ],
        "path_device_names": [
            [node_name_by_id.get(node_id, node_id) for node_id in path]
            for path in ordered_paths
        ],
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
    output_path_with_answer: Path,
    output_path_without_answer: Path,
    split: str,
    rng: random.Random,
    max_attempts: int,
    indent: int,
) -> tuple[bool, str, dict[str, Any] | None]:
    graph, error = load_json(input_path)
    if graph is None:
        return False, f"load-json-error: {error}", None

    node_ids, node_name_by_id, node_role_by_id = get_node_information(graph)
    if len(node_ids) < 2:
        return False, "not-enough-nodes", None

    adjacency = build_adjacency(graph, set(node_ids))
    if not any(adjacency.values()):
        return False, "no-valid-links", None

    source, target, node_paths = choose_connected_node_pair(
        node_ids=node_ids,
        adjacency=adjacency,
        rng=rng,
        max_attempts=max_attempts,
    )
    if source is None or target is None or not node_paths:
        return False, "no-connected-node-pair-found", None

    task_graph = copy.deepcopy(graph)
    task_graph["task_source_node_id"] = source
    task_graph["task_target_node_id"] = target
    task_graph["task_question"] = (
        f"请查找节点 ID {source} 到节点 ID {target} 的全部最短物理路径。"
        "请输出最短路径长度、全部最短路径的节点 ID 序列，以及每条路径"
        "对应的设备名称序列和 DEVICEROLE 序列。"
    )
    task_graph["task_answer"] = build_answer(
        node_paths,
        node_name_by_id,
        node_role_by_id,
    )
    task_graph["task_metadata"] = {
        "task_name": "shortest_path_between_two_nodes",
        "split": split,
        "source_file": input_path.name,
    }
    # 两个版本必须由同一个已完成随机选择的样本派生，保证除答案字段外完全一致。
    write_json(output_path_with_answer, task_graph, indent=indent)
    task_graph_without_answer = copy.deepcopy(task_graph)
    task_graph_without_answer.pop("task_answer", None)
    write_json(output_path_without_answer, task_graph_without_answer, indent=indent)
    return True, "", {
        "split": split,
        "file": str(input_path),
        "output_file_with_answer": str(output_path_with_answer),
        "output_file_without_answer": str(output_path_without_answer),
        "shortest_path_length": len(node_paths[0]) - 1,
        "shortest_path_count": len(node_paths),
    }


def write_stats_csv(output_root: Path, rows: list[dict[str, Any]]) -> None:
    stats_path = output_root / "shortest_path_stats.csv"
    fieldnames = [
        "split",
        "file",
        "output_file_with_answer",
        "output_file_without_answer",
        "shortest_path_length",
        "shortest_path_count",
    ]
    with stats_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def build_dataset(args: argparse.Namespace) -> dict[str, Any]:
    rng = random.Random(args.seed)
    args.output_root.mkdir(parents=True, exist_ok=True)
    issue_path = args.output_root / "build_issues.jsonl"
    if issue_path.exists():
        issue_path.unlink()

    summary: dict[str, Any] = {
        "dataset_root": str(args.dataset_root),
        "output_root": str(args.output_root),
        "with_answer_root": str(args.output_root / WITH_ANSWER_DIR_NAME),
        "without_answer_root": str(args.output_root / WITHOUT_ANSWER_DIR_NAME),
        "splits": {},
        "seed": args.seed,
        "max_attempts_per_graph": args.max_attempts_per_graph,
    }
    stats_rows: list[dict[str, Any]] = []

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
            output_path_with_answer = (
                args.output_root / WITH_ANSWER_DIR_NAME / split / relative_path
            )
            output_path_without_answer = (
                args.output_root / WITHOUT_ANSWER_DIR_NAME / split / relative_path
            )
            ok, reason, stats_row = process_file(
                input_path=input_path,
                output_path_with_answer=output_path_with_answer,
                output_path_without_answer=output_path_without_answer,
                split=split,
                rng=rng,
                max_attempts=args.max_attempts_per_graph,
                indent=args.indent,
            )
            if ok:
                split_summary["built_files"] += 1
                if stats_row is not None:
                    stats_rows.append(stats_row)
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
    write_stats_csv(args.output_root, stats_rows)
    return summary


def main() -> None:
    args = parse_args()
    summary = build_dataset(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
