#!/usr/bin/env python3
"""构造“上行节点路径查询”任务数据集。

输入数据集目录结构默认是：

datasets/
  train/*.json
  val/*.json

一次运行会生成两套内容一一对应的数据集：with_answer 保留标准答案，
without_answer 删除标准答案。每个输出 JSON 完整保留原始拓扑，并在顶层增加
任务源节点、自然语言问题和任务元数据。源节点严格选择 DEVICEROLE=AP 的节点。
目标角色按以下优先级回退：

1. CORE；
2. Gateway+CORE；
3. Gateway_vRR；
4. Gateway；
5. Firewall；
6. AGG；
7. ACC。

只有当前层级不存在任何可达 AP→目标组合时才回退到下一层级。选择目标层级后，
随机选择第一个能够到达该层级目标的 AP；如果多个目标距离相同，则保留到这些
目标的全部最短节点 ID 路径。答案只包含最短跳数和全部最短路径。
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
DEFAULT_OUTPUT_ROOT = Path("uplink_node_path_dataset")
DEFAULT_RANDOM_SEED = 20260715
DEFAULT_SPLITS = ("train", "val")
DEFAULT_PROGRESS_INTERVAL = 100
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


def get_node_role(node: dict[str, Any]) -> str:
    topology_node = node.get("topologyNode")
    if not isinstance(topology_node, dict):
        return ""
    role = topology_node.get("DEVICEROLE")
    return str(role) if role is not None else ""


def get_node_information(
    graph: dict[str, Any],
) -> tuple[list[str], dict[str, str]]:
    nodes = graph.get("nodes")
    if not isinstance(nodes, list):
        return [], {}

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

    return node_ids, node_role_by_id


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


def shortest_path_tree(
    adjacency: dict[str, set[str]],
    source: str,
) -> tuple[dict[str, int], dict[str, list[str]]]:
    """用 BFS 计算源节点到所有可达节点的距离及最短路径前驱。"""

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
    """根据 BFS 前驱关系恢复 source 到 target 的全部最短路径。"""

    paths: list[list[str]] = []

    def backtrack(node_id: str, suffix: list[str]) -> None:
        if node_id == source:
            paths.append([source, *suffix])
            return
        for parent in sorted(parents.get(node_id, [])):
            backtrack(parent, [node_id, *suffix])

    backtrack(target, [])
    return sorted(paths)


def find_nearest_targets(
    adjacency: dict[str, set[str]],
    source: str,
    target_node_ids: list[str],
) -> tuple[list[str], list[list[str]], int | None]:
    distances, parents = shortest_path_tree(adjacency, source)
    reachable_targets = [
        node_id for node_id in target_node_ids if node_id in distances
    ]
    if not reachable_targets:
        return [], [], None

    minimum_distance = min(distances[node_id] for node_id in reachable_targets)
    nearest_targets = sorted(
        node_id
        for node_id in reachable_targets
        if distances[node_id] == minimum_distance
    )
    paths: list[list[str]] = []
    for target_node_id in nearest_targets:
        paths.extend(restore_all_shortest_paths(source, target_node_id, parents))
    return nearest_targets, sorted(paths), minimum_distance


def choose_source_and_nearest_targets(
    ap_node_ids: list[str],
    node_role_by_id: dict[str, str],
    adjacency: dict[str, set[str]],
    rng: random.Random,
) -> tuple[
    str | None,
    list[str],
    list[list[str]],
    int | None,
    str | None,
    str | None,
    int | None,
]:
    """优先选择最高目标层级，再随机选择一个可达该层级的 AP。"""

    candidates = list(ap_node_ids)
    rng.shuffle(candidates)
    for priority_rank, (tier_name, target_role) in enumerate(
        TARGET_ROLE_PRIORITY,
        start=1,
    ):
        target_node_ids = [
            node_id
            for node_id, role in node_role_by_id.items()
            if role == target_role
        ]
        if not target_node_ids:
            continue
        for source in candidates:
            nearest_targets, paths, path_length = find_nearest_targets(
                adjacency,
                source,
                target_node_ids,
            )
            if nearest_targets and paths:
                return (
                    source,
                    nearest_targets,
                    paths,
                    path_length,
                    tier_name,
                    target_role,
                    priority_rank,
                )
    return None, [], [], None, None, None, None


def build_answer(
    node_paths: list[list[str]],
    path_length: int,
) -> dict[str, Any]:
    return {
        "path_length": path_length,
        "paths": sorted(node_paths),
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

    node_ids, node_role_by_id = get_node_information(graph)
    if not node_ids:
        return False, "no-valid-nodes", None

    # 所有角色使用严格相等判断，复合角色只进入显式配置的目标层级。
    ap_node_ids = [
        node_id for node_id in node_ids if node_role_by_id.get(node_id) == "AP"
    ]
    if not ap_node_ids:
        return False, "no-ap-role-node", None
    supported_target_roles = {role for _, role in TARGET_ROLE_PRIORITY}
    if not any(role in supported_target_roles for role in node_role_by_id.values()):
        return False, "no-supported-target-role-node", None

    adjacency = build_adjacency(graph, set(node_ids))
    if not any(adjacency.values()):
        return False, "no-valid-links", None

    (
        source,
        nearest_target_ids,
        node_paths,
        path_length,
        target_tier,
        target_role,
        target_priority_rank,
    ) = choose_source_and_nearest_targets(
        ap_node_ids,
        node_role_by_id,
        adjacency,
        rng,
    )
    if (
        source is None
        or path_length is None
        or target_tier is None
        or target_role is None
        or target_priority_rank is None
    ):
        return False, "no-ap-can-reach-supported-target", None

    task_graph = copy.deepcopy(graph)
    task_graph["task_source_node_id"] = source
    task_graph["task_question"] = (
        f"请查找从 AP 节点 ID {source} 到 DEVICEROLE 为 "
        f"{target_role} 的最近设备的全部最短物理路径。"
        "请输出最短跳数和全部最短路径，路径中的节点使用节点 ID。"
    )
    task_graph["task_answer"] = build_answer(
        node_paths=node_paths,
        path_length=path_length,
    )
    task_graph["task_metadata"] = {
        "task_name": "uplink_node_path_query",
        "split": split,
        "source_file": input_path.name,
        "target_priority_rank": target_priority_rank,
        "target_tier": target_tier,
        "target_role": target_role,
        "target_roles": [target_role],
        "selection_strategy": "highest_reachable_role_tier_then_shortest_distance",
    }
    # 两个版本必须从同一个完整样本派生，避免再次随机选择源节点造成内容偏差。
    write_json(output_path_with_answer, task_graph, indent=indent)
    task_graph_without_answer = copy.deepcopy(task_graph)
    task_graph_without_answer.pop("task_answer", None)
    write_json(output_path_without_answer, task_graph_without_answer, indent=indent)

    return True, "", {
        "split": split,
        "file": str(input_path),
        "output_file_with_answer": str(output_path_with_answer),
        "output_file_without_answer": str(output_path_without_answer),
        "source_node_id": source,
        "target_priority_rank": target_priority_rank,
        "target_tier": target_tier,
        "target_role": target_role,
        "target_roles": target_role,
        "nearest_target_count": len(nearest_target_ids),
        "shortest_path_length": path_length,
        "shortest_path_count": len(node_paths),
    }


def write_stats_csv(output_root: Path, rows: list[dict[str, Any]]) -> None:
    stats_path = output_root / "nearest_target_stats.csv"
    fieldnames = [
        "split",
        "file",
        "output_file_with_answer",
        "output_file_without_answer",
        "source_node_id",
        "target_priority_rank",
        "target_tier",
        "target_role",
        "target_roles",
        "nearest_target_count",
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
        "source_role": "AP",
        "target_role_priority": [
            {"rank": rank, "tier": tier_name, "role": role}
            for rank, (tier_name, role) in enumerate(
                TARGET_ROLE_PRIORITY,
                start=1,
            )
        ],
    }
    stats_rows: list[dict[str, Any]] = []

    for split in args.splits:
        input_files = iter_json_files(args.dataset_root, split)
        split_summary = {
            "input_files": len(input_files),
            "built_files": 0,
            "skipped_files": 0,
            "built_by_target_tier": {
                tier_name: 0 for tier_name, _ in TARGET_ROLE_PRIORITY
            },
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
                indent=args.indent,
            )
            if ok:
                split_summary["built_files"] += 1
                if stats_row is not None:
                    stats_rows.append(stats_row)
                    split_summary["built_by_target_tier"][
                        stats_row["target_tier"]
                    ] += 1
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
