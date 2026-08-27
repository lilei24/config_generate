#!/usr/bin/env python3
"""构造节点故障后哪些 AP 到指定上游目标的路径受到影响的数据集。"""

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
DEFAULT_OUTPUT_ROOT = Path("node_failure_ap_impact_dataset")
DEFAULT_RANDOM_SEED = 20260723
DEFAULT_SPLITS = ("train", "val")
DEFAULT_PROGRESS_INTERVAL = 50
DEFAULT_SAMPLES_PER_GRAPH = 3

WITH_ANSWER_DIR_NAME = "with_answer"
WITHOUT_ANSWER_DIR_NAME = "without_answer"
STATS_FILE = "node_failure_ap_impact_stats.csv"
SUMMARY_FILE = "build_summary.json"
ISSUE_FILE = "build_issues.jsonl"

TARGET_ROLE_PRIORITY: tuple[tuple[str, str], ...] = (
    ("core", "CORE"),
    ("gateway_plus_core", "Gateway+CORE"),
    ("gateway_vrr", "Gateway_vRR"),
    ("gateway", "Gateway"),
    ("firewall", "Firewall"),
    ("aggregation", "AGG"),
    ("access", "ACC"),
)

IMPACT_LEVEL_ORDER = ("small", "medium", "large")

QUESTION_TEMPLATE = """节点 ID {failed_node_id} 发生故障，指定上游目标节点为节点 ID {target_node_id}。

请找出所有受到影响的 AP 节点。如果某个 AP 到指定上游目标节点的最短路径比故障前更长，或者故障后无法到达该目标节点，则认为该 AP 受到影响。

请严格按照以下 JSON Schema 输出：
{{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "impacted_ap_ids"
  ],
  "properties": {{
    "impacted_ap_ids": {{
      "type": "array",
      "description": "所有受影响 AP 的节点 ID",
      "items": {{
        "type": "string"
      }}
    }}
  }}
}}

只输出 JSON，不要输出解释、Markdown 或代码块。

输出示例如下：
{{
  "impacted_ap_ids": [
    "AP_NODE_1",
    "AP_NODE_2"
  ]
}}"""


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
class ImpactCandidate:
    target_node_id: str
    failed_node_id: str
    impacted_ap_ids: tuple[str, ...]
    impact_level: str


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
        "--samples-per-graph",
        type=int,
        default=DEFAULT_SAMPLES_PER_GRAPH,
        help=(
            "每张图最多生成的故障任务数；按 small、medium、large "
            "各选一个，最大有效值为 3，默认: %(default)s"
        ),
    )
    parser.add_argument(
        "--progress-interval",
        type=int,
        default=DEFAULT_PROGRESS_INTERVAL,
        help="每处理 N 个文件打印进度，0 表示关闭，默认: %(default)s",
    )
    parser.add_argument("--indent", type=int, default=2)
    args = parser.parse_args()
    if not 1 <= args.samples_per_graph <= len(IMPACT_LEVEL_ORDER):
        parser.error("--samples-per-graph 必须在 1 到 3 之间")
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
        name_by_id[node_id] = scalar_text(device.get("NAME")) or node_id
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


def shortest_distance(
    adjacency: dict[str, set[str]],
    source: str,
    target: str,
    blocked_node_id: str | None = None,
) -> int | None:
    """计算避开指定故障节点时的最短跳数，不可达时返回 None。"""

    if source == blocked_node_id or target == blocked_node_id:
        return None
    if source not in adjacency or target not in adjacency:
        return None
    if source == target:
        return 0

    distances = {source: 0}
    queue: deque[str] = deque([source])
    while queue:
        current = queue.popleft()
        next_distance = distances[current] + 1
        for neighbor in adjacency.get(current, set()):
            if neighbor == blocked_node_id or neighbor in distances:
                continue
            if neighbor == target:
                return next_distance
            distances[neighbor] = next_distance
            queue.append(neighbor)
    return None


def connected_components(
    adjacency: dict[str, set[str]],
    blocked_node_id: str | None = None,
) -> dict[str, int]:
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
        target_ids = frozenset(
            node_id
            for node_id in reachable
            if node_info.role_by_id.get(node_id) == role
        )
        if target_ids:
            return BaselineTarget(rank, tier, role, target_ids)
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


def choose_target_node(
    baselines: dict[str, BaselineTarget],
    rng: random.Random,
) -> str | None:
    """从各 AP 按原优先级选出的正常上游目标中固定选择一个节点。"""

    target_node_ids = sorted(
        {
            target_node_id
            for baseline in baselines.values()
            for target_node_id in baseline.target_node_ids
        }
    )
    return rng.choice(target_node_ids) if target_node_ids else None


def build_baseline_distances(
    adjacency: dict[str, set[str]],
    baselines: dict[str, BaselineTarget],
    target_node_id: str,
) -> dict[str, int]:
    """记录以指定节点为正常上游目标的 AP 在故障前的最短距离。"""

    distances: dict[str, int] = {}
    for ap_id, baseline in sorted(baselines.items()):
        if target_node_id not in baseline.target_node_ids:
            continue
        distance = shortest_distance(adjacency, ap_id, target_node_id)
        if distance is not None:
            distances[ap_id] = distance
    return distances


def impacted_aps_after_failure(
    adjacency: dict[str, set[str]],
    baseline_distances: dict[str, int],
    target_node_id: str,
    failed_node_id: str,
) -> tuple[str, ...]:
    impacted: list[str] = []
    for ap_id, baseline_distance in sorted(baseline_distances.items()):
        failure_distance = shortest_distance(
            adjacency,
            ap_id,
            target_node_id,
            blocked_node_id=failed_node_id,
        )
        if failure_distance is None or failure_distance > baseline_distance:
            impacted.append(ap_id)
    return tuple(impacted)


def classify_impact(affected_ap_count: int) -> str:
    if affected_ap_count == 0:
        return "no_impact"
    if affected_ap_count <= 5:
        return "small"
    if affected_ap_count <= 20:
        return "medium"
    return "large"


def collect_candidates(
    node_info: NodeInformation,
    adjacency: dict[str, set[str]],
    target_node_id: str,
    baseline_distances: dict[str, int],
) -> list[ImpactCandidate]:
    candidates: list[ImpactCandidate] = []
    for failed_node_id in node_info.node_ids:
        if (
            node_info.role_by_id.get(failed_node_id) == "AP"
            or failed_node_id == target_node_id
        ):
            continue
        impacted_ap_ids = impacted_aps_after_failure(
            adjacency,
            baseline_distances,
            target_node_id,
            failed_node_id,
        )
        if not impacted_ap_ids:
            continue
        candidates.append(
            ImpactCandidate(
                target_node_id=target_node_id,
                failed_node_id=failed_node_id,
                impacted_ap_ids=impacted_ap_ids,
                impact_level=classify_impact(len(impacted_ap_ids)),
            )
        )
    return candidates


def select_candidates(
    candidates: list[ImpactCandidate],
    samples_per_graph: int,
    rng: random.Random,
) -> list[ImpactCandidate]:
    """从 small、medium、large 三个影响等级中各固定随机选择一个。"""

    by_level: dict[str, list[ImpactCandidate]] = {
        level: [] for level in IMPACT_LEVEL_ORDER
    }
    for candidate in candidates:
        by_level[candidate.impact_level].append(candidate)
    for items in by_level.values():
        rng.shuffle(items)

    selected: list[ImpactCandidate] = []
    for level in IMPACT_LEVEL_ORDER:
        if by_level[level] and len(selected) < samples_per_graph:
            selected.append(by_level[level].pop())
    return selected


def build_task_graph(
    graph: dict[str, Any],
    candidate: ImpactCandidate,
    split: str,
    source_file: str,
) -> dict[str, Any]:
    task_graph = copy.deepcopy(graph)
    for key in list(task_graph):
        if key.startswith("task_"):
            task_graph.pop(key)

    task_graph["task_failed_node_id"] = candidate.failed_node_id
    task_graph["task_target_node_id"] = candidate.target_node_id
    task_graph["task_target_role_priority"] = [
        role for _, role in TARGET_ROLE_PRIORITY
    ]
    task_graph["task_question"] = QUESTION_TEMPLATE.format(
        failed_node_id=candidate.failed_node_id,
        target_node_id=candidate.target_node_id,
    )
    task_graph["task_answer"] = {
        "impacted_ap_ids": list(candidate.impacted_ap_ids)
    }
    task_graph["task_metadata"] = {
        "task_name": "single_node_failure_ap_connectivity_impact",
        "split": split,
        "source_file": source_file,
        "fault_assumption": "specified_non_ap_node_failure",
        "normal_upstream_policy": "highest_priority_reachable_exact_role",
        "impact_rule": "shortest_path_increased_or_target_unreachable",
    }
    return task_graph


def output_relative_path(relative_input: Path, sample_index: int) -> Path:
    return relative_input.with_name(
        f"{relative_input.stem}__ap_impact_{sample_index:03d}.json"
    )


def remove_previous_outputs(
    output_root: Path,
    split: str,
    relative_input: Path,
) -> None:
    prefix = f"{relative_input.stem}__ap_impact_"
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
    with (output_root / ISSUE_FILE).open("a", encoding="utf-8") as file:
        file.write(json.dumps(issue, ensure_ascii=False) + "\n")


def make_stats_row(
    split: str,
    relative_input: Path,
    output_with_answer: Path,
    output_without_answer: Path,
    sample_index: int,
    candidate: ImpactCandidate,
    node_info: NodeInformation,
) -> dict[str, Any]:
    failed_node_id = candidate.failed_node_id
    return {
        "split": split,
        "source_file": str(relative_input),
        "sample_index": sample_index,
        "output_file_with_answer": str(output_with_answer),
        "output_file_without_answer": str(output_without_answer),
        "failed_node_id": failed_node_id,
        "failed_device_name": node_info.name_by_id.get(failed_node_id, failed_node_id),
        "failed_device_type": node_info.type_by_id.get(failed_node_id, ""),
        "failed_device_role": node_info.role_by_id.get(failed_node_id, ""),
        "target_node_id": candidate.target_node_id,
        "target_device_name": node_info.name_by_id.get(
            candidate.target_node_id,
            candidate.target_node_id,
        ),
        "target_device_type": node_info.type_by_id.get(candidate.target_node_id, ""),
        "target_device_role": node_info.role_by_id.get(candidate.target_node_id, ""),
        "impact_level": candidate.impact_level,
        "impacted_ap_count": len(candidate.impacted_ap_ids),
        "impacted_ap_ids": json.dumps(
            candidate.impacted_ap_ids,
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
        "failed_node_id",
        "failed_device_name",
        "failed_device_type",
        "failed_device_role",
        "target_node_id",
        "target_device_name",
        "target_device_type",
        "target_device_role",
        "impact_level",
        "impacted_ap_count",
        "impacted_ap_ids",
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
        "samples_per_graph": args.samples_per_graph,
        "impact_levels": {
            "small": "1-5 impacted APs",
            "medium": "6-20 impacted APs",
            "large": ">20 impacted APs",
        },
        "target_role_priority": [
            {"rank": rank, "tier": tier, "role": role}
            for rank, (tier, role) in enumerate(TARGET_ROLE_PRIORITY, start=1)
        ],
        "sampled_impact_levels": list(IMPACT_LEVEL_ORDER),
        "selection_strategy": "one_each_from_small_medium_large_without_fill",
        "splits": {},
    }

    for split in args.splits:
        input_files = iter_json_files(dataset_root, split)
        split_summary: dict[str, Any] = {
            "input_files": len(input_files),
            "graphs_with_samples": 0,
            "skipped_graphs": 0,
            "generated_samples": 0,
            "generated_by_impact_level": {
                level: 0 for level in IMPACT_LEVEL_ORDER
            },
            "skip_reasons": {},
        }
        skip_reasons: Counter[str] = Counter()
        print(f"[{split}] found {len(input_files)} json files", flush=True)

        for file_index, input_path in enumerate(input_files, start=1):
            relative_input = input_path.relative_to(dataset_root / split)
            remove_previous_outputs(output_root, split, relative_input)
            graph, error = load_json(input_path)
            reason = ""
            candidates: list[ImpactCandidate] = []
            node_info = NodeInformation([], {}, {}, {})

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
                        baselines = build_ap_baselines(graph, adjacency, node_info)
                        if not baselines:
                            reason = "no-ap-with-reachable-supported-upstream-role"
                        else:
                            target_node_id = choose_target_node(baselines, rng)
                            if target_node_id is None:
                                reason = "no-selectable-upstream-target-node"
                            else:
                                baseline_distances = build_baseline_distances(
                                    adjacency,
                                    baselines,
                                    target_node_id,
                                )
                                candidates = collect_candidates(
                                    node_info,
                                    adjacency,
                                    target_node_id,
                                    baseline_distances,
                                )
                                if not candidates:
                                    reason = "no-eligible-non-ap-failure-candidate"

            selected = select_candidates(
                candidates,
                args.samples_per_graph,
                rng,
            )
            if not selected:
                split_summary["skipped_graphs"] += 1
                skip_reasons[reason or "no-selected-candidate"] += 1
                append_issue(
                    output_root,
                    {
                        "split": split,
                        "file": str(relative_input),
                        "issue": reason or "no-selected-candidate",
                        "detail": error,
                    },
                )
            else:
                assert graph is not None
                split_summary["graphs_with_samples"] += 1
                for sample_index, candidate in enumerate(selected, start=1):
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
                        candidate,
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
                            candidate,
                            node_info,
                        )
                    )
                    split_summary["generated_samples"] += 1
                    split_summary["generated_by_impact_level"][
                        candidate.impact_level
                    ] += 1

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
