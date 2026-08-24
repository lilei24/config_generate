#!/usr/bin/env python3
"""验证 VLAN 约束路径任务在忽略 VLAN 时的 LSW 最短路径。"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter, deque
from pathlib import Path
from typing import Any, Optional


DEFAULT_DATASET_ROOT = Path(
    "vlan_constrained_shortest_path_dataset/with_answer"
)
DEFAULT_OUTPUT_FILE = Path("/tmp/vlan_task_unconstrained_path_validation.json")
DEFAULT_SPLIT = "all"
DEFAULT_MAX_OUTPUT_PATHS = 1000
DEFAULT_PROGRESS_INTERVAL = 100


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "dataset_root",
        nargs="?",
        type=Path,
        default=DEFAULT_DATASET_ROOT,
        help="with_answer 数据集根目录，目录下包含 train/val，默认: %(default)s",
    )
    parser.add_argument(
        "-o",
        "--output-file",
        type=Path,
        default=DEFAULT_OUTPUT_FILE,
        help="验证结果 JSON 文件，默认: %(default)s",
    )
    parser.add_argument(
        "--split",
        choices=["train", "val", "all"],
        default=DEFAULT_SPLIT,
        help="验证 train、val 或全部数据，默认: %(default)s",
    )
    parser.add_argument(
        "--max-output-paths",
        type=int,
        default=DEFAULT_MAX_OUTPUT_PATHS,
        help="每个任务最多写入的无约束路径数，默认: %(default)s",
    )
    parser.add_argument(
        "--progress-interval",
        type=int,
        default=DEFAULT_PROGRESS_INTERVAL,
        help="每处理 N 个文件打印一次进度，0 表示关闭，默认: %(default)s",
    )
    args = parser.parse_args()
    if args.max_output_paths <= 0:
        parser.error("--max-output-paths 必须大于 0")
    if args.progress_interval < 0:
        parser.error("--progress-interval 不能小于 0")
    return args


def iter_json_files(dataset_root: Path, split: str) -> list[Path]:
    split_root = dataset_root / split
    if not split_root.is_dir():
        raise FileNotFoundError(f"数据划分目录不存在: {split_root}")
    return sorted(path for path in split_root.rglob("*.json") if path.is_file())


def load_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON 顶层必须是对象，实际为 {type(value).__name__}")
    return value


def scalar_text(value: Any) -> Optional[str]:
    if value is None or isinstance(value, (dict, list, bool)):
        return None
    text = str(value).strip()
    return text or None


def node_device(node: dict[str, Any]) -> Optional[dict[str, Any]]:
    device = node.get("devices")
    if not isinstance(device, dict):
        device = node.get("device")
    return device if isinstance(device, dict) else None


def is_lsw_node(node: dict[str, Any]) -> bool:
    device = node_device(node)
    if device is None:
        return False
    device_type = scalar_text(device.get("TYPE"))
    return device_type is not None and device_type.upper() == "LSW"


def build_unconstrained_lsw_graph(
    graph: dict[str, Any],
) -> tuple[dict[str, set[str]], Counter[str]]:
    """仅按物理连接构建 LSW 无向图，不检查端口和 VLAN 配置。"""

    counters: Counter[str] = Counter()
    nodes = graph.get("nodes")
    links = graph.get("links")
    if not isinstance(nodes, list):
        raise ValueError("nodes-not-list")
    if not isinstance(links, list):
        raise ValueError("links-not-list")

    node_by_id: dict[str, dict[str, Any]] = {}
    duplicate_ids: set[str] = set()
    for node in nodes:
        if not isinstance(node, dict):
            counters["invalid-node-items"] += 1
            continue
        node_id = scalar_text(node.get("id"))
        if node_id is None:
            counters["nodes-without-id"] += 1
            continue
        if node_id in node_by_id:
            duplicate_ids.add(node_id)
            continue
        node_by_id[node_id] = node
    if duplicate_ids:
        raise ValueError(
            "duplicate-node-id: " + ", ".join(sorted(duplicate_ids))
        )

    lsw_node_ids = {
        node_id for node_id, node in node_by_id.items() if is_lsw_node(node)
    }
    adjacency = {node_id: set() for node_id in lsw_node_ids}
    counters["lsw-nodes"] = len(lsw_node_ids)
    counters["input-links"] = len(links)
    for link in links:
        if not isinstance(link, dict):
            counters["invalid-link-items"] += 1
            continue
        source = scalar_text(link.get("source"))
        target = scalar_text(link.get("target"))
        if source is None or target is None:
            counters["links-with-missing-endpoints"] += 1
            continue
        if source == target:
            counters["self-loop-links"] += 1
            continue
        if source not in node_by_id or target not in node_by_id:
            counters["links-with-unresolved-endpoints"] += 1
            continue
        if source not in lsw_node_ids or target not in lsw_node_ids:
            counters["non-lsw-to-lsw-links"] += 1
            continue
        existed = target in adjacency[source]
        adjacency[source].add(target)
        adjacency[target].add(source)
        if existed:
            counters["duplicate-lsw-edges"] += 1
        else:
            counters["lsw-unique-edges"] += 1
    return adjacency, counters


def shortest_path_tree(
    source: str,
    adjacency: dict[str, set[str]],
) -> tuple[dict[str, int], dict[str, list[str]], dict[str, int]]:
    distances = {source: 0}
    predecessors: dict[str, list[str]] = {source: []}
    path_counts = {source: 1}
    queue = deque([source])
    while queue:
        node = queue.popleft()
        next_distance = distances[node] + 1
        for neighbor in sorted(adjacency.get(node, set())):
            if neighbor not in distances:
                distances[neighbor] = next_distance
                predecessors[neighbor] = [node]
                path_counts[neighbor] = path_counts[node]
                queue.append(neighbor)
            elif distances[neighbor] == next_distance:
                predecessors[neighbor].append(node)
                path_counts[neighbor] += path_counts[node]
    return distances, predecessors, path_counts


def restore_paths(
    source: str,
    target: str,
    predecessors: dict[str, list[str]],
    limit: int,
) -> list[list[str]]:
    paths: list[tuple[str, ...]] = []
    stack: list[tuple[str, tuple[str, ...]]] = [(target, (target,))]
    while stack and len(paths) < limit:
        node, reversed_path = stack.pop()
        if node == source:
            paths.append(tuple(reversed(reversed_path)))
            continue
        for predecessor in reversed(sorted(predecessors.get(node, []))):
            stack.append((predecessor, reversed_path + (predecessor,)))
    return [list(path) for path in sorted(paths)]


def constrained_answer_length(graph: dict[str, Any]) -> int:
    answer = graph.get("task_answer")
    if not isinstance(answer, dict):
        raise ValueError("task_answer-not-object")
    value = answer.get("path_length")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("task_answer.path_length-not-nonnegative-int")
    return value


def validate_task(
    graph: dict[str, Any],
    max_output_paths: int,
) -> tuple[dict[str, Any], Counter[str]]:
    source = scalar_text(graph.get("task_source_node_id"))
    target = scalar_text(graph.get("task_target_node_id"))
    if source is None:
        raise ValueError("missing-task_source_node_id")
    if target is None:
        raise ValueError("missing-task_target_node_id")
    vlan_id = graph.get("task_vlan_id")
    if isinstance(vlan_id, bool) or not isinstance(vlan_id, int):
        raise ValueError("task_vlan_id-not-int")
    constrained_length = constrained_answer_length(graph)
    adjacency, counters = build_unconstrained_lsw_graph(graph)
    if source not in adjacency:
        raise ValueError(f"source-not-lsw-node:{source}")
    if target not in adjacency:
        raise ValueError(f"target-not-lsw-node:{target}")

    distances, predecessors, path_counts = shortest_path_tree(source, adjacency)
    if target not in distances:
        return (
            {
                "task_source_node_id": source,
                "task_target_node_id": target,
                "task_vlan_id": vlan_id,
                "vlan_constrained_path_length": constrained_length,
                "unconstrained_path_length": None,
                "hop_increase": None,
                "unconstrained_shortest_path_count": 0,
                "unconstrained_paths_truncated": False,
                "unconstrained_paths": [],
                "validation_status": "unconstrained-unreachable",
            },
            counters,
        )

    unconstrained_length = distances[target]
    unconstrained_path_count = path_counts[target]
    paths = restore_paths(
        source,
        target,
        predecessors,
        max_output_paths,
    )
    hop_increase = constrained_length - unconstrained_length
    if hop_increase > 0:
        status = "passed-constrained-longer"
    elif hop_increase == 0:
        status = "unexpected-equal-length"
    else:
        status = "invalid-constrained-shorter"
    return (
        {
            "task_source_node_id": source,
            "task_target_node_id": target,
            "task_vlan_id": vlan_id,
            "vlan_constrained_path_length": constrained_length,
            "unconstrained_path_length": unconstrained_length,
            "hop_increase": hop_increase,
            "unconstrained_shortest_path_count": unconstrained_path_count,
            "unconstrained_paths_truncated": (
                unconstrained_path_count > max_output_paths
            ),
            "unconstrained_paths": paths,
            "validation_status": status,
        },
        counters,
    )


def counter_summary(counters: Counter[str]) -> dict[str, int]:
    fixed_keys = (
        "input-files",
        "validated-files",
        "invalid-files",
        "passed-constrained-longer",
        "unexpected-equal-length",
        "invalid-constrained-shorter",
        "unconstrained-unreachable",
        "truncated-path-files",
    )
    summary = {
        key.replace("-", "_"): counters[key] for key in fixed_keys
    }
    fixed = set(fixed_keys)
    summary.update(
        {
            key.replace("-", "_"): value
            for key, value in sorted(counters.items())
            if key not in fixed and value
        }
    )
    return summary


def run(args: argparse.Namespace) -> dict[str, Any]:
    dataset_root = args.dataset_root.resolve()
    output_file = args.output_file.resolve()
    splits = ["train", "val"] if args.split == "all" else [args.split]
    records: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    total_counters: Counter[str] = Counter()
    total_hop_distribution: Counter[int] = Counter()
    by_split: dict[str, dict[str, Any]] = {}

    for split in splits:
        split_root = dataset_root / split
        files = iter_json_files(dataset_root, split)
        counters: Counter[str] = Counter()
        hop_distribution: Counter[int] = Counter()
        counters["input-files"] = len(files)
        started_at = time.time()
        for index, path in enumerate(files, start=1):
            relative_path = path.relative_to(split_root).as_posix()
            try:
                graph = load_json_object(path)
                validation, graph_counters = validate_task(
                    graph,
                    args.max_output_paths,
                )
                counters.update(graph_counters)
                counters["validated-files"] += 1
                status = validation["validation_status"]
                counters[status] += 1
                if validation["unconstrained_paths_truncated"]:
                    counters["truncated-path-files"] += 1
                hop_increase = validation["hop_increase"]
                if isinstance(hop_increase, int):
                    hop_distribution[hop_increase] += 1
                records.append(
                    {
                        "split": split,
                        "source_file": path.name,
                        "source_relative_path": relative_path,
                        **validation,
                    }
                )
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
                counters["invalid-files"] += 1
                errors.append(
                    {
                        "split": split,
                        "source_file": path.name,
                        "source_relative_path": relative_path,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )

            if args.progress_interval and (
                index % args.progress_interval == 0 or index == len(files)
            ):
                elapsed = max(time.time() - started_at, 0.001)
                speed = index / elapsed
                eta = (len(files) - index) / speed if speed else 0.0
                print(
                    f"[{split}] {index}/{len(files)}，验证通过 "
                    f"{counters['passed-constrained-longer']}，"
                    f"异常 {counters['invalid-files'] + counters['unexpected-equal-length'] + counters['invalid-constrained-shorter']}，"
                    f"预计剩余 {eta:.1f} 秒",
                    flush=True,
                )

        by_split[split] = {
            **counter_summary(counters),
            "hop_increase_distribution": {
                str(key): hop_distribution[key]
                for key in sorted(hop_distribution)
            },
        }
        total_counters.update(counters)
        total_hop_distribution.update(hop_distribution)

    result = {
        "dataset_root": str(dataset_root),
        "splits": splits,
        "validation_rule": {
            "nodes": "nodes whose devices.TYPE or device.TYPE equals LSW",
            "edges": "all non-self physical links whose endpoints are both LSW",
            "ignored_constraints": (
                "LEFTPORT, RIGHTPORT, interface-name and all VLAN configurations"
            ),
            "expected_relation": (
                "task_answer.path_length > unconstrained_path_length"
            ),
        },
        "summary": {
            **counter_summary(total_counters),
            "hop_increase_distribution": {
                str(key): total_hop_distribution[key]
                for key in sorted(total_hop_distribution)
            },
            "by_split": by_split,
        },
        "errors": errors,
        "records": records,
    }
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"验证完成，结果已写入: {output_file}")
    return result


def main() -> None:
    run(parse_args())


if __name__ == "__main__":
    main()
