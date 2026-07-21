#!/usr/bin/env python3
"""直接从原始拓扑构造单节点故障绕行任务数据集。

与依赖最近目标单样本的构建器不同，本脚本遍历每张图中的全部 AP。对每个 AP
独立按照以下目标角色优先级选择其最高可达层级：

1. CORE；
2. Gateway+CORE；
3. Gateway_vRR；
4. Gateway；
5. Firewall；
6. AGG；
7. ACC。

在选定层级中查找最近目标及全部最短路径，枚举路径中间节点故障，并只保留故障
后仍可到达原目标的候选。优先输出跳数增加的 detour，其次输出等长路径切换。
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


DEFAULT_DATASET_ROOT = Path("datasets")
DEFAULT_OUTPUT_ROOT = Path("node_failure_reroute_dataset_from_raw")
DEFAULT_RANDOM_SEED = 20260715
DEFAULT_SPLITS = ("train", "val")
DEFAULT_PROGRESS_INTERVAL = 100
DEFAULT_MIN_BASELINE_PATH_NODE_COUNT = 3
DEFAULT_SAMPLES_PER_GRAPH = 3
WITH_ANSWER_DIR_NAME = "with_answer"
WITHOUT_ANSWER_DIR_NAME = "without_answer"
TARGET_ROLE_PRIORITY: tuple[tuple[str, str], ...] = (
    ("core", "CORE"),
    ("gateway_plus_core", "Gateway+CORE"),
    ("gateway_vrr", "Gateway_vRR"),
    ("gateway", "Gateway"),
    ("firewall", "Firewall"),
    ("aggregation", "AGG"),
    ("access", "ACC"),
)


@dataclass(frozen=True)
class NodeInformation:
    node_ids: list[str]
    node_role_by_id: dict[str, str]


@dataclass(frozen=True)
class RerouteCandidate:
    source_id: str
    target_id: str
    failed_node_id: str
    target_node_role: str
    failed_node_role: str
    target_priority_rank: int
    target_tier: str
    target_role: str
    baseline_paths: list[list[str]]
    reroute_paths: list[list[str]]
    reroute_type: str


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
        "--samples-per-graph",
        type=int,
        default=DEFAULT_SAMPLES_PER_GRAPH,
        help=f"每张图最多生成的去重样本数，默认: {DEFAULT_SAMPLES_PER_GRAPH}",
    )
    parser.add_argument(
        "--min-baseline-path-node-count",
        type=int,
        default=DEFAULT_MIN_BASELINE_PATH_NODE_COUNT,
        help=(
            "基线路径最少节点数，必须不小于 3，默认: "
            f"{DEFAULT_MIN_BASELINE_PATH_NODE_COUNT}"
        ),
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
    args = parser.parse_args()
    if args.samples_per_graph <= 0:
        parser.error("--samples-per-graph 必须大于 0")
    if args.min_baseline_path_node_count < 3:
        parser.error("--min-baseline-path-node-count 不能小于 3")
    if args.progress_interval < 0:
        parser.error("--progress-interval 不能小于 0")
    return args


def iter_json_files(dataset_root: Path, split: str) -> list[Path]:
    split_dir = dataset_root / split
    if not split_dir.is_dir():
        return []
    return sorted(path for path in split_dir.rglob("*.json") if path.is_file())


def load_json(path: Path) -> tuple[dict[str, Any] | None, str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as error:  # noqa: BLE001 - 坏文件需要记录并继续构造。
        return None, f"{type(error).__name__}: {error}"
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
        if not isinstance(node, dict) or node.get("id") is None:
            continue
        node_id = str(node["id"])
        if node_id in seen_node_ids:
            continue
        seen_node_ids.add(node_id)
        node_ids.append(node_id)
        node_role_by_id[node_id] = get_node_role(node)
    return NodeInformation(node_ids, node_role_by_id)


def build_adjacency(
    graph: dict[str, Any],
    node_id_set: set[str],
) -> dict[str, set[str]]:
    directed = bool(graph.get("directed", False))
    adjacency = {node_id: set() for node_id in node_id_set}
    links = graph.get("links")
    if not isinstance(links, list):
        return adjacency

    for link in links:
        if not isinstance(link, dict):
            continue
        source = link.get("source")
        target = link.get("target")
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
    return {
        node_id: {neighbor for neighbor in neighbors if neighbor != failed_node_id}
        for node_id, neighbors in adjacency.items()
        if node_id != failed_node_id
    }


def shortest_path_tree(
    adjacency: dict[str, set[str]],
    source: str,
) -> tuple[dict[str, int], dict[str, list[str]]]:
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
    return distances, parents


def restore_all_shortest_paths(
    source: str,
    target: str,
    parents: dict[str, list[str]],
) -> list[list[str]]:
    paths: list[list[str]] = []

    def backtrack(node_id: str, suffix: list[str]) -> None:
        if node_id == source:
            paths.append([source, *suffix])
            return
        for parent in sorted(parents.get(node_id, [])):
            backtrack(parent, [node_id, *suffix])

    backtrack(target, [])
    return sorted(paths)


def all_shortest_node_paths(
    adjacency: dict[str, set[str]],
    source: str,
    target: str,
) -> list[list[str]]:
    if source == target:
        return [[source]]
    if source not in adjacency or target not in adjacency:
        return []
    distances, parents = shortest_path_tree(adjacency, source)
    if target not in distances:
        return []
    return restore_all_shortest_paths(source, target, parents)


def select_nearest_targets_for_ap(
    source_id: str,
    node_role_by_id: dict[str, str],
    adjacency: dict[str, set[str]],
) -> tuple[
    int | None,
    str | None,
    str | None,
    list[str],
    dict[str, int],
    dict[str, list[str]],
]:
    """为单个 AP 选择其最高可达目标层级和该层级内的最近目标。"""

    distances, parents = shortest_path_tree(adjacency, source_id)
    for priority_rank, (tier_name, target_role) in enumerate(
        TARGET_ROLE_PRIORITY,
        start=1,
    ):
        reachable_targets = [
            node_id
            for node_id, role in node_role_by_id.items()
            if role == target_role and node_id in distances
        ]
        if not reachable_targets:
            continue
        minimum_distance = min(distances[node_id] for node_id in reachable_targets)
        nearest_targets = sorted(
            node_id
            for node_id in reachable_targets
            if distances[node_id] == minimum_distance
        )
        return (
            priority_rank,
            tier_name,
            target_role,
            nearest_targets,
            distances,
            parents,
        )
    return None, None, None, [], distances, parents


def collect_reroute_candidates(
    graph: dict[str, Any],
    min_path_node_count: int,
) -> tuple[list[RerouteCandidate], dict[str, int], str]:
    node_info = get_node_information(graph)
    if not node_info.node_ids:
        return [], {}, "no-valid-nodes"
    ap_node_ids = sorted(
        node_id
        for node_id in node_info.node_ids
        if node_info.node_role_by_id.get(node_id) == "AP"
    )
    if not ap_node_ids:
        return [], {}, "no-ap-role-node"

    supported_roles = {role for _, role in TARGET_ROLE_PRIORITY}
    if not any(
        role in supported_roles for role in node_info.node_role_by_id.values()
    ):
        return [], {}, "no-supported-target-role-node"

    adjacency = build_adjacency(graph, set(node_info.node_ids))
    if not any(adjacency.values()):
        return [], {}, "no-valid-links"

    candidates_by_key: dict[tuple[str, str, str], RerouteCandidate] = {}
    counters = {
        "ap_nodes": len(ap_node_ids),
        "aps_with_reachable_target_tier": 0,
        "aps_with_eligible_baseline": 0,
        "target_candidates": 0,
        "failed_node_candidates": 0,
        "disconnecting_candidates": 0,
        "detour_candidates": 0,
        "equal_cost_candidates": 0,
    }

    for source_id in ap_node_ids:
        (
            target_priority_rank,
            target_tier,
            target_role,
            nearest_target_ids,
            distances,
            parents,
        ) = select_nearest_targets_for_ap(
            source_id,
            node_info.node_role_by_id,
            adjacency,
        )
        if (
            target_priority_rank is None
            or target_tier is None
            or target_role is None
        ):
            continue
        counters["aps_with_reachable_target_tier"] += 1
        counters["target_candidates"] += len(nearest_target_ids)
        ap_has_eligible_baseline = False

        for target_id in nearest_target_ids:
            if distances[target_id] + 1 < min_path_node_count:
                continue
            baseline_paths = restore_all_shortest_paths(
                source_id,
                target_id,
                parents,
            )
            if not baseline_paths:
                continue
            ap_has_eligible_baseline = True
            failed_node_ids = sorted(
                {
                    node_id
                    for path in baseline_paths
                    for node_id in path[1:-1]
                }
            )
            for failed_node_id in failed_node_ids:
                counters["failed_node_candidates"] += 1
                reroute_adjacency = remove_node_from_adjacency(
                    adjacency,
                    failed_node_id,
                )
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
                    "detour"
                    if reroute_length > baseline_length
                    else "equal_cost_failover"
                )
                candidate = RerouteCandidate(
                    source_id=source_id,
                    target_id=target_id,
                    failed_node_id=failed_node_id,
                    target_node_role=node_info.node_role_by_id.get(target_id, ""),
                    failed_node_role=node_info.node_role_by_id.get(
                        failed_node_id,
                        "",
                    ),
                    target_priority_rank=target_priority_rank,
                    target_tier=target_tier,
                    target_role=target_role,
                    baseline_paths=baseline_paths,
                    reroute_paths=reroute_paths,
                    reroute_type=reroute_type,
                )
                candidates_by_key[(source_id, target_id, failed_node_id)] = candidate
        if ap_has_eligible_baseline:
            counters["aps_with_eligible_baseline"] += 1

    candidates = list(candidates_by_key.values())
    counters["detour_candidates"] = sum(
        candidate.reroute_type == "detour" for candidate in candidates
    )
    counters["equal_cost_candidates"] = sum(
        candidate.reroute_type == "equal_cost_failover"
        for candidate in candidates
    )
    if not candidates:
        if counters["aps_with_eligible_baseline"] == 0:
            return [], counters, "no-ap-with-eligible-baseline-path"
        return [], counters, "all-intermediate-node-failures-disconnect-target"
    return candidates, counters, ""


def select_candidates(
    candidates: list[RerouteCandidate],
    samples_per_graph: int,
    rng: random.Random,
) -> list[RerouteCandidate]:
    detours = [candidate for candidate in candidates if candidate.reroute_type == "detour"]
    equal_cost = [
        candidate
        for candidate in candidates
        if candidate.reroute_type == "equal_cost_failover"
    ]
    rng.shuffle(detours)
    rng.shuffle(equal_cost)
    return (detours + equal_cost)[:samples_per_graph]


def output_relative_path(relative_input_path: Path, sample_index: int) -> Path:
    return relative_input_path.with_name(
        f"{relative_input_path.stem}__reroute_{sample_index:03d}"
        f"{relative_input_path.suffix}"
    )


def remove_previous_graph_outputs(
    output_root: Path,
    split: str,
    relative_input_path: Path,
) -> None:
    """删除同一原图上次生成的编号样本，避免减少样本数后残留旧文件。"""

    prefix = f"{relative_input_path.stem}__reroute_"
    suffix = relative_input_path.suffix
    for version_dir in (WITH_ANSWER_DIR_NAME, WITHOUT_ANSWER_DIR_NAME):
        parent = output_root / version_dir / split / relative_input_path.parent
        if not parent.is_dir():
            continue
        for path in parent.iterdir():
            if (
                path.is_file()
                and path.name.startswith(prefix)
                and path.name.endswith(suffix)
            ):
                path.unlink()


def build_task_graph(
    graph: dict[str, Any],
    candidate: RerouteCandidate,
    split: str,
    source_file: str,
) -> dict[str, Any]:
    task_graph = copy.deepcopy(graph)
    for field in list(task_graph):
        if field.startswith("task_"):
            task_graph.pop(field)

    task_graph["task_source_node_id"] = candidate.source_id
    task_graph["task_target_node_id"] = candidate.target_id
    task_graph["task_failed_node_id"] = candidate.failed_node_id
    task_graph["task_question"] = (
        f"节点 ID {candidate.failed_node_id} 发生故障。请查找节点 ID "
        f"{candidate.source_id} 到节点 ID {candidate.target_id} 当前可用的全部"
        "最短物理路径，计算时不得经过该故障节点。请输出最短跳数和全部"
        "最短路径，路径中的节点使用节点 ID。"
    )
    task_graph["task_answer"] = {
        "path_length": len(candidate.reroute_paths[0]) - 1,
        "paths": sorted(candidate.reroute_paths),
    }
    task_graph["task_metadata"] = {
        "task_name": "node_failure_rerouting",
        "split": split,
        "source_file": source_file,
        "target_priority_rank": candidate.target_priority_rank,
        "target_tier": candidate.target_tier,
        "target_role": candidate.target_role,
        "target_roles": [candidate.target_role],
        "construction": "enumerate_all_aps_from_raw_topology",
    }
    return task_graph


def write_json(path: Path, data: dict[str, Any], indent: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=indent) + "\n",
        encoding="utf-8",
    )


def append_issue(output_root: Path, issue: dict[str, Any]) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    with (output_root / "build_issues.jsonl").open("a", encoding="utf-8") as file:
        file.write(json.dumps(issue, ensure_ascii=False) + "\n")


def candidate_stats_row(
    input_path: Path,
    output_with_answer: Path,
    output_without_answer: Path,
    split: str,
    candidate: RerouteCandidate,
    sample_index: int,
) -> dict[str, Any]:
    baseline_length = len(candidate.baseline_paths[0]) - 1
    reroute_length = len(candidate.reroute_paths[0]) - 1
    return {
        "split": split,
        "source_file": str(input_path),
        "sample_index": sample_index,
        "output_file_with_answer": str(output_with_answer),
        "output_file_without_answer": str(output_without_answer),
        "source_node_id": candidate.source_id,
        "target_node_id": candidate.target_id,
        "failed_node_id": candidate.failed_node_id,
        "target_node_role": candidate.target_node_role,
        "failed_node_role": candidate.failed_node_role,
        "target_priority_rank": candidate.target_priority_rank,
        "target_tier": candidate.target_tier,
        "target_role": candidate.target_role,
        "target_roles": candidate.target_role,
        "reroute_type": candidate.reroute_type,
        "baseline_path_length": baseline_length,
        "baseline_path_count": len(candidate.baseline_paths),
        "reroute_path_length": reroute_length,
        "reroute_path_count": len(candidate.reroute_paths),
        "hop_change": reroute_length - baseline_length,
    }


def write_stats_csv(output_root: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "split",
        "source_file",
        "sample_index",
        "output_file_with_answer",
        "output_file_without_answer",
        "source_node_id",
        "target_node_id",
        "failed_node_id",
        "target_node_role",
        "failed_node_role",
        "target_priority_rank",
        "target_tier",
        "target_role",
        "target_roles",
        "reroute_type",
        "baseline_path_length",
        "baseline_path_count",
        "reroute_path_length",
        "reroute_path_count",
        "hop_change",
    ]
    with (output_root / "node_failure_reroute_stats.csv").open(
        "w",
        encoding="utf-8",
        newline="",
    ) as file:
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
        "seed": args.seed,
        "samples_per_graph": args.samples_per_graph,
        "minimum_baseline_path_node_count": args.min_baseline_path_node_count,
        "target_role_priority": [
            {"rank": rank, "tier": tier_name, "role": role}
            for rank, (tier_name, role) in enumerate(
                TARGET_ROLE_PRIORITY,
                start=1,
            )
        ],
        "selection_priority": ["detour", "equal_cost_failover"],
        "splits": {},
    }
    stats_rows: list[dict[str, Any]] = []

    for split in args.splits:
        input_files = iter_json_files(args.dataset_root, split)
        split_summary: dict[str, Any] = {
            "input_files": len(input_files),
            "graphs_with_samples": 0,
            "skipped_graphs": 0,
            "generated_samples": 0,
            "detour_samples": 0,
            "equal_cost_failover_samples": 0,
            "generated_by_target_tier": {},
        }
        print(f"[{split}] found {len(input_files)} json files")

        for file_index, input_path in enumerate(input_files, start=1):
            relative_input = input_path.relative_to(args.dataset_root / split)
            remove_previous_graph_outputs(
                args.output_root,
                split,
                relative_input,
            )
            graph, error = load_json(input_path)
            if graph is None:
                split_summary["skipped_graphs"] += 1
                append_issue(
                    args.output_root,
                    {"split": split, "file": str(input_path), "issue": error},
                )
                continue

            candidates, counters, reason = collect_reroute_candidates(
                graph,
                args.min_baseline_path_node_count,
            )
            selected = select_candidates(candidates, args.samples_per_graph, rng)
            if not selected:
                split_summary["skipped_graphs"] += 1
                append_issue(
                    args.output_root,
                    {
                        "split": split,
                        "file": str(input_path),
                        "issue": reason,
                        "counters": counters,
                    },
                )
            else:
                split_summary["graphs_with_samples"] += 1
                for sample_index, candidate in enumerate(selected, start=1):
                    relative_output = output_relative_path(relative_input, sample_index)
                    output_with_answer = (
                        args.output_root
                        / WITH_ANSWER_DIR_NAME
                        / split
                        / relative_output
                    )
                    output_without_answer = (
                        args.output_root
                        / WITHOUT_ANSWER_DIR_NAME
                        / split
                        / relative_output
                    )
                    task_graph = build_task_graph(
                        graph,
                        candidate,
                        split,
                        str(relative_input),
                    )
                    write_json(output_with_answer, task_graph, args.indent)
                    task_graph_without_answer = copy.deepcopy(task_graph)
                    task_graph_without_answer.pop("task_answer", None)
                    write_json(
                        output_without_answer,
                        task_graph_without_answer,
                        args.indent,
                    )
                    stats_rows.append(
                        candidate_stats_row(
                            input_path,
                            output_with_answer,
                            output_without_answer,
                            split,
                            candidate,
                            sample_index,
                        )
                    )
                    split_summary["generated_samples"] += 1
                    split_summary[f"{candidate.reroute_type}_samples"] += 1
                    tier_counts = split_summary["generated_by_target_tier"]
                    tier_counts[candidate.target_tier] = (
                        tier_counts.get(candidate.target_tier, 0) + 1
                    )

            if args.progress_interval > 0 and (
                file_index % args.progress_interval == 0
                or file_index == len(input_files)
            ):
                print(
                    f"[{split}] processed {file_index}/{len(input_files)}, "
                    f"graphs={split_summary['graphs_with_samples']}, "
                    f"samples={split_summary['generated_samples']}, "
                    f"skipped={split_summary['skipped_graphs']}"
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
