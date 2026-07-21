#!/usr/bin/env python3
"""基于最近目标任务数据集构造单节点故障绕行任务。

默认输入是 ``nearest_core_dataset/with_answer/{train,val}``。每张输入图已经包含
一个源 AP，以及该 AP 到当前最高可达目标层级的全部最短节点 ID 路径。本脚本
执行以下处理：

1. 筛选节点数至少为 3 的基线最短路径；
2. 从路径中间节点中选择一个故障节点，源 AP 和目标节点不会被选中；
3. 从计算图中移除故障节点及其关联链路，重新计算源节点到同一目标的全部最短路径；
4. 只保留故障后仍然可达的样本；
5. 优先选择跳数增加的 detour，找不到时使用等长的 equal_cost_failover；
6. 同时生成 with_answer 和 without_answer，两个版本除 task_answer 外完全一致。

原“最近目标”任务的 question、answer 和 metadata 会被替换，避免旧答案泄漏到
新任务。故障节点仍保留在原始拓扑中，只通过任务字段声明故障。
"""

from __future__ import annotations

import argparse
import copy
import csv
import json
import random
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_INPUT_ROOT = Path("nearest_core_dataset/with_answer")
DEFAULT_OUTPUT_ROOT = Path("node_failure_reroute_dataset")
DEFAULT_RANDOM_SEED = 20260715
DEFAULT_SPLITS = ("train", "val")
DEFAULT_PROGRESS_INTERVAL = 100
DEFAULT_MIN_BASELINE_PATH_NODE_COUNT = 3
WITH_ANSWER_DIR_NAME = "with_answer"
WITHOUT_ANSWER_DIR_NAME = "without_answer"


@dataclass(frozen=True)
class NodeInformation:
    node_ids: list[str]
    node_role_by_id: dict[str, str]


@dataclass(frozen=True)
class RerouteCandidate:
    source_id: str
    target_id: str
    failed_node_id: str
    baseline_paths: list[list[str]]
    reroute_paths: list[list[str]]
    reroute_type: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-root",
        type=Path,
        default=DEFAULT_INPUT_ROOT,
        help=f"最近目标有答案数据集根目录，默认: {DEFAULT_INPUT_ROOT}",
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
        "--progress-interval",
        type=int,
        default=DEFAULT_PROGRESS_INTERVAL,
        help=f"每处理多少个文件打印一次进度，默认: {DEFAULT_PROGRESS_INTERVAL}",
    )
    parser.add_argument(
        "--min-baseline-path-node-count",
        type=int,
        default=DEFAULT_MIN_BASELINE_PATH_NODE_COUNT,
        help=(
            "可用于构造故障任务的基线路径最少节点数，默认: "
            f"{DEFAULT_MIN_BASELINE_PATH_NODE_COUNT}"
        ),
    )
    parser.add_argument(
        "--indent",
        type=int,
        default=2,
        help="输出 JSON 缩进，默认: 2",
    )
    args = parser.parse_args()
    if args.min_baseline_path_node_count < 3:
        parser.error("--min-baseline-path-node-count 不能小于 3")
    return args


def iter_json_files(input_root: Path, split: str) -> list[Path]:
    split_dir = input_root / split
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


def get_node_role(node: dict[str, Any]) -> str:
    topology_node = node.get("topologyNode")
    if not isinstance(topology_node, dict):
        return ""
    role = topology_node.get("DEVICEROLE")
    return str(role) if role is not None else ""


def get_node_information(graph: dict[str, Any]) -> NodeInformation:
    nodes = graph.get("nodes")
    if not isinstance(nodes, list):
        return NodeInformation([], {})

    node_ids: list[str] = []
    node_role_by_id: dict[str, str] = {}
    seen_node_ids: set[str] = set()

    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_id = node.get("id")
        if node_id is None:
            continue

        node_id_str = str(node_id)
        if node_id_str in seen_node_ids:
            continue
        seen_node_ids.add(node_id_str)
        node_ids.append(node_id_str)
        node_role_by_id[node_id_str] = get_node_role(node)
    return NodeInformation(
        node_ids=node_ids,
        node_role_by_id=node_role_by_id,
    )


def build_adjacency(
    graph: dict[str, Any],
    node_id_set: set[str],
) -> dict[str, set[str]]:
    """根据 links 构造邻接表，directed=false 时按无向图处理。"""

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


def remove_node_from_adjacency(
    adjacency: dict[str, set[str]],
    failed_node_id: str,
) -> dict[str, set[str]]:
    """移除故障节点和全部入边、出边，不修改原邻接表。"""

    return {
        node_id: {neighbor for neighbor in neighbors if neighbor != failed_node_id}
        for node_id, neighbors in adjacency.items()
        if node_id != failed_node_id
    }


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
        next_distance = distances[current] + 1
        for neighbor in sorted(adjacency.get(current, set())):
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


def extract_target_roles(graph: dict[str, Any]) -> tuple[str | None, set[str]]:
    task_metadata = graph.get("task_metadata")
    if not isinstance(task_metadata, dict):
        return None, set()
    target_tier = task_metadata.get("target_tier")
    target_roles = task_metadata.get("target_roles")
    if not isinstance(target_tier, str) or not isinstance(target_roles, list):
        return None, set()
    roles = {
        role for role in target_roles if isinstance(role, str) and role
    }
    return target_tier, roles


def extract_eligible_target_ids(
    graph: dict[str, Any],
    source_id: str,
    valid_node_ids: set[str],
    target_roles: set[str],
    node_role_by_id: dict[str, str],
    min_path_node_count: int,
) -> list[str]:
    """从上游答案的节点 ID 路径中提取符合角色和长度要求的目标。"""

    task_answer = graph.get("task_answer")
    if not isinstance(task_answer, dict):
        return []
    answer_paths = task_answer.get("paths")
    if not isinstance(answer_paths, list):
        return []

    target_ids: set[str] = set()
    for path in answer_paths:
        if not isinstance(path, list) or len(path) < min_path_node_count:
            continue
        if not all(isinstance(node_id, str) for node_id in path):
            continue
        if path[0] != source_id or any(
            node_id not in valid_node_ids for node_id in path
        ):
            continue
        target_id = path[-1]
        if node_role_by_id.get(target_id) not in target_roles:
            continue
        target_ids.add(target_id)
    return sorted(target_ids)


def evaluate_candidates(
    source_id: str,
    target_ids: list[str],
    adjacency: dict[str, set[str]],
    rng: random.Random,
    min_path_node_count: int,
) -> tuple[RerouteCandidate | None, dict[str, int]]:
    """枚举可用故障节点，优先随机选择 detour，其次等长切换。"""

    detour_candidates: list[RerouteCandidate] = []
    equal_cost_candidates: list[RerouteCandidate] = []
    counters = {
        "target_candidates": len(target_ids),
        "failed_node_candidates": 0,
        "disconnecting_candidates": 0,
        "detour_candidates": 0,
        "equal_cost_candidates": 0,
    }

    for target_id in target_ids:
        baseline_paths = all_shortest_node_paths(adjacency, source_id, target_id)
        if not baseline_paths or len(baseline_paths[0]) < min_path_node_count:
            continue

        failed_node_ids = sorted(
            {
                node_id
                for path in baseline_paths
                for node_id in path[1:-1]
            }
        )
        for failed_node_id in failed_node_ids:
            counters["failed_node_candidates"] += 1
            reroute_adjacency = remove_node_from_adjacency(adjacency, failed_node_id)
            reroute_paths = all_shortest_node_paths(
                reroute_adjacency,
                source_id,
                target_id,
            )
            if not reroute_paths:
                counters["disconnecting_candidates"] += 1
                continue

            baseline_length = len(baseline_paths[0]) - 1
            reroute_length = len(reroute_paths[0]) - 1
            reroute_type = (
                "detour" if reroute_length > baseline_length else "equal_cost_failover"
            )
            candidate = RerouteCandidate(
                source_id=source_id,
                target_id=target_id,
                failed_node_id=failed_node_id,
                baseline_paths=baseline_paths,
                reroute_paths=reroute_paths,
                reroute_type=reroute_type,
            )
            if reroute_type == "detour":
                detour_candidates.append(candidate)
            else:
                equal_cost_candidates.append(candidate)

    counters["detour_candidates"] = len(detour_candidates)
    counters["equal_cost_candidates"] = len(equal_cost_candidates)
    if detour_candidates:
        return rng.choice(detour_candidates), counters
    if equal_cost_candidates:
        return rng.choice(equal_cost_candidates), counters
    return None, counters


def build_task_answer(
    candidate: RerouteCandidate,
) -> dict[str, Any]:
    return {
        "path_length": len(candidate.reroute_paths[0]) - 1,
        "paths": sorted(candidate.reroute_paths),
    }


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
    min_path_node_count: int,
    indent: int,
) -> tuple[bool, str, dict[str, Any] | None]:
    graph, error = load_json(input_path)
    if graph is None:
        return False, f"load-json-error: {error}", None

    source_id = graph.get("task_source_node_id")
    if not isinstance(source_id, str) or not source_id:
        return False, "missing-task-source-node-id", None

    node_info = get_node_information(graph)
    if not node_info.node_ids:
        return False, "no-valid-nodes", None
    node_id_set = set(node_info.node_ids)
    if source_id not in node_id_set:
        return False, "source-node-id-not-found", None

    target_tier, target_roles = extract_target_roles(graph)
    if target_tier is None or not target_roles:
        return False, "missing-target-tier-metadata", None

    target_ids = extract_eligible_target_ids(
        graph=graph,
        source_id=source_id,
        valid_node_ids=node_id_set,
        target_roles=target_roles,
        node_role_by_id=node_info.node_role_by_id,
        min_path_node_count=min_path_node_count,
    )
    if not target_ids:
        return False, "no-eligible-baseline-target", None

    adjacency = build_adjacency(graph, node_id_set)
    if not any(adjacency.values()):
        return False, "no-valid-links", None

    candidate, counters = evaluate_candidates(
        source_id=source_id,
        target_ids=target_ids,
        adjacency=adjacency,
        rng=rng,
        min_path_node_count=min_path_node_count,
    )
    if candidate is None:
        if counters["failed_node_candidates"] == 0:
            return False, "no-intermediate-node-candidate", None
        return False, "all-intermediate-node-failures-disconnect-target", None

    task_graph = copy.deepcopy(graph)
    for old_task_field in (
        "task_source_node_name",
        "task_target_node_name",
        "task_failed_node_name",
        "task_source_node_id",
        "task_target_node_id",
        "task_failed_node_id",
        "task_question",
        "task_answer",
        "task_metadata",
    ):
        task_graph.pop(old_task_field, None)

    task_graph["task_source_node_id"] = source_id
    task_graph["task_target_node_id"] = candidate.target_id
    task_graph["task_failed_node_id"] = candidate.failed_node_id
    task_graph["task_question"] = (
        f"节点 ID {candidate.failed_node_id} 发生故障。请查找节点 ID {source_id} "
        f"到节点 ID {candidate.target_id} 当前可用的全部最短物理路径，"
        "计算时不得经过该故障节点。请输出最短跳数和全部最短路径，"
        "路径中的节点使用节点 ID。"
    )
    task_graph["task_answer"] = build_task_answer(candidate)
    task_graph["task_metadata"] = {
        "task_name": "node_failure_rerouting",
        "split": split,
        "source_file": input_path.name,
        "target_tier": target_tier,
        "target_roles": sorted(target_roles),
    }

    write_json(output_path_with_answer, task_graph, indent=indent)
    task_graph_without_answer = copy.deepcopy(task_graph)
    task_graph_without_answer.pop("task_answer", None)
    write_json(output_path_without_answer, task_graph_without_answer, indent=indent)

    baseline_path_length = len(candidate.baseline_paths[0]) - 1
    reroute_path_length = len(candidate.reroute_paths[0]) - 1
    return True, "", {
        "split": split,
        "file": str(input_path),
        "output_file_with_answer": str(output_path_with_answer),
        "output_file_without_answer": str(output_path_without_answer),
        "source_node_id": source_id,
        "target_node_id": candidate.target_id,
        "failed_node_id": candidate.failed_node_id,
        "target_tier": target_tier,
        "target_roles": "|".join(sorted(target_roles)),
        "failed_node_role": node_info.node_role_by_id.get(
            candidate.failed_node_id,
            "",
        ),
        "reroute_type": candidate.reroute_type,
        "baseline_path_length": baseline_path_length,
        "baseline_path_count": len(candidate.baseline_paths),
        "reroute_path_length": reroute_path_length,
        "reroute_path_count": len(candidate.reroute_paths),
        "hop_change": reroute_path_length - baseline_path_length,
        **counters,
    }


def write_stats_csv(output_root: Path, rows: list[dict[str, Any]]) -> None:
    stats_path = output_root / "node_failure_reroute_stats.csv"
    fieldnames = [
        "split",
        "file",
        "output_file_with_answer",
        "output_file_without_answer",
        "source_node_id",
        "target_node_id",
        "failed_node_id",
        "target_tier",
        "target_roles",
        "failed_node_role",
        "reroute_type",
        "baseline_path_length",
        "baseline_path_count",
        "reroute_path_length",
        "reroute_path_count",
        "hop_change",
        "target_candidates",
        "failed_node_candidates",
        "disconnecting_candidates",
        "detour_candidates",
        "equal_cost_candidates",
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
        "input_root": str(args.input_root),
        "output_root": str(args.output_root),
        "with_answer_root": str(args.output_root / WITH_ANSWER_DIR_NAME),
        "without_answer_root": str(args.output_root / WITHOUT_ANSWER_DIR_NAME),
        "splits": {},
        "seed": args.seed,
        "minimum_baseline_path_node_count": args.min_baseline_path_node_count,
        "selection_priority": ["detour", "equal_cost_failover"],
    }
    stats_rows: list[dict[str, Any]] = []

    for split in args.splits:
        input_files = iter_json_files(args.input_root, split)
        split_summary = {
            "input_files": len(input_files),
            "built_files": 0,
            "skipped_files": 0,
            "detour_files": 0,
            "equal_cost_failover_files": 0,
            "built_by_target_tier": {},
        }
        print(f"[{split}] found {len(input_files)} json files")

        for index, input_path in enumerate(input_files, start=1):
            relative_path = input_path.relative_to(args.input_root / split)
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
                min_path_node_count=args.min_baseline_path_node_count,
                indent=args.indent,
            )
            if ok:
                split_summary["built_files"] += 1
                if stats_row is not None:
                    stats_rows.append(stats_row)
                    reroute_type = stats_row["reroute_type"]
                    split_summary[f"{reroute_type}_files"] += 1
                    target_tier = stats_row["target_tier"]
                    split_summary["built_by_target_tier"][target_tier] = (
                        split_summary["built_by_target_tier"].get(target_tier, 0)
                        + 1
                    )
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
                    f"skipped={split_summary['skipped_files']}, "
                    f"detour={split_summary['detour_files']}, "
                    "equal_cost="
                    f"{split_summary['equal_cost_failover_files']}"
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
