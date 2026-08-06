#!/usr/bin/env python3
"""构造单节点一阶邻居与全部可达节点任务数据集。

每张原始拓扑使用固定随机种子选择一个合法节点。物理链路统一按无向图处理，
标准答案包含去重、排序后的一阶邻居节点 ID 和同一连通分量内的其他节点 ID。
一次运行同步生成 with_answer 和 without_answer 两套数据集。
"""

from __future__ import annotations

import argparse
import copy
import csv
import json
import random
from collections import Counter, deque
from pathlib import Path
from typing import Any


DEFAULT_DATASET_ROOT = Path("datasets")
DEFAULT_OUTPUT_ROOT = Path("node_neighborhood_reachability_dataset")
DEFAULT_RANDOM_SEED = 20260806
DEFAULT_SPLITS = ("train", "val")
DEFAULT_PROGRESS_INTERVAL = 100

WITH_ANSWER_DIR = "with_answer"
WITHOUT_ANSWER_DIR = "without_answer"
STATS_FILE = "node_neighborhood_reachability_stats.csv"
SUMMARY_FILE = "build_summary.json"
ISSUES_FILE = "build_issues.jsonl"

QUESTION_TEMPLATE = """请根据给定的无向物理网络拓扑，分析目标节点 ID：{target_node_id}。

你需要输出：

1. one_hop_neighbor_node_ids：与目标节点直接通过一条物理链路连接的全部一阶邻居节点 ID。
2. reachable_node_ids：从目标节点出发，经过一条或多条物理链路能够到达的全部节点 ID。

要求：
- 两个列表都不能包含目标节点 {target_node_id} 自身；
- reachable_node_ids 必须包含全部一阶邻居和全部间接可达节点；
- 不在目标节点所属连通分量中的节点不能输出；
- 节点必须使用 nodes[].id，不能使用设备名称；
- 每个节点 ID 在同一个列表中只能出现一次，不能重复；
- 同一对节点之间存在多条链路时，对应邻居节点仍然只输出一次；
- 两个列表中的节点 ID 按字典序从小到大排列；
- 不要输出解释、Markdown 代码块或其他字段，只输出一个合法 JSON 对象。

实际示例：

假设拓扑为 NODE_A--NODE_B--NODE_C，并且 NODE_B--NODE_D，NODE_E 与它们不连通。当目标节点为 NODE_A 时，正确输出为：

{{
  "one_hop_neighbor_node_ids": [
    "NODE_B"
  ],
  "reachable_node_ids": [
    "NODE_B",
    "NODE_C",
    "NODE_D"
  ]
}}

如果目标节点是孤立节点，正确输出为：

{{
  "one_hop_neighbor_node_ids": [],
  "reachable_node_ids": []
}}"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset-root",
        type=Path,
        default=DEFAULT_DATASET_ROOT,
        help="原始数据集根目录，默认: %(default)s",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="任务数据集输出根目录，默认: %(default)s",
    )
    parser.add_argument(
        "--splits",
        nargs="+",
        default=list(DEFAULT_SPLITS),
        help="处理的数据划分，默认: train val",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_RANDOM_SEED,
        help="固定随机种子，默认: %(default)s",
    )
    parser.add_argument(
        "--progress-interval",
        type=int,
        default=DEFAULT_PROGRESS_INTERVAL,
        help="每处理 N 个文件打印进度，0 表示关闭，默认: %(default)s",
    )
    parser.add_argument("--indent", type=int, default=2)
    args = parser.parse_args()
    if args.progress_interval < 0:
        parser.error("--progress-interval 不能小于 0")
    if args.indent < 0:
        parser.error("--indent 不能小于 0")
    return args


def iter_json_files(dataset_root: Path, split: str) -> list[Path]:
    split_root = dataset_root / split
    if not split_root.is_dir():
        return []
    return sorted(path for path in split_root.rglob("*.json") if path.is_file())


def load_graph(path: Path) -> tuple[dict[str, Any] | None, str]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as error:  # noqa: BLE001 - 坏文件应记录并继续批处理。
        return None, f"{type(error).__name__}: {error}"
    if not isinstance(value, dict):
        return None, f"top-level type is {type(value).__name__}, expected object"
    return value, ""


def collect_node_ids(
    graph: dict[str, Any],
) -> tuple[list[str], Counter[str], str]:
    nodes = graph.get("nodes")
    reasons: Counter[str] = Counter()
    if not isinstance(nodes, list):
        return [], reasons, "nodes-not-list"

    node_ids: list[str] = []
    seen: set[str] = set()
    duplicates: set[str] = set()
    for node in nodes:
        if not isinstance(node, dict):
            reasons["node-not-object"] += 1
            continue
        raw_id = node.get("id")
        if raw_id is None or not str(raw_id):
            reasons["missing-or-empty-node-id"] += 1
            continue
        node_id = str(raw_id)
        if node_id in seen:
            duplicates.add(node_id)
            continue
        seen.add(node_id)
        node_ids.append(node_id)
    if duplicates:
        return [], reasons, "duplicate-node-id: " + ", ".join(sorted(duplicates))
    if not node_ids:
        return [], reasons, "no-valid-node-id"
    return sorted(node_ids), reasons, ""


def build_adjacency(
    graph: dict[str, Any],
    node_ids: list[str],
) -> tuple[dict[str, set[str]], int, Counter[str]]:
    adjacency = {node_id: set() for node_id in node_ids}
    node_id_set = set(node_ids)
    reasons: Counter[str] = Counter()
    links = graph.get("links")
    if not isinstance(links, list):
        reasons["links-not-list"] += 1
        return adjacency, 0, reasons

    valid_link_count = 0
    for item in links:
        if not isinstance(item, dict):
            reasons["link-not-object"] += 1
            continue
        source = item.get("source")
        target = item.get("target")
        if source is None or target is None:
            reasons["missing-source-or-target"] += 1
            continue
        source_id = str(source)
        target_id = str(target)
        if source_id not in node_id_set or target_id not in node_id_set:
            reasons["endpoint-not-in-nodes"] += 1
            continue
        if source_id == target_id:
            reasons["self-loop"] += 1
            continue
        adjacency[source_id].add(target_id)
        adjacency[target_id].add(source_id)
        valid_link_count += 1
    return adjacency, valid_link_count, reasons


def reachable_node_ids(
    adjacency: dict[str, set[str]],
    target_node_id: str,
) -> list[str]:
    visited = {target_node_id}
    queue: deque[str] = deque([target_node_id])
    while queue:
        current = queue.popleft()
        for neighbor in sorted(adjacency[current]):
            if neighbor in visited:
                continue
            visited.add(neighbor)
            queue.append(neighbor)
    visited.remove(target_node_id)
    return sorted(visited)


def build_task_graph(
    graph: dict[str, Any],
    target_node_id: str,
    one_hop_ids: list[str],
    reachable_ids: list[str],
    split: str,
    source_file: str,
) -> dict[str, Any]:
    task_graph = copy.deepcopy(graph)
    for key in list(task_graph):
        if key.startswith("task_"):
            task_graph.pop(key)
    task_graph["task_target_node_id"] = target_node_id
    task_graph["task_question"] = QUESTION_TEMPLATE.format(
        target_node_id=target_node_id
    )
    task_graph["task_answer"] = {
        "one_hop_neighbor_node_ids": one_hop_ids,
        "reachable_node_ids": reachable_ids,
    }
    task_graph["task_metadata"] = {
        "task_name": "node_neighborhood_and_reachability",
        "split": split,
        "source_file": source_file,
        "graph_policy": "undirected_physical_topology",
        "samples_per_graph": 1,
    }
    return task_graph


def write_json(path: Path, value: Any, indent: int = 2) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=indent) + "\n",
        encoding="utf-8",
    )


def append_issue(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(value, ensure_ascii=False) + "\n")


def write_stats(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "split",
        "source_file",
        "output_file",
        "target_node_id",
        "node_count",
        "valid_link_count",
        "one_hop_neighbor_count",
        "reachable_node_count",
        "connected_component_size",
        "is_isolated",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def remove_stale_outputs(output_root: Path, split: str, relative_path: Path) -> None:
    for version in (WITH_ANSWER_DIR, WITHOUT_ANSWER_DIR):
        path = output_root / version / split / relative_path
        if path.is_file():
            path.unlink()


def build_dataset(args: argparse.Namespace) -> dict[str, Any]:
    dataset_root = args.dataset_root.resolve()
    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    issue_path = output_root / ISSUES_FILE
    if issue_path.exists():
        issue_path.unlink()

    rng = random.Random(args.seed)
    stats_rows: list[dict[str, Any]] = []
    summary: dict[str, Any] = {
        "dataset_root": str(dataset_root),
        "output_root": str(output_root),
        "seed": args.seed,
        "samples_per_graph": 1,
        "graph_policy": "undirected_physical_topology",
        "splits": {},
    }

    for split in args.splits:
        files = iter_json_files(dataset_root, split)
        skip_reasons: Counter[str] = Counter()
        ignored_node_reasons: Counter[str] = Counter()
        ignored_link_reasons: Counter[str] = Counter()
        split_summary: dict[str, Any] = {
            "input_files": len(files),
            "generated_files": 0,
            "skipped_files": 0,
            "isolated_target_samples": 0,
            "connected_target_samples": 0,
            "skip_reasons": {},
            "ignored_node_reasons": {},
            "ignored_link_reasons": {},
        }
        print(f"[{split}] found {len(files)} json files", flush=True)

        for file_index, source_path in enumerate(files, start=1):
            relative_path = source_path.relative_to(dataset_root / split)
            remove_stale_outputs(output_root, split, relative_path)
            graph, load_error = load_graph(source_path)
            reason = ""
            detail = load_error
            if graph is None:
                reason = "load-json-error"
            else:
                node_ids, node_reasons, reason = collect_node_ids(graph)
                ignored_node_reasons.update(node_reasons)
                detail = reason
                if reason.startswith("duplicate-node-id:"):
                    reason = "duplicate-node-id"

            if graph is None or reason:
                skip_reasons[reason] += 1
                append_issue(
                    issue_path,
                    {
                        "split": split,
                        "source_file": str(relative_path),
                        "issue": reason,
                        "detail": detail,
                    },
                )
            else:
                adjacency, valid_link_count, link_reasons = build_adjacency(
                    graph,
                    node_ids,
                )
                ignored_link_reasons.update(link_reasons)
                target_node_id = rng.choice(node_ids)
                one_hop_ids = sorted(adjacency[target_node_id])
                reachable_ids = reachable_node_ids(adjacency, target_node_id)
                if not set(one_hop_ids).issubset(reachable_ids):
                    raise AssertionError("一阶邻居必须属于可达节点集合")

                task_graph = build_task_graph(
                    graph,
                    target_node_id,
                    one_hop_ids,
                    reachable_ids,
                    split,
                    str(relative_path),
                )
                with_path = output_root / WITH_ANSWER_DIR / split / relative_path
                without_path = output_root / WITHOUT_ANSWER_DIR / split / relative_path
                write_json(with_path, task_graph, args.indent)
                hidden_graph = copy.deepcopy(task_graph)
                hidden_graph.pop("task_answer", None)
                write_json(without_path, hidden_graph, args.indent)

                is_isolated = not one_hop_ids
                split_summary["generated_files"] += 1
                split_summary[
                    "isolated_target_samples"
                    if is_isolated
                    else "connected_target_samples"
                ] += 1
                stats_rows.append(
                    {
                        "split": split,
                        "source_file": str(relative_path),
                        "output_file": str(with_path.relative_to(output_root)),
                        "target_node_id": target_node_id,
                        "node_count": len(node_ids),
                        "valid_link_count": valid_link_count,
                        "one_hop_neighbor_count": len(one_hop_ids),
                        "reachable_node_count": len(reachable_ids),
                        "connected_component_size": len(reachable_ids) + 1,
                        "is_isolated": is_isolated,
                    }
                )

            if args.progress_interval > 0 and (
                file_index % args.progress_interval == 0 or file_index == len(files)
            ):
                print(
                    f"[{split}] {file_index}/{len(files)}，"
                    f"已生成 {split_summary['generated_files']}，"
                    f"跳过 {sum(skip_reasons.values())}",
                    flush=True,
                )

        split_summary["skipped_files"] = sum(skip_reasons.values())
        split_summary["skip_reasons"] = dict(sorted(skip_reasons.items()))
        split_summary["ignored_node_reasons"] = dict(
            sorted(ignored_node_reasons.items())
        )
        split_summary["ignored_link_reasons"] = dict(
            sorted(ignored_link_reasons.items())
        )
        summary["splits"][split] = split_summary

    write_stats(output_root / STATS_FILE, stats_rows)
    write_json(output_root / SUMMARY_FILE, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


if __name__ == "__main__":
    build_dataset(parse_args())
