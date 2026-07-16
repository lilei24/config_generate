#!/usr/bin/env python3
"""基于最近核心任务数据集构造单节点故障绕行任务。

默认输入是 ``nearest_core_dataset/with_answer/{train,val}``。每张输入图已经包含
一个源 AP，以及该 AP 到最近 CORE 的全部最短路径。本脚本执行以下处理：

1. 筛选节点数大于 3 的基线最短路径；
2. 从路径中间节点中选择一个故障节点，源 AP 和目标 CORE 不会被选中；
3. 从图中移除故障节点及其关联链路，重新计算源节点到同一 CORE 的全部最短路径；
4. 只保留故障后仍然可达的样本；
5. 优先选择跳数增加的 detour，找不到时使用等长的 equal_cost_failover；
6. 同时生成 with_answer 和 without_answer，两个版本除 task_answer 外完全一致。

原“最近核心”任务的 question、answer 和 metadata 会被替换，避免旧答案泄漏到新任务。
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
MIN_BASELINE_PATH_NODE_COUNT = 4
WITH_ANSWER_DIR_NAME = "with_answer"
WITHOUT_ANSWER_DIR_NAME = "without_answer"


@dataclass(frozen=True)
class NodeInformation:
    node_ids: list[str]
    node_name_by_id: dict[str, str]
    node_role_by_id: dict[str, str]
    unique_node_id_by_name: dict[str, str]
    ambiguous_node_names: set[str]


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
        help=f"最近核心有答案数据集根目录，默认: {DEFAULT_INPUT_ROOT}",
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
        "--indent",
        type=int,
        default=2,
        help="输出 JSON 缩进，默认: 2",
    )
    return parser.parse_args()


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


def get_node_information(graph: dict[str, Any]) -> NodeInformation:
    nodes = graph.get("nodes")
    if not isinstance(nodes, list):
        return NodeInformation([], {}, {}, {}, set())

    node_ids: list[str] = []
    node_name_by_id: dict[str, str] = {}
    node_role_by_id: dict[str, str] = {}
    node_ids_by_name: dict[str, list[str]] = defaultdict(list)

    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_id = node.get("id")
        if node_id is None:
            continue

        node_id_str = str(node_id)
        device = get_device(node)
        node_name = device.get("NAME")
        node_name_str = str(node_name) if node_name is not None else node_id_str
        node_ids.append(node_id_str)
        node_name_by_id[node_id_str] = node_name_str
        node_role_by_id[node_id_str] = get_node_role(node)
        node_ids_by_name[node_name_str].append(node_id_str)

    unique_node_id_by_name = {
        name: ids[0] for name, ids in node_ids_by_name.items() if len(ids) == 1
    }
    ambiguous_node_names = {
        name for name, ids in node_ids_by_name.items() if len(ids) > 1
    }
    return NodeInformation(
        node_ids=node_ids,
        node_name_by_id=node_name_by_id,
        node_role_by_id=node_role_by_id,
        unique_node_id_by_name=unique_node_id_by_name,
        ambiguous_node_names=ambiguous_node_names,
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


def extract_eligible_target_names(graph: dict[str, Any], source_name: str) -> list[str]:
    """从上游最近核心答案中提取拥有长路径的目标 CORE 名称。"""

    task_answer = graph.get("task_answer")
    if not isinstance(task_answer, dict):
        return []
    answer_paths = task_answer.get("paths")
    if not isinstance(answer_paths, list):
        return []

    target_names: set[str] = set()
    for path in answer_paths:
        if not isinstance(path, list) or len(path) < MIN_BASELINE_PATH_NODE_COUNT:
            continue
        if not all(isinstance(node_name, str) for node_name in path):
            continue
        if path[0] != source_name:
            continue
        target_names.add(path[-1])
    return sorted(target_names)


def evaluate_candidates(
    source_id: str,
    target_ids: list[str],
    adjacency: dict[str, set[str]],
    rng: random.Random,
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
        if not baseline_paths or len(baseline_paths[0]) < MIN_BASELINE_PATH_NODE_COUNT:
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
    node_name_by_id: dict[str, str],
) -> dict[str, Any]:
    named_paths = [
        [node_name_by_id.get(node_id, node_id) for node_id in path]
        for path in candidate.reroute_paths
    ]
    return {
        "connected": True,
        "path_length": len(candidate.reroute_paths[0]) - 1,
        "paths": sorted(named_paths),
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
    indent: int,
) -> tuple[bool, str, dict[str, Any] | None]:
    graph, error = load_json(input_path)
    if graph is None:
        return False, f"load-json-error: {error}", None

    source_name = graph.get("task_source_node_name")
    if not isinstance(source_name, str) or not source_name:
        return False, "missing-task-source-node-name", None

    node_info = get_node_information(graph)
    if not node_info.node_ids:
        return False, "no-valid-nodes", None
    if source_name in node_info.ambiguous_node_names:
        return False, "ambiguous-source-node-name", None
    source_id = node_info.unique_node_id_by_name.get(source_name)
    if source_id is None:
        return False, "source-node-name-not-found", None

    eligible_target_names = extract_eligible_target_names(graph, source_name)
    if not eligible_target_names:
        return False, "no-baseline-path-with-more-than-3-nodes", None

    target_ids: list[str] = []
    for target_name in eligible_target_names:
        if target_name in node_info.ambiguous_node_names:
            continue
        target_id = node_info.unique_node_id_by_name.get(target_name)
        if target_id is None:
            continue
        # 继续严格要求目标是 CORE，避免上游坏数据带入其他角色。
        if node_info.node_role_by_id.get(target_id) == "CORE":
            target_ids.append(target_id)
    if not target_ids:
        return False, "no-unique-core-target-for-eligible-path", None

    adjacency = build_adjacency(graph, set(node_info.node_ids))
    if not any(adjacency.values()):
        return False, "no-valid-links", None

    candidate, counters = evaluate_candidates(
        source_id=source_id,
        target_ids=target_ids,
        adjacency=adjacency,
        rng=rng,
    )
    if candidate is None:
        if counters["failed_node_candidates"] == 0:
            return False, "no-intermediate-node-candidate", None
        return False, "all-intermediate-node-failures-disconnect-target", None

    target_name = node_info.node_name_by_id.get(
        candidate.target_id,
        candidate.target_id,
    )
    failed_node_name = node_info.node_name_by_id.get(
        candidate.failed_node_id,
        candidate.failed_node_id,
    )

    task_graph = copy.deepcopy(graph)
    for old_task_field in (
        "task_source_node_name",
        "task_target_node_name",
        "task_failed_node_name",
        "task_question",
        "task_answer",
        "task_metadata",
    ):
        task_graph.pop(old_task_field, None)

    task_graph["task_source_node_name"] = source_name
    task_graph["task_target_node_name"] = target_name
    task_graph["task_failed_node_name"] = failed_node_name
    task_graph["task_question"] = (
        f"设备 {failed_node_name} 发生故障。请查找 {source_name} 到 {target_name} "
        "当前可用的全部最短物理路径，计算时不得经过该故障设备。"
    )
    task_graph["task_answer"] = build_task_answer(
        candidate,
        node_info.node_name_by_id,
    )
    task_graph["task_metadata"] = {
        "task_name": "node_failure_rerouting",
        "split": split,
        "source_file": input_path.name,
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
        "source_node_name": source_name,
        "target_node_name": target_name,
        "failed_node_name": failed_node_name,
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
        "source_node_name",
        "target_node_name",
        "failed_node_name",
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
        "minimum_baseline_path_node_count": MIN_BASELINE_PATH_NODE_COUNT,
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
                indent=args.indent,
            )
            if ok:
                split_summary["built_files"] += 1
                if stats_row is not None:
                    stats_rows.append(stats_row)
                    reroute_type = stats_row["reroute_type"]
                    split_summary[f"{reroute_type}_files"] += 1
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
