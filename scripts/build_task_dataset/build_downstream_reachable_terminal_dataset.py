#!/usr/bin/env python3
"""构造“指定 CORE 或 Firewall 的下游可达终端”任务数据集。

物理链路统一按无向简单图处理。终端叶子定义为度数等于 1、设备类型为 AP
或 LSW，且自身角色不是 CORE/Firewall 的节点。CORE 与 Firewall 分别建立
归属体系：叶子节点只归属于唯一最近的同角色核心上游节点；同角色距离并列时
不归属于任何一方。
"""

from __future__ import annotations

import argparse
import copy
import csv
import json
import random
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_DATASET_ROOT = Path("datasets")
DEFAULT_OUTPUT_ROOT = Path("downstream_reachable_terminal_dataset")
DEFAULT_RANDOM_SEED = 20260826
DEFAULT_SPLITS = ("train", "val")
DEFAULT_PROGRESS_INTERVAL = 100

WITH_ANSWER_DIR = "with_answer"
WITHOUT_ANSWER_DIR = "without_answer"
STATS_FILE = "downstream_reachable_terminal_stats.csv"
SUMMARY_FILE = "build_summary.json"
ISSUES_FILE = "build_issues.jsonl"
UPSTREAM_ROLES = ("CORE", "Firewall")
TERMINAL_DEVICE_TYPES = ("AP", "LSW")

QUESTION_TEMPLATE = """请查找核心上游节点 ID {upstream_node_id}（DEVICEROLE 为 {upstream_role}）的全部下游可达终端节点。

请严格按照以下 JSON Schema 输出：
{{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "downstream_terminal_node_ids"
  ],
  "properties": {{
    "downstream_terminal_node_ids": {{
      "type": "array",
      "description": "全部下游可达终端的节点 ID",
      "items": {{
        "type": "string"
      }}
    }}
  }}
}}

只输出 JSON，不要输出解释、Markdown 或代码块。

输出示例如下：
{{
  "downstream_terminal_node_ids": [
    "AP_NODE_1",
    "AP_NODE_2"
  ]
}}"""


@dataclass(frozen=True)
class NodeInformation:
    node_ids: list[str]
    role_by_id: dict[str, str]
    type_by_id: dict[str, str]


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
    except Exception as error:  # noqa: BLE001 - 单个坏文件不能中断批处理。
        return None, f"{type(error).__name__}: {error}"
    if not isinstance(value, dict):
        return None, f"top-level type is {type(value).__name__}, expected object"
    return value, ""


def get_node_role(node: dict[str, Any]) -> str:
    topology = node.get("topologyNode")
    if not isinstance(topology, dict):
        return ""
    value = topology.get("DEVICEROLE")
    return str(value).strip() if value is not None else ""


def get_node_type(node: dict[str, Any]) -> str:
    device = node.get("device")
    if not isinstance(device, dict):
        device = node.get("devices")
    if not isinstance(device, dict):
        return ""
    value = device.get("TYPE")
    return str(value).strip() if value is not None else ""


def collect_node_information(
    graph: dict[str, Any],
) -> tuple[NodeInformation | None, Counter[str], str]:
    nodes = graph.get("nodes")
    ignored: Counter[str] = Counter()
    if not isinstance(nodes, list):
        return None, ignored, "nodes-not-list"

    node_ids: list[str] = []
    role_by_id: dict[str, str] = {}
    type_by_id: dict[str, str] = {}
    duplicates: set[str] = set()
    for node in nodes:
        if not isinstance(node, dict):
            ignored["node-not-object"] += 1
            continue
        raw_id = node.get("id")
        if raw_id is None or not str(raw_id):
            ignored["missing-or-empty-node-id"] += 1
            continue
        node_id = str(raw_id)
        if node_id in role_by_id:
            duplicates.add(node_id)
            continue
        node_ids.append(node_id)
        role_by_id[node_id] = get_node_role(node)
        type_by_id[node_id] = get_node_type(node)
    if duplicates:
        return None, ignored, "duplicate-node-id: " + ", ".join(sorted(duplicates))
    if not node_ids:
        return None, ignored, "no-valid-node-id"
    return NodeInformation(sorted(node_ids), role_by_id, type_by_id), ignored, ""


def build_adjacency(
    graph: dict[str, Any],
    node_ids: list[str],
) -> tuple[dict[str, set[str]], int, Counter[str]]:
    adjacency = {node_id: set() for node_id in node_ids}
    node_id_set = set(node_ids)
    ignored: Counter[str] = Counter()
    links = graph.get("links")
    if not isinstance(links, list):
        ignored["links-not-list"] += 1
        return adjacency, 0, ignored

    valid_link_count = 0
    for link in links:
        if not isinstance(link, dict):
            ignored["link-not-object"] += 1
            continue
        source = link.get("source")
        target = link.get("target")
        if source is None or target is None:
            ignored["missing-source-or-target"] += 1
            continue
        source_id = str(source)
        target_id = str(target)
        if source_id not in node_id_set or target_id not in node_id_set:
            ignored["endpoint-not-in-nodes"] += 1
            continue
        if source_id == target_id:
            ignored["self-loop"] += 1
            continue
        if target_id not in adjacency[source_id]:
            valid_link_count += 1
        adjacency[source_id].add(target_id)
        adjacency[target_id].add(source_id)
    return adjacency, valid_link_count, ignored


def shortest_distances(
    adjacency: dict[str, set[str]], source_id: str
) -> dict[str, int]:
    distances = {source_id: 0}
    queue: deque[str] = deque([source_id])
    while queue:
        current = queue.popleft()
        for neighbor in sorted(adjacency[current]):
            if neighbor not in distances:
                distances[neighbor] = distances[current] + 1
                queue.append(neighbor)
    return distances


def assign_leaf_nodes(
    node_info: NodeInformation,
    adjacency: dict[str, set[str]],
) -> tuple[
    dict[str, list[str]],
    dict[str, dict[str, int]],
    list[str],
    Counter[str],
]:
    upstream_by_role = {
        role: sorted(
            node_id
            for node_id in node_info.node_ids
            if node_info.role_by_id.get(node_id) == role
        )
        for role in UPSTREAM_ROLES
    }
    leaf_node_ids = sorted(
        node_id
        for node_id in node_info.node_ids
        if len(adjacency[node_id]) == 1
        and node_info.type_by_id.get(node_id) in TERMINAL_DEVICE_TYPES
        and node_info.role_by_id.get(node_id) not in UPSTREAM_ROLES
    )
    distances_by_upstream = {
        upstream_id: shortest_distances(adjacency, upstream_id)
        for upstream_ids in upstream_by_role.values()
        for upstream_id in upstream_ids
    }
    assignments: dict[str, list[str]] = defaultdict(list)
    assignment_reasons: Counter[str] = Counter()

    # CORE 与 Firewall 独立计算，因此同一个叶子可以分别归属于一个 CORE 和一个 Firewall。
    for role, upstream_ids in upstream_by_role.items():
        if not upstream_ids:
            continue
        for leaf_id in leaf_node_ids:
            reachable = [
                (
                    distances_by_upstream[upstream_id][leaf_id],
                    upstream_id,
                )
                for upstream_id in upstream_ids
                if leaf_id in distances_by_upstream[upstream_id]
            ]
            if not reachable:
                assignment_reasons[f"unreachable-from-any-{role}"] += 1
                continue
            minimum_distance = min(distance for distance, _ in reachable)
            nearest = sorted(
                upstream_id
                for distance, upstream_id in reachable
                if distance == minimum_distance
            )
            if len(nearest) != 1:
                assignment_reasons[f"equal-distance-{role}-tie"] += 1
                continue
            assignments[nearest[0]].append(leaf_id)

    normalized_assignments = {
        upstream_id: sorted(leaf_ids)
        for upstream_id, leaf_ids in assignments.items()
    }
    return (
        normalized_assignments,
        distances_by_upstream,
        leaf_node_ids,
        assignment_reasons,
    )


def build_task_graph(
    graph: dict[str, Any],
    upstream_node_id: str,
    upstream_role: str,
    downstream_leaf_ids: list[str],
    split: str,
    source_file: str,
) -> dict[str, Any]:
    task_graph = copy.deepcopy(graph)
    for key in list(task_graph):
        if key.startswith("task_"):
            task_graph.pop(key)
    task_graph["task_upstream_node_id"] = upstream_node_id
    task_graph["task_question"] = QUESTION_TEMPLATE.format(
        upstream_node_id=upstream_node_id,
        upstream_role=upstream_role,
    )
    task_graph["task_answer"] = {
        "downstream_terminal_node_ids": downstream_leaf_ids,
    }
    task_graph["task_metadata"] = {
        "task_name": "downstream_reachable_terminal",
        "split": split,
        "source_file": source_file,
        "upstream_role": upstream_role,
        "graph_policy": "undirected_simple_physical_topology",
        "leaf_policy": "degree_one_ap_or_lsw_excluding_upstream_roles",
        "terminal_device_types": list(TERMINAL_DEVICE_TYPES),
        "assignment_policy": "unique_nearest_same_role_upstream",
        "upstream_roles": list(UPSTREAM_ROLES),
        "equal_distance_policy": "exclude",
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
        "upstream_node_id",
        "upstream_role",
        "same_role_upstream_count",
        "node_count",
        "valid_link_count",
        "leaf_candidate_count",
        "downstream_leaf_count",
        "maximum_downstream_distance",
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
        "upstream_roles": list(UPSTREAM_ROLES),
        "graph_policy": "undirected_simple_physical_topology",
        "leaf_policy": "degree_one_ap_or_lsw_excluding_upstream_roles",
        "terminal_device_types": list(TERMINAL_DEVICE_TYPES),
        "assignment_policy": "unique_nearest_same_role_upstream",
        "equal_distance_policy": "exclude",
        "splits": {},
    }

    for split in args.splits:
        files = iter_json_files(dataset_root, split)
        skip_reasons: Counter[str] = Counter()
        ignored_node_reasons: Counter[str] = Counter()
        ignored_link_reasons: Counter[str] = Counter()
        assignment_reasons: Counter[str] = Counter()
        generated_by_role: Counter[str] = Counter()
        split_summary: dict[str, Any] = {
            "input_files": len(files),
            "generated_files": 0,
            "skipped_files": 0,
            "generated_by_upstream_role": {},
            "skip_reasons": {},
            "leaf_assignment_reasons": {},
            "ignored_node_reasons": {},
            "ignored_link_reasons": {},
        }
        print(f"[{split}] found {len(files)} json files", flush=True)

        for file_index, source_path in enumerate(files, start=1):
            relative_path = source_path.relative_to(dataset_root / split)
            remove_stale_outputs(output_root, split, relative_path)
            graph, load_error = load_graph(source_path)
            reason = ""
            detail: Any = load_error
            node_info: NodeInformation | None = None

            if graph is None:
                reason = "load-json-error"
            else:
                node_info, node_reasons, reason = collect_node_information(graph)
                ignored_node_reasons.update(node_reasons)
                detail = reason
                if reason.startswith("duplicate-node-id:"):
                    detail = reason
                    reason = "duplicate-node-id"

            if graph is None or node_info is None or reason:
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
                    graph, node_info.node_ids
                )
                ignored_link_reasons.update(link_reasons)
                upstream_ids = sorted(
                    node_id
                    for node_id in node_info.node_ids
                    if node_info.role_by_id.get(node_id) in UPSTREAM_ROLES
                )
                if not upstream_ids:
                    reason = "no-core-or-firewall-node"
                else:
                    (
                        assignments,
                        distances_by_upstream,
                        leaf_node_ids,
                        per_graph_assignment_reasons,
                    ) = assign_leaf_nodes(node_info, adjacency)
                    assignment_reasons.update(per_graph_assignment_reasons)
                    eligible_upstream_ids = sorted(
                        node_id for node_id in upstream_ids if assignments.get(node_id)
                    )
                    if not leaf_node_ids:
                        reason = "no-degree-one-ap-or-lsw-terminal"
                    elif not eligible_upstream_ids:
                        reason = "no-upstream-with-uniquely-assigned-leaf"
                    else:
                        upstream_node_id = rng.choice(eligible_upstream_ids)
                        upstream_role = node_info.role_by_id[upstream_node_id]
                        downstream_leaf_ids = assignments[upstream_node_id]
                        task_graph = build_task_graph(
                            graph,
                            upstream_node_id,
                            upstream_role,
                            downstream_leaf_ids,
                            split,
                            str(relative_path),
                        )
                        with_path = (
                            output_root / WITH_ANSWER_DIR / split / relative_path
                        )
                        without_path = (
                            output_root / WITHOUT_ANSWER_DIR / split / relative_path
                        )
                        write_json(with_path, task_graph, args.indent)
                        hidden_graph = copy.deepcopy(task_graph)
                        hidden_graph.pop("task_answer", None)
                        write_json(without_path, hidden_graph, args.indent)

                        selected_distances = distances_by_upstream[upstream_node_id]
                        stats_rows.append(
                            {
                                "split": split,
                                "source_file": str(relative_path),
                                "output_file": str(with_path.relative_to(output_root)),
                                "upstream_node_id": upstream_node_id,
                                "upstream_role": upstream_role,
                                "same_role_upstream_count": sum(
                                    role == upstream_role
                                    for role in node_info.role_by_id.values()
                                ),
                                "node_count": len(node_info.node_ids),
                                "valid_link_count": valid_link_count,
                                "leaf_candidate_count": len(leaf_node_ids),
                                "downstream_leaf_count": len(downstream_leaf_ids),
                                "maximum_downstream_distance": max(
                                    selected_distances[leaf_id]
                                    for leaf_id in downstream_leaf_ids
                                ),
                            }
                        )
                        split_summary["generated_files"] += 1
                        generated_by_role[upstream_role] += 1

                if reason:
                    skip_reasons[reason] += 1
                    append_issue(
                        issue_path,
                        {
                            "split": split,
                            "source_file": str(relative_path),
                            "issue": reason,
                        },
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
        split_summary["generated_by_upstream_role"] = dict(
            sorted(generated_by_role.items())
        )
        split_summary["skip_reasons"] = dict(sorted(skip_reasons.items()))
        split_summary["leaf_assignment_reasons"] = dict(
            sorted(assignment_reasons.items())
        )
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
