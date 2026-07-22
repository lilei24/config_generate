#!/usr/bin/env python3
"""从原始拓扑构造“根据失联 AP 集合反推单节点故障”任务数据集。

对每个 AP，先按照固定角色优先级确定其正常状态下最高优先级的可达上游角色，
再依次模拟每个非 AP 节点故障。产生完全相同失联 AP 集合的故障节点会被归入
同一答案，因此数据集能够同时覆盖唯一根因和多候选歧义根因场景。
"""

from __future__ import annotations

import argparse
import copy
import csv
import json
import random
from collections import Counter, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_DATASET_ROOT = Path("datasets")
DEFAULT_OUTPUT_ROOT = Path("node_failure_localization_dataset")
DEFAULT_RANDOM_SEED = 20260722
DEFAULT_SPLITS = ("train", "val")
DEFAULT_PROGRESS_INTERVAL = 50
DEFAULT_MIN_AFFECTED_APS = 2
DEFAULT_SAMPLES_PER_GRAPH = 3

WITH_ANSWER_DIR_NAME = "with_answer"
WITHOUT_ANSWER_DIR_NAME = "without_answer"
STATS_FILE = "node_failure_localization_stats.csv"
SUMMARY_FILE = "build_summary.json"
ISSUE_FILE = "build_issues.jsonl"

# 每一级只包含一个精确 DEVICEROLE，复合角色不会被拆分匹配。
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
    role_by_id: dict[str, str]
    type_by_id: dict[str, str]
    name_by_id: dict[str, str]


@dataclass(frozen=True)
class BaselineTarget:
    target_priority_rank: int
    target_tier: str
    target_role: str
    target_node_ids: frozenset[str]


@dataclass(frozen=True)
class ImpactGroup:
    affected_ap_ids: tuple[str, ...]
    candidate_fault_node_ids: tuple[str, ...]

    @property
    def localization_type(self) -> str:
        return "unique_root_cause" if len(self.candidate_fault_node_ids) == 1 else "ambiguous_root_cause"


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
        "--min-affected-aps",
        type=int,
        default=DEFAULT_MIN_AFFECTED_APS,
        help="一个故障现象至少包含的失联 AP 数量，默认: %(default)s",
    )
    parser.add_argument(
        "--samples-per-graph",
        type=int,
        default=DEFAULT_SAMPLES_PER_GRAPH,
        help="每张图最多生成的不同故障现象数量，默认: %(default)s",
    )
    parser.add_argument(
        "--progress-interval",
        type=int,
        default=DEFAULT_PROGRESS_INTERVAL,
        help="每处理 N 个文件打印进度，0 表示关闭，默认: %(default)s",
    )
    parser.add_argument("--indent", type=int, default=2)
    args = parser.parse_args()

    if args.min_affected_aps < 1:
        parser.error("--min-affected-aps 必须大于等于 1")
    if args.samples_per_graph < 1:
        parser.error("--samples-per-graph 必须大于等于 1")
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


def load_json(path: Path) -> tuple[dict[str, Any] | None, str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as error:  # noqa: BLE001 - 单个坏文件不能中断构造。
        return None, f"{type(error).__name__}: {error}"
    if not isinstance(data, dict):
        return None, f"top-level JSON type is {type(data).__name__}, expected object"
    return data, ""


def get_device(node: dict[str, Any]) -> dict[str, Any]:
    device = node.get("device")
    if not isinstance(device, dict):
        device = node.get("devices")
    return device if isinstance(device, dict) else {}


def scalar_text(value: Any) -> str:
    return str(value) if value is not None else ""


def get_node_information(graph: dict[str, Any]) -> NodeInformation:
    nodes = graph.get("nodes")
    if not isinstance(nodes, list):
        return NodeInformation([], {}, {}, {})

    node_ids: list[str] = []
    role_by_id: dict[str, str] = {}
    type_by_id: dict[str, str] = {}
    name_by_id: dict[str, str] = {}
    seen: set[str] = set()
    for node in nodes:
        if not isinstance(node, dict) or node.get("id") is None:
            continue
        node_id = str(node["id"])
        if node_id in seen:
            continue
        seen.add(node_id)
        node_ids.append(node_id)

        topology_node = node.get("topologyNode")
        role = topology_node.get("DEVICEROLE") if isinstance(topology_node, dict) else None
        device = get_device(node)
        role_by_id[node_id] = scalar_text(role)
        type_by_id[node_id] = scalar_text(device.get("TYPE"))
        name = device.get("NAME")
        name_by_id[node_id] = scalar_text(name) or node_id
    return NodeInformation(node_ids, role_by_id, type_by_id, name_by_id)


def build_adjacency(
    graph: dict[str, Any],
    node_ids: set[str],
) -> dict[str, set[str]]:
    adjacency = {node_id: set() for node_id in node_ids}
    directed = bool(graph.get("directed", False))
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
        if source_id not in node_ids or target_id not in node_ids:
            continue
        adjacency[source_id].add(target_id)
        if not directed:
            adjacency[target_id].add(source_id)
    return adjacency


def reachable_nodes(
    adjacency: dict[str, set[str]],
    source: str,
    blocked_node_id: str | None = None,
) -> set[str]:
    if source == blocked_node_id or source not in adjacency:
        return set()
    visited = {source}
    queue: deque[str] = deque([source])
    while queue:
        current = queue.popleft()
        for neighbor in adjacency.get(current, set()):
            if neighbor == blocked_node_id or neighbor in visited:
                continue
            visited.add(neighbor)
            queue.append(neighbor)
    return visited


def connected_components(
    adjacency: dict[str, set[str]],
    blocked_node_id: str | None = None,
) -> dict[str, int]:
    """为无向图计算连通分量；删除候选节点时不修改原始邻接表。"""

    component_by_node: dict[str, int] = {}
    component_id = 0
    for source in sorted(adjacency):
        if source == blocked_node_id or source in component_by_node:
            continue
        component_id += 1
        component_by_node[source] = component_id
        queue: deque[str] = deque([source])
        while queue:
            current = queue.popleft()
            for neighbor in adjacency.get(current, set()):
                if neighbor == blocked_node_id or neighbor in component_by_node:
                    continue
                component_by_node[neighbor] = component_id
                queue.append(neighbor)
    return component_by_node


def select_baseline_target(
    reachable: set[str],
    node_info: NodeInformation,
) -> BaselineTarget | None:
    for rank, (tier, role) in enumerate(TARGET_ROLE_PRIORITY, start=1):
        targets = frozenset(
            node_id
            for node_id in reachable
            if node_info.role_by_id.get(node_id) == role
        )
        if targets:
            return BaselineTarget(rank, tier, role, targets)
    return None


def build_ap_baselines(
    graph: dict[str, Any],
    adjacency: dict[str, set[str]],
    node_info: NodeInformation,
) -> dict[str, BaselineTarget]:
    ap_ids = [
        node_id
        for node_id in node_info.node_ids
        if node_info.role_by_id.get(node_id) == "AP"
    ]
    baselines: dict[str, BaselineTarget] = {}
    if bool(graph.get("directed", False)):
        for ap_id in ap_ids:
            baseline = select_baseline_target(
                reachable_nodes(adjacency, ap_id),
                node_info,
            )
            if baseline is not None:
                baselines[ap_id] = baseline
        return baselines

    component_by_node = connected_components(adjacency)
    nodes_by_component: dict[int, set[str]] = {}
    for node_id, component_id in component_by_node.items():
        nodes_by_component.setdefault(component_id, set()).add(node_id)
    for ap_id in ap_ids:
        component_id = component_by_node.get(ap_id)
        if component_id is None:
            continue
        baseline = select_baseline_target(
            nodes_by_component[component_id],
            node_info,
        )
        if baseline is not None:
            baselines[ap_id] = baseline
    return baselines


def affected_aps_for_failure(
    graph: dict[str, Any],
    adjacency: dict[str, set[str]],
    baselines: dict[str, BaselineTarget],
    failed_node_id: str,
) -> tuple[str, ...]:
    affected: list[str] = []
    directed = bool(graph.get("directed", False))
    component_by_node = None if directed else connected_components(adjacency, failed_node_id)

    for ap_id, baseline in sorted(baselines.items()):
        remaining_targets = baseline.target_node_ids - {failed_node_id}
        if not remaining_targets:
            affected.append(ap_id)
            continue

        if directed:
            reachable = reachable_nodes(adjacency, ap_id, failed_node_id)
            still_reachable = bool(remaining_targets & reachable)
        else:
            assert component_by_node is not None
            ap_component = component_by_node.get(ap_id)
            still_reachable = ap_component is not None and any(
                component_by_node.get(target_id) == ap_component
                for target_id in remaining_targets
            )
        if not still_reachable:
            affected.append(ap_id)
    return tuple(affected)


def collect_impact_groups(
    graph: dict[str, Any],
    node_info: NodeInformation,
    adjacency: dict[str, set[str]],
    baselines: dict[str, BaselineTarget],
    min_affected_aps: int,
) -> list[ImpactGroup]:
    candidates_by_signature: dict[tuple[str, ...], list[str]] = {}
    for failed_node_id in node_info.node_ids:
        if node_info.role_by_id.get(failed_node_id) == "AP":
            continue
        affected_ap_ids = affected_aps_for_failure(
            graph,
            adjacency,
            baselines,
            failed_node_id,
        )
        if len(affected_ap_ids) < min_affected_aps:
            continue
        candidates_by_signature.setdefault(affected_ap_ids, []).append(failed_node_id)

    return [
        ImpactGroup(signature, tuple(sorted(candidate_ids)))
        for signature, candidate_ids in sorted(candidates_by_signature.items())
    ]


def select_impact_groups(
    groups: list[ImpactGroup],
    samples_per_graph: int,
    rng: random.Random,
) -> list[ImpactGroup]:
    """优先覆盖一条歧义样本和一条唯一根因样本，其余随机补齐。"""

    ambiguous = [group for group in groups if len(group.candidate_fault_node_ids) > 1]
    unique = [group for group in groups if len(group.candidate_fault_node_ids) == 1]
    rng.shuffle(ambiguous)
    rng.shuffle(unique)

    selected: list[ImpactGroup] = []
    if ambiguous:
        selected.append(ambiguous.pop())
    if unique and len(selected) < samples_per_graph:
        selected.append(unique.pop())

    remaining = ambiguous + unique
    rng.shuffle(remaining)
    selected.extend(remaining[: max(0, samples_per_graph - len(selected))])
    return selected


def build_candidate_details(
    group: ImpactGroup,
    node_info: NodeInformation,
) -> list[dict[str, Any]]:
    return [
        {
            "node_id": node_id,
            "device_name": node_info.name_by_id.get(node_id, node_id),
            "device_type": node_info.type_by_id.get(node_id, ""),
            "device_role": node_info.role_by_id.get(node_id, ""),
            "simulated_disconnected_ap_ids": list(group.affected_ap_ids),
        }
        for node_id in group.candidate_fault_node_ids
    ]


def build_task_graph(
    graph: dict[str, Any],
    group: ImpactGroup,
    node_info: NodeInformation,
    split: str,
    source_file: str,
) -> dict[str, Any]:
    task_graph = copy.deepcopy(graph)
    for key in list(task_graph):
        if key.startswith("task_"):
            task_graph.pop(key)

    affected_text = "、".join(group.affected_ap_ids)
    role_priority = [role for _, role in TARGET_ROLE_PRIORITY]
    task_graph["task_observed_disconnected_ap_ids"] = list(group.affected_ap_ids)
    task_graph["task_target_role_priority"] = role_priority
    task_graph["task_question"] = (
        f"网络监控发现 AP 节点 {affected_text} 无法访问其故障前按照角色优先级 "
        f"{' > '.join(role_priority)} 确定的上游目标角色，其他正常状态下能够找到"
        "上游目标的 AP 均正常。假设当前恰有一个非 AP 节点发生故障、AP 节点"
        "自身没有故障且观测到的失联 AP 集合完整。请找出所有能够精确解释该"
        "现象的候选故障节点。只输出 JSON，包含 candidate_fault_node_ids 和 "
        "candidate_details；candidate_details 中给出 node_id、device_name、"
        "device_type、device_role 和 simulated_disconnected_ap_ids。"
    )
    task_graph["task_answer"] = {
        "observed_disconnected_ap_ids": list(group.affected_ap_ids),
        "candidate_fault_node_ids": list(group.candidate_fault_node_ids),
        "candidate_details": build_candidate_details(group, node_info),
    }
    task_graph["task_metadata"] = {
        "task_name": "single_node_failure_localization_from_disconnected_aps",
        "split": split,
        "source_file": source_file,
        "fault_assumption": "exactly_one_non_ap_node_failure",
        "observation_assumption": "complete_disconnected_ap_set",
        "normal_upstream_policy": "highest_priority_reachable_exact_role",
    }
    return task_graph


def output_relative_path(relative_input: Path, sample_index: int) -> Path:
    return relative_input.with_name(
        f"{relative_input.stem}__localization_{sample_index:03d}.json"
    )


def remove_previous_outputs(
    output_root: Path,
    split: str,
    relative_input: Path,
) -> None:
    prefix = f"{relative_input.stem}__localization_"
    for answer_dir in (WITH_ANSWER_DIR_NAME, WITHOUT_ANSWER_DIR_NAME):
        parent = output_root / answer_dir / split / relative_input.parent
        if not parent.is_dir():
            continue
        for path in parent.glob(f"{prefix}*.json"):
            path.unlink()


def write_json(path: Path, data: dict[str, Any], indent: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=indent) + "\n",
        encoding="utf-8",
    )


def append_issue(output_root: Path, issue: dict[str, Any]) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    with (output_root / ISSUE_FILE).open("a", encoding="utf-8") as file:
        file.write(json.dumps(issue, ensure_ascii=False) + "\n")


def make_stats_row(
    split: str,
    relative_input: Path,
    output_with_answer: Path,
    output_without_answer: Path,
    sample_index: int,
    group: ImpactGroup,
    node_info: NodeInformation,
) -> dict[str, Any]:
    role_counts = Counter(
        node_info.role_by_id.get(node_id, "")
        for node_id in group.candidate_fault_node_ids
    )
    return {
        "split": split,
        "source_file": str(relative_input),
        "sample_index": sample_index,
        "output_file_with_answer": str(output_with_answer),
        "output_file_without_answer": str(output_without_answer),
        "localization_type": group.localization_type,
        "affected_ap_count": len(group.affected_ap_ids),
        "candidate_fault_node_count": len(group.candidate_fault_node_ids),
        "affected_ap_ids": json.dumps(group.affected_ap_ids, ensure_ascii=False),
        "candidate_fault_node_ids": json.dumps(
            group.candidate_fault_node_ids,
            ensure_ascii=False,
        ),
        "candidate_role_counts": json.dumps(
            dict(sorted(role_counts.items())),
            ensure_ascii=False,
        ),
    }


def write_stats(output_root: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "split",
        "source_file",
        "sample_index",
        "output_file_with_answer",
        "output_file_without_answer",
        "localization_type",
        "affected_ap_count",
        "candidate_fault_node_count",
        "affected_ap_ids",
        "candidate_fault_node_ids",
        "candidate_role_counts",
    ]
    with (output_root / STATS_FILE).open(
        "w", encoding="utf-8-sig", newline=""
    ) as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def build_dataset(args: argparse.Namespace) -> dict[str, Any]:
    dataset_root = args.dataset_root.resolve()
    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    issue_path = output_root / ISSUE_FILE
    if issue_path.exists():
        issue_path.unlink()

    rng = random.Random(args.seed)
    stats_rows: list[dict[str, Any]] = []
    summary: dict[str, Any] = {
        "dataset_root": str(dataset_root),
        "output_root": str(output_root),
        "with_answer_root": str(output_root / WITH_ANSWER_DIR_NAME),
        "without_answer_root": str(output_root / WITHOUT_ANSWER_DIR_NAME),
        "seed": args.seed,
        "minimum_affected_aps": args.min_affected_aps,
        "samples_per_graph": args.samples_per_graph,
        "target_role_priority": [
            {"rank": rank, "tier": tier, "role": role}
            for rank, (tier, role) in enumerate(TARGET_ROLE_PRIORITY, start=1)
        ],
        "selection_strategy": "prefer_one_ambiguous_then_one_unique_then_random",
        "splits": {},
    }

    for split in args.splits:
        input_files = iter_json_files(dataset_root, split)
        split_summary: dict[str, Any] = {
            "input_files": len(input_files),
            "graphs_with_samples": 0,
            "skipped_graphs": 0,
            "generated_samples": 0,
            "unique_root_cause_samples": 0,
            "ambiguous_root_cause_samples": 0,
            "skip_reasons": {},
        }
        skip_reasons: Counter[str] = Counter()
        print(f"[{split}] found {len(input_files)} json files", flush=True)

        for file_index, input_path in enumerate(input_files, start=1):
            relative_input = input_path.relative_to(dataset_root / split)
            remove_previous_outputs(output_root, split, relative_input)
            graph, error = load_json(input_path)
            reason = ""
            groups: list[ImpactGroup] = []
            node_info = NodeInformation([], {}, {}, {})
            baseline_ap_count = 0

            if graph is None:
                reason = "load-json-error"
            else:
                node_info = get_node_information(graph)
                ap_count = sum(
                    node_info.role_by_id.get(node_id) == "AP"
                    for node_id in node_info.node_ids
                )
                if ap_count == 0:
                    reason = "no-ap-role-node"
                else:
                    adjacency = build_adjacency(graph, set(node_info.node_ids))
                    if not any(adjacency.values()):
                        reason = "no-valid-links"
                    else:
                        baselines = build_ap_baselines(
                            graph,
                            adjacency,
                            node_info,
                        )
                        baseline_ap_count = len(baselines)
                        if not baselines:
                            reason = "no-ap-with-reachable-supported-upstream-role"
                        else:
                            groups = collect_impact_groups(
                                graph,
                                node_info,
                                adjacency,
                                baselines,
                                args.min_affected_aps,
                            )
                            if not groups:
                                reason = "no-failure-with-enough-disconnected-aps"

            selected = select_impact_groups(
                groups,
                args.samples_per_graph,
                rng,
            )
            if not selected:
                split_summary["skipped_graphs"] += 1
                skip_reasons[reason or "no-selected-impact-group"] += 1
                append_issue(
                    output_root,
                    {
                        "split": split,
                        "file": str(relative_input),
                        "issue": reason or "no-selected-impact-group",
                        "detail": error,
                        "baseline_ap_count": baseline_ap_count,
                    },
                )
            else:
                assert graph is not None
                split_summary["graphs_with_samples"] += 1
                for sample_index, group in enumerate(selected, start=1):
                    relative_output = output_relative_path(relative_input, sample_index)
                    with_answer_path = (
                        output_root
                        / WITH_ANSWER_DIR_NAME
                        / split
                        / relative_output
                    )
                    without_answer_path = (
                        output_root
                        / WITHOUT_ANSWER_DIR_NAME
                        / split
                        / relative_output
                    )
                    task_graph = build_task_graph(
                        graph,
                        group,
                        node_info,
                        split,
                        str(relative_input),
                    )
                    write_json(with_answer_path, task_graph, args.indent)
                    hidden_graph = copy.deepcopy(task_graph)
                    hidden_graph.pop("task_answer", None)
                    write_json(without_answer_path, hidden_graph, args.indent)

                    stats_rows.append(
                        make_stats_row(
                            split,
                            relative_input,
                            with_answer_path,
                            without_answer_path,
                            sample_index,
                            group,
                            node_info,
                        )
                    )
                    split_summary["generated_samples"] += 1
                    split_summary[f"{group.localization_type}_samples"] += 1

            if args.progress_interval > 0 and (
                file_index % args.progress_interval == 0
                or file_index == len(input_files)
            ):
                print(
                    f"[{split}] processed {file_index}/{len(input_files)}, "
                    f"graphs={split_summary['graphs_with_samples']}, "
                    f"samples={split_summary['generated_samples']}, "
                    f"skipped={split_summary['skipped_graphs']}",
                    flush=True,
                )

        split_summary["skip_reasons"] = dict(sorted(skip_reasons.items()))
        summary["splits"][split] = split_summary

    write_stats(output_root, stats_rows)
    write_json(output_root / SUMMARY_FILE, summary, indent=2)
    return summary


def main() -> None:
    args = parse_args()
    summary = build_dataset(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
