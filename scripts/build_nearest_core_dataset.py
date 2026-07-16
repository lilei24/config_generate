#!/usr/bin/env python3
"""构造“查找距离接入节点最近的核心交换机”任务数据集。

输入数据集目录结构默认是：

datasets/
  train/*.json
  val/*.json

每个输出 JSON 完整保留原始拓扑，并在顶层增加任务源节点、自然语言问题、
标准答案和任务元数据。源节点严格选择 DEVICEROLE=AP 的节点，目标核心设备
严格选择 DEVICEROLE=CORE 的节点；Gateway+CORE 等复合角色不计入目标集合。

如果多个核心设备与源节点的距离相同且均为最近核心，则全部保留，并输出到
每个最近核心的全部最短节点路径。没有 AP、没有 CORE 或二者均不连通的图会被
跳过，原因写入 build_issues.jsonl。
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
DEFAULT_OUTPUT_ROOT = Path("nearest_core_dataset")
DEFAULT_RANDOM_SEED = 20260715
DEFAULT_SPLITS = ("train", "val")
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
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_id = node.get("id")
        if node_id is None:
            continue

        node_id_str = str(node_id)
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


def find_nearest_cores(
    adjacency: dict[str, set[str]],
    source: str,
    core_node_ids: list[str],
) -> tuple[list[str], list[list[str]], int | None]:
    distances, parents = shortest_path_tree(adjacency, source)
    reachable_cores = [node_id for node_id in core_node_ids if node_id in distances]
    if not reachable_cores:
        return [], [], None

    minimum_distance = min(distances[node_id] for node_id in reachable_cores)
    nearest_cores = sorted(
        node_id
        for node_id in reachable_cores
        if distances[node_id] == minimum_distance
    )
    paths: list[list[str]] = []
    for core_node_id in nearest_cores:
        paths.extend(restore_all_shortest_paths(source, core_node_id, parents))
    return nearest_cores, sorted(paths), minimum_distance


def choose_source_and_nearest_cores(
    ap_node_ids: list[str],
    core_node_ids: list[str],
    adjacency: dict[str, set[str]],
    rng: random.Random,
) -> tuple[str | None, list[str], list[list[str]], int | None]:
    """随机检查 AP 候选，选择第一个能够到达至少一个 CORE 的节点。"""

    candidates = list(ap_node_ids)
    rng.shuffle(candidates)
    for source in candidates:
        nearest_cores, paths, path_length = find_nearest_cores(
            adjacency,
            source,
            core_node_ids,
        )
        if nearest_cores and paths:
            return source, nearest_cores, paths, path_length
    return None, [], [], None


def build_answer(
    nearest_core_ids: list[str],
    node_paths: list[list[str]],
    path_length: int,
    node_name_by_id: dict[str, str],
    node_role_by_id: dict[str, str],
) -> dict[str, Any]:
    named_paths = [
        [node_name_by_id.get(node_id, node_id) for node_id in path]
        for path in node_paths
    ]
    role_paths = [
        [node_role_by_id.get(node_id, "") for node_id in path]
        for path in node_paths
    ]
    return {
        "connected": True,
        "path_length": path_length,
        "nearest_core_node_names": sorted(
            node_name_by_id.get(node_id, node_id) for node_id in nearest_core_ids
        ),
        "paths": named_paths,
        "path_role_sequences": role_paths,
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
    output_path: Path,
    split: str,
    rng: random.Random,
    indent: int,
) -> tuple[bool, str, dict[str, Any] | None]:
    graph, error = load_json(input_path)
    if graph is None:
        return False, f"load-json-error: {error}", None

    node_ids, node_name_by_id, node_role_by_id = get_node_information(graph)
    if not node_ids:
        return False, "no-valid-nodes", None

    # 角色使用严格相等判断，避免把 Gateway+CORE 当作 CORE。
    ap_node_ids = [
        node_id for node_id in node_ids if node_role_by_id.get(node_id) == "AP"
    ]
    core_node_ids = [
        node_id for node_id in node_ids if node_role_by_id.get(node_id) == "CORE"
    ]
    if not ap_node_ids:
        return False, "no-ap-role-node", None
    if not core_node_ids:
        return False, "no-core-role-node", None

    adjacency = build_adjacency(graph, set(node_ids))
    if not any(adjacency.values()):
        return False, "no-valid-links", None

    source, nearest_core_ids, node_paths, path_length = choose_source_and_nearest_cores(
        ap_node_ids,
        core_node_ids,
        adjacency,
        rng,
    )
    if source is None or path_length is None:
        return False, "no-ap-can-reach-core", None

    source_name = node_name_by_id.get(source, source)
    task_graph = copy.deepcopy(graph)
    task_graph["task_source_node_name"] = source_name
    task_graph["task_question"] = (
        f"距离 {source_name} 最近的核心交换机是什么？"
        "请输出最短距离、全部最近核心设备及对应的全部最短物理路径。"
    )
    task_graph["task_answer"] = build_answer(
        nearest_core_ids=nearest_core_ids,
        node_paths=node_paths,
        path_length=path_length,
        node_name_by_id=node_name_by_id,
        node_role_by_id=node_role_by_id,
    )
    task_graph["task_metadata"] = {
        "task_name": "find_nearest_core_nodes",
        "split": split,
        "source_file": input_path.name,
    }
    write_json(output_path, task_graph, indent=indent)

    return True, "", {
        "split": split,
        "file": str(input_path),
        "output_file": str(output_path),
        "source_node_name": source_name,
        "nearest_core_count": len(nearest_core_ids),
        "shortest_path_length": path_length,
        "shortest_path_count": len(node_paths),
    }


def write_stats_csv(output_root: Path, rows: list[dict[str, Any]]) -> None:
    stats_path = output_root / "nearest_core_stats.csv"
    fieldnames = [
        "split",
        "file",
        "output_file",
        "source_node_name",
        "nearest_core_count",
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
        "splits": {},
        "seed": args.seed,
        "source_role": "AP",
        "target_role": "CORE",
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
            output_path = args.output_root / split / relative_path
            ok, reason, stats_row = process_file(
                input_path=input_path,
                output_path=output_path,
                split=split,
                rng=rng,
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
