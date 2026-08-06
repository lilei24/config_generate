#!/usr/bin/env python3
"""从原始拓扑构造单链路故障绕行任务数据集。

对每个 AP 按业务角色优先级选择最高可达层级中的最近目标，枚举正常最短
路径上的链路故障，并将候选划分为等价切换、绕行和失联三类。默认每张图
按照 1:1:1 的配额分别抽取等价切换、绕行和失联样本；只有至少存在一种
可切换或可绕行样本时，才允许附带失联样本。输出内容对应的 with_answer
和 without_answer 数据集。
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
DEFAULT_OUTPUT_ROOT = Path("link_failure_reroute_dataset")
DEFAULT_RANDOM_SEED = 20260805
DEFAULT_SPLITS = ("train", "val")
DEFAULT_PROGRESS_INTERVAL = 100
DEFAULT_EQUAL_COST_SAMPLES_PER_GRAPH = 1
DEFAULT_DETOUR_SAMPLES_PER_GRAPH = 1
DEFAULT_DISCONNECTED_SAMPLES_PER_GRAPH = 1

WITH_ANSWER_DIR = "with_answer"
WITHOUT_ANSWER_DIR = "without_answer"
STATS_FILE = "link_failure_reroute_stats.csv"
SUMMARY_FILE = "build_summary.json"
ISSUES_FILE = "build_issues.jsonl"

TARGET_ROLE_PRIORITY: tuple[tuple[str, str], ...] = (
    ("core", "CORE"),
    ("gateway_plus_core", "Gateway+CORE"),
    ("gateway_vrr", "Gateway_vRR"),
    ("gateway", "Gateway"),
    ("firewall", "Firewall"),
    ("aggregation", "AGG"),
    ("access", "ACC"),
)
RESULT_TYPE_ORDER = (
    "equal_cost_failover",
    "detour",
    "disconnected",
)


@dataclass(frozen=True)
class LinkRecord:
    index: int
    source_id: str
    target_id: str
    left_port: Any
    right_port: Any


@dataclass(frozen=True)
class LinkFailureCandidate:
    source_id: str
    target_id: str
    target_priority_rank: int
    target_tier: str
    target_role: str
    failed_link: LinkRecord
    baseline_path_length: int
    paths: tuple[tuple[str, ...], ...]
    result_type: str

    @property
    def connected(self) -> bool:
        return bool(self.paths)

    @property
    def path_length(self) -> int | None:
        return len(self.paths[0]) - 1 if self.paths else None


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
        help="任务数据集输出目录，默认: %(default)s",
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
        "--equal-cost-samples-per-graph",
        type=int,
        default=DEFAULT_EQUAL_COST_SAMPLES_PER_GRAPH,
        help="每张图最多抽取的等价切换样本数，默认: %(default)s",
    )
    parser.add_argument(
        "--detour-samples-per-graph",
        type=int,
        default=DEFAULT_DETOUR_SAMPLES_PER_GRAPH,
        help="每张图最多抽取的绕行样本数，默认: %(default)s",
    )
    parser.add_argument(
        "--disconnected-samples-per-graph",
        type=int,
        default=DEFAULT_DISCONNECTED_SAMPLES_PER_GRAPH,
        help="每张图最多抽取的失联样本数，默认: %(default)s",
    )
    parser.add_argument(
        "--progress-interval",
        type=int,
        default=DEFAULT_PROGRESS_INTERVAL,
        help="每处理 N 个文件打印进度，0 表示关闭，默认: %(default)s",
    )
    parser.add_argument("--indent", type=int, default=2)
    args = parser.parse_args()
    quotas = (
        args.equal_cost_samples_per_graph,
        args.detour_samples_per_graph,
        args.disconnected_samples_per_graph,
    )
    if any(quota < 0 for quota in quotas):
        parser.error("三类样本配额不能小于 0")
    if sum(quotas) == 0:
        parser.error("三类样本配额不能全部为 0")
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


def get_node_role(node: dict[str, Any]) -> str:
    topology = node.get("topologyNode")
    if not isinstance(topology, dict):
        return ""
    role = topology.get("DEVICEROLE")
    return str(role) if role is not None else ""


def collect_nodes(graph: dict[str, Any]) -> tuple[list[str], dict[str, str]]:
    nodes = graph.get("nodes")
    if not isinstance(nodes, list):
        return [], {}
    node_ids: list[str] = []
    role_by_id: dict[str, str] = {}
    for node in nodes:
        if not isinstance(node, dict) or node.get("id") is None:
            continue
        node_id = str(node["id"])
        if node_id in role_by_id:
            continue
        node_ids.append(node_id)
        role_by_id[node_id] = get_node_role(node)
    return node_ids, role_by_id


def collect_links(
    graph: dict[str, Any],
    node_ids: set[str],
) -> list[LinkRecord]:
    links = graph.get("links")
    if not isinstance(links, list):
        return []
    records: list[LinkRecord] = []
    for index, item in enumerate(links):
        if not isinstance(item, dict):
            continue
        source = item.get("source")
        target = item.get("target")
        if source is None or target is None:
            continue
        source_id = str(source)
        target_id = str(target)
        if (
            source_id not in node_ids
            or target_id not in node_ids
            or source_id == target_id
        ):
            continue
        detail = item.get("link")
        if not isinstance(detail, dict):
            detail = {}
        records.append(
            LinkRecord(
                index=index,
                source_id=source_id,
                target_id=target_id,
                left_port=detail.get("LEFTPORT"),
                right_port=detail.get("RIGHTPORT"),
            )
        )
    return records


def build_adjacency(
    node_ids: set[str],
    links: list[LinkRecord],
    directed: bool,
    excluded_link_index: int | None = None,
) -> dict[str, set[str]]:
    """按链路索引排除单条边，重复端点的其他物理链路仍然有效。"""

    adjacency = {node_id: set() for node_id in node_ids}
    for link in links:
        if link.index == excluded_link_index:
            continue
        adjacency[link.source_id].add(link.target_id)
        if not directed:
            adjacency[link.target_id].add(link.source_id)
    return adjacency


def shortest_path_tree(
    adjacency: dict[str, set[str]],
    source_id: str,
) -> tuple[dict[str, int], dict[str, list[str]]]:
    distances = {source_id: 0}
    parents: dict[str, list[str]] = defaultdict(list)
    queue: deque[str] = deque([source_id])
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
    source_id: str,
    target_id: str,
    parents: dict[str, list[str]],
) -> list[list[str]]:
    paths: list[list[str]] = []

    def backtrack(node_id: str, suffix: list[str]) -> None:
        if node_id == source_id:
            paths.append([source_id, *suffix])
            return
        for parent_id in sorted(parents.get(node_id, [])):
            backtrack(parent_id, [node_id, *suffix])

    backtrack(target_id, [])
    return sorted(paths)


def all_shortest_paths(
    adjacency: dict[str, set[str]],
    source_id: str,
    target_id: str,
) -> list[list[str]]:
    if source_id not in adjacency or target_id not in adjacency:
        return []
    distances, parents = shortest_path_tree(adjacency, source_id)
    if target_id not in distances:
        return []
    return restore_all_shortest_paths(source_id, target_id, parents)


def select_nearest_targets(
    source_id: str,
    role_by_id: dict[str, str],
    adjacency: dict[str, set[str]],
) -> tuple[int | None, str | None, str | None, list[str], dict[str, int], dict[str, list[str]]]:
    distances, parents = shortest_path_tree(adjacency, source_id)
    for rank, (tier, role) in enumerate(TARGET_ROLE_PRIORITY, start=1):
        reachable = [
            node_id
            for node_id, node_role in role_by_id.items()
            if node_role == role and node_id in distances and node_id != source_id
        ]
        if not reachable:
            continue
        minimum = min(distances[node_id] for node_id in reachable)
        nearest = sorted(
            node_id for node_id in reachable if distances[node_id] == minimum
        )
        return rank, tier, role, nearest, distances, parents
    return None, None, None, [], distances, parents


def path_edge_pairs(path: list[str], directed: bool) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for left, right in zip(path, path[1:]):
        pairs.add((left, right) if directed else tuple(sorted((left, right))))
    return pairs


def link_pair(link: LinkRecord, directed: bool) -> tuple[str, str]:
    if directed:
        return link.source_id, link.target_id
    return tuple(sorted((link.source_id, link.target_id)))


def collect_candidates(
    graph: dict[str, Any],
) -> tuple[list[LinkFailureCandidate], dict[str, int], str]:
    node_ids, role_by_id = collect_nodes(graph)
    if not node_ids:
        return [], {}, "no-valid-nodes"
    aps = sorted(node_id for node_id in node_ids if role_by_id[node_id] == "AP")
    if not aps:
        return [], {}, "no-ap-role-node"

    links = collect_links(graph, set(node_ids))
    if not links:
        return [], {}, "no-valid-links"
    directed = bool(graph.get("directed", False))
    adjacency = build_adjacency(set(node_ids), links, directed)
    counters = Counter(
        {
            "ap_nodes": len(aps),
            "valid_links": len(links),
            "aps_with_targets": 0,
            "baseline_target_pairs": 0,
            "failed_link_candidates": 0,
        }
    )
    candidates: dict[tuple[str, str, int], LinkFailureCandidate] = {}

    for source_id in aps:
        rank, tier, role, targets, distances, parents = select_nearest_targets(
            source_id,
            role_by_id,
            adjacency,
        )
        if rank is None or tier is None or role is None:
            continue
        counters["aps_with_targets"] += 1
        for target_id in targets:
            baseline_paths = restore_all_shortest_paths(
                source_id,
                target_id,
                parents,
            )
            if not baseline_paths:
                continue
            counters["baseline_target_pairs"] += 1
            baseline_length = distances[target_id]
            baseline_pairs = set().union(
                *(path_edge_pairs(path, directed) for path in baseline_paths)
            )
            failed_links = [
                link for link in links if link_pair(link, directed) in baseline_pairs
            ]
            for failed_link in failed_links:
                counters["failed_link_candidates"] += 1
                failed_adjacency = build_adjacency(
                    set(node_ids),
                    links,
                    directed,
                    excluded_link_index=failed_link.index,
                )
                reroute_paths = all_shortest_paths(
                    failed_adjacency,
                    source_id,
                    target_id,
                )
                if not reroute_paths:
                    result_type = "disconnected"
                elif len(reroute_paths[0]) - 1 > baseline_length:
                    result_type = "detour"
                else:
                    result_type = "equal_cost_failover"
                candidates[(source_id, target_id, failed_link.index)] = (
                    LinkFailureCandidate(
                        source_id=source_id,
                        target_id=target_id,
                        target_priority_rank=rank,
                        target_tier=tier,
                        target_role=role,
                        failed_link=failed_link,
                        baseline_path_length=baseline_length,
                        paths=tuple(tuple(path) for path in reroute_paths),
                        result_type=result_type,
                    )
                )
                counters[f"{result_type}_candidates"] += 1

    if not candidates:
        if not counters["aps_with_targets"]:
            return [], dict(counters), "no-ap-can-reach-supported-target"
        return [], dict(counters), "no-baseline-path-link-candidate"
    return list(candidates.values()), dict(counters), ""


def select_candidates(
    candidates: list[LinkFailureCandidate],
    quotas: dict[str, int],
    rng: random.Random,
) -> list[LinkFailureCandidate]:
    by_type: dict[str, list[LinkFailureCandidate]] = defaultdict(list)
    for candidate in candidates:
        by_type[candidate.result_type].append(candidate)
    selected: list[LinkFailureCandidate] = []
    for result_type in RESULT_TYPE_ORDER[:2]:
        values = by_type[result_type]
        rng.shuffle(values)
        selected.extend(values[: quotas[result_type]])
    if selected:
        disconnected = by_type["disconnected"]
        rng.shuffle(disconnected)
        selected.extend(disconnected[: quotas["disconnected"]])
    return selected


def failed_link_payload(link: LinkRecord) -> dict[str, Any]:
    return {
        "link_index": link.index,
        "source_node_id": link.source_id,
        "target_node_id": link.target_id,
        "LEFTPORT": link.left_port,
        "RIGHTPORT": link.right_port,
    }


def build_task_graph(
    graph: dict[str, Any],
    candidate: LinkFailureCandidate,
    split: str,
    source_file: str,
) -> dict[str, Any]:
    task_graph = copy.deepcopy(graph)
    for key in list(task_graph):
        if key.startswith("task_"):
            task_graph.pop(key)

    failed_link = candidate.failed_link
    task_graph["task_source_node_id"] = candidate.source_id
    task_graph["task_target_node_id"] = candidate.target_id
    task_graph["task_failed_link"] = failed_link_payload(failed_link)
    task_graph["task_question"] = f"""链路索引 {failed_link.index} 发生故障，该链路连接节点 ID {failed_link.source_id} 和节点 ID {failed_link.target_id}。请判断节点 ID {candidate.source_id} 到节点 ID {candidate.target_id} 在不经过该故障链路时是否仍然可达。

如果可达，请输出故障后的最短跳数和全部最短物理路径；如果不可达，path_length 使用 null，paths 使用空数组。路径中的节点使用节点 ID。只输出包含 connected、path_length、paths 的 JSON。

输出格式示例 1（故障后仍然连通）：
{{
  "connected": true,
  "path_length": 3,
  "paths": [
    ["NODE_A", "NODE_B", "NODE_C", "NODE_D"]
  ]
}}

输出格式示例 2（故障后不连通）：
{{
  "connected": false,
  "path_length": null,
  "paths": []
}}"""
    task_graph["task_answer"] = {
        "connected": candidate.connected,
        "path_length": candidate.path_length,
        "paths": [list(path) for path in candidate.paths],
    }
    task_graph["task_metadata"] = {
        "task_name": "single_link_failure_rerouting",
        "split": split,
        "source_file": source_file,
        "target_priority_rank": candidate.target_priority_rank,
        "target_tier": candidate.target_tier,
        "target_role": candidate.target_role,
        "construction": "enumerate_baseline_shortest_path_links",
    }
    return task_graph


def output_relative_path(relative_input: Path, sample_index: int) -> Path:
    return relative_input.with_name(
        f"{relative_input.stem}__link_failure_{sample_index:03d}.json"
    )


def remove_stale_outputs(output_root: Path, split: str, relative_input: Path) -> None:
    prefix = f"{relative_input.stem}__link_failure_"
    for version in (WITH_ANSWER_DIR, WITHOUT_ANSWER_DIR):
        parent = output_root / version / split / relative_input.parent
        if not parent.is_dir():
            continue
        for path in parent.glob(f"{prefix}*.json"):
            path.unlink()


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
        "sample_file",
        "source_node_id",
        "target_node_id",
        "target_role",
        "failed_link_index",
        "failed_link_source",
        "failed_link_target",
        "result_type",
        "baseline_path_length",
        "path_length",
        "path_count",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def build_dataset(args: argparse.Namespace) -> dict[str, Any]:
    rng = random.Random(args.seed)
    selection_quotas = {
        "equal_cost_failover": args.equal_cost_samples_per_graph,
        "detour": args.detour_samples_per_graph,
        "disconnected": args.disconnected_samples_per_graph,
    }
    args.output_root.mkdir(parents=True, exist_ok=True)
    issue_path = args.output_root / ISSUES_FILE
    if issue_path.exists():
        issue_path.unlink()
    stats_rows: list[dict[str, Any]] = []
    summary: dict[str, Any] = {
        "dataset_root": str(args.dataset_root),
        "output_root": str(args.output_root),
        "seed": args.seed,
        "samples_per_graph": sum(selection_quotas.values()),
        "selection_quotas": selection_quotas,
        "disconnected_requires_recoverable_sample": True,
        "selection_types": list(RESULT_TYPE_ORDER),
        "target_role_priority": [role for _, role in TARGET_ROLE_PRIORITY],
        "splits": {},
    }

    for split in args.splits:
        files = iter_json_files(args.dataset_root, split)
        split_summary: dict[str, Any] = {
            "input_files": len(files),
            "graphs_with_samples": 0,
            "skipped_graphs": 0,
            "generated_samples": 0,
            "equal_cost_failover_samples": 0,
            "detour_samples": 0,
            "disconnected_samples": 0,
        }
        print(f"[{split}] found {len(files)} json files", flush=True)
        for file_index, source_path in enumerate(files, start=1):
            relative_input = source_path.relative_to(args.dataset_root / split)
            remove_stale_outputs(args.output_root, split, relative_input)
            graph, error = load_graph(source_path)
            if graph is None:
                candidates: list[LinkFailureCandidate] = []
                counters: dict[str, int] = {}
                reason = error
            else:
                candidates, counters, reason = collect_candidates(graph)
            selected = select_candidates(candidates, selection_quotas, rng)
            if candidates and not selected and not reason:
                reason = "only-disconnected-candidates-excluded"
            if graph is None or not selected:
                split_summary["skipped_graphs"] += 1
                append_issue(
                    issue_path,
                    {
                        "split": split,
                        "source_file": str(relative_input),
                        "issue": reason,
                        "counters": counters,
                    },
                )
            else:
                split_summary["graphs_with_samples"] += 1
                for sample_index, candidate in enumerate(selected, start=1):
                    relative_output = output_relative_path(relative_input, sample_index)
                    with_answer_path = (
                        args.output_root / WITH_ANSWER_DIR / split / relative_output
                    )
                    without_answer_path = (
                        args.output_root / WITHOUT_ANSWER_DIR / split / relative_output
                    )
                    task_graph = build_task_graph(
                        graph,
                        candidate,
                        split,
                        str(relative_input),
                    )
                    write_json(with_answer_path, task_graph, args.indent)
                    hidden_graph = copy.deepcopy(task_graph)
                    hidden_graph.pop("task_answer", None)
                    write_json(without_answer_path, hidden_graph, args.indent)
                    stats_rows.append(
                        {
                            "split": split,
                            "source_file": str(relative_input),
                            "sample_file": str(relative_output),
                            "source_node_id": candidate.source_id,
                            "target_node_id": candidate.target_id,
                            "target_role": candidate.target_role,
                            "failed_link_index": candidate.failed_link.index,
                            "failed_link_source": candidate.failed_link.source_id,
                            "failed_link_target": candidate.failed_link.target_id,
                            "result_type": candidate.result_type,
                            "baseline_path_length": candidate.baseline_path_length,
                            "path_length": candidate.path_length,
                            "path_count": len(candidate.paths),
                        }
                    )
                    split_summary["generated_samples"] += 1
                    split_summary[f"{candidate.result_type}_samples"] += 1

            if args.progress_interval > 0 and (
                file_index % args.progress_interval == 0 or file_index == len(files)
            ):
                print(
                    f"[{split}] processed {file_index}/{len(files)}, "
                    f"graphs={split_summary['graphs_with_samples']}, "
                    f"samples={split_summary['generated_samples']}, "
                    f"skipped={split_summary['skipped_graphs']}",
                    flush=True,
                )
        summary["splits"][split] = split_summary

    write_stats(args.output_root / STATS_FILE, stats_rows)
    write_json(args.output_root / SUMMARY_FILE, summary)
    return summary


def main() -> None:
    summary = build_dataset(parse_args())
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
