#!/usr/bin/env python3
"""构造两个 AP 必须经过指定 CORE 的全部最短物理路径任务数据集。

两个 AP 必须唯一归属于同一个最近 CORE。默认每张图最多选择两个强制绕行
样本和一个自然经过 CORE 的样本，并同步生成 with_answer 与 without_answer。
"""

from __future__ import annotations

import argparse
import copy
import csv
import itertools
import json
import random
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_DATASET_ROOT = Path("datasets")
DEFAULT_OUTPUT_ROOT = Path("ap_pair_via_core_path_dataset")
DEFAULT_RANDOM_SEED = 20260806
DEFAULT_SPLITS = ("train", "val")
DEFAULT_PROGRESS_INTERVAL = 100
DEFAULT_DETOUR_SAMPLES_PER_GRAPH = 2
DEFAULT_NATURAL_SAMPLES_PER_GRAPH = 1
DEFAULT_MAX_CANDIDATE_ATTEMPTS_PER_GRAPH = 500
DEFAULT_MAX_ANSWER_PATHS = 1000

WITH_ANSWER_DIR = "with_answer"
WITHOUT_ANSWER_DIR = "without_answer"
STATS_FILE = "ap_pair_via_core_path_stats.csv"
SUMMARY_FILE = "build_summary.json"
ISSUES_FILE = "build_issues.jsonl"

DETOUR = "forced_core_detour"
NATURAL = "natural_via_core"

QUESTION_TEMPLATE = """请查找 AP 节点 ID {source_ap_id} 到 AP 节点 ID {target_ap_id} 必须经过 CORE 节点 ID {required_core_id} 的全部最短物理路径。

请严格按照以下 JSON Schema 输出：
{{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "path_length",
    "paths"
  ],
  "properties": {{
    "path_length": {{
      "type": "integer",
      "description": "经过指定 CORE 节点的最短路径跳数"
    }},
    "paths": {{
      "type": "array",
      "description": "经过指定 CORE 节点的全部最短路径，路径中的节点使用节点 ID",
      "items": {{
        "type": "array",
        "items": {{
          "type": "string"
        }}
      }}
    }}
  }}
}}

请返回全部最短路径。只输出 JSON，不要输出解释、Markdown 或代码块。

输出示例如下：
{{
  "path_length": 4,
  "paths": [
    [
      "AP_NODE_1",
      "ACC_NODE_1",
      "CORE_NODE_1",
      "ACC_NODE_2",
      "AP_NODE_2"
    ],
    [
      "AP_NODE_1",
      "ACC_NODE_3",
      "CORE_NODE_1",
      "ACC_NODE_4",
      "AP_NODE_2"
    ]
  ]
}}"""


@dataclass(frozen=True)
class Candidate:
    source_ap_id: str
    target_ap_id: str
    required_core_id: str
    baseline_path_length: int
    constrained_path_length: int
    paths: tuple[tuple[str, ...], ...]
    category: str


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
        "--detour-samples-per-graph",
        type=int,
        default=DEFAULT_DETOUR_SAMPLES_PER_GRAPH,
        help="每图最多抽取的强制绕行样本数，默认: %(default)s",
    )
    parser.add_argument(
        "--natural-samples-per-graph",
        type=int,
        default=DEFAULT_NATURAL_SAMPLES_PER_GRAPH,
        help="每图最多抽取的自然经过 CORE 样本数，默认: %(default)s",
    )
    parser.add_argument(
        "--max-candidate-attempts-per-graph",
        type=int,
        default=DEFAULT_MAX_CANDIDATE_ATTEMPTS_PER_GRAPH,
        help="每图最多检查的 AP 对与 CORE 组合数，默认: %(default)s",
    )
    parser.add_argument(
        "--max-answer-paths",
        type=int,
        default=DEFAULT_MAX_ANSWER_PATHS,
        help="超过该完整答案路径数的候选会跳过，默认: %(default)s",
    )
    parser.add_argument(
        "--progress-interval",
        type=int,
        default=DEFAULT_PROGRESS_INTERVAL,
        help="每处理 N 个文件打印进度，0 表示关闭，默认: %(default)s",
    )
    parser.add_argument("--indent", type=int, default=2)
    args = parser.parse_args()
    if args.detour_samples_per_graph < 0 or args.natural_samples_per_graph < 0:
        parser.error("样本配额不能小于 0")
    if args.detour_samples_per_graph + args.natural_samples_per_graph == 0:
        parser.error("强制绕行和自然经过样本配额不能同时为 0")
    if args.max_candidate_attempts_per_graph <= 0:
        parser.error("--max-candidate-attempts-per-graph 必须大于 0")
    if args.max_answer_paths <= 0:
        parser.error("--max-answer-paths 必须大于 0")
    if args.progress_interval < 0 or args.indent < 0:
        parser.error("进度间隔和 JSON 缩进不能小于 0")
    return args


def iter_json_files(dataset_root: Path, split: str) -> list[Path]:
    split_root = dataset_root / split
    if not split_root.is_dir():
        return []
    return sorted(path for path in split_root.rglob("*.json") if path.is_file())


def load_graph(path: Path) -> tuple[dict[str, Any] | None, str]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as error:  # noqa: BLE001 - 坏文件应记录并继续。
        return None, f"{type(error).__name__}: {error}"
    if not isinstance(value, dict):
        return None, f"top-level type is {type(value).__name__}, expected object"
    return value, ""


def node_role(node: dict[str, Any]) -> str:
    topology = node.get("topologyNode")
    if not isinstance(topology, dict):
        return ""
    role = topology.get("DEVICEROLE")
    return str(role) if role is not None else ""


def collect_nodes(
    graph: dict[str, Any],
) -> tuple[list[str], dict[str, str], str]:
    nodes = graph.get("nodes")
    if not isinstance(nodes, list):
        return [], {}, "nodes-not-list"
    node_ids: list[str] = []
    role_by_id: dict[str, str] = {}
    duplicates: set[str] = set()
    for node in nodes:
        if not isinstance(node, dict) or node.get("id") is None:
            continue
        node_id = str(node["id"])
        if not node_id:
            continue
        if node_id in role_by_id:
            duplicates.add(node_id)
            continue
        node_ids.append(node_id)
        role_by_id[node_id] = node_role(node)
    if duplicates:
        return [], {}, "duplicate-node-id: " + ", ".join(sorted(duplicates))
    if not node_ids:
        return [], {}, "no-valid-node-id"
    return sorted(node_ids), role_by_id, ""


def build_adjacency(
    graph: dict[str, Any],
    node_ids: list[str],
) -> tuple[dict[str, set[str]], int, Counter[str]]:
    adjacency = {node_id: set() for node_id in node_ids}
    node_id_set = set(node_ids)
    reasons: Counter[str] = Counter()
    links = graph.get("links")
    if not isinstance(links, list):
        reasons["links-not-list"] += 1
        return adjacency, 0, reasons
    valid_links = 0
    for link in links:
        if not isinstance(link, dict):
            reasons["link-not-object"] += 1
            continue
        source = link.get("source")
        target = link.get("target")
        if source is None or target is None:
            reasons["missing-source-or-target"] += 1
            continue
        source_id = str(source)
        target_id = str(target)
        if source_id not in node_id_set or target_id not in node_id_set:
            reasons["endpoint-not-in-nodes"] += 1
            continue
        if source_id == target_id:
            reasons["self-loop"] += 1
            continue
        adjacency[source_id].add(target_id)
        adjacency[target_id].add(source_id)
        valid_links += 1
    return adjacency, valid_links, reasons


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
        for neighbor in sorted(adjacency[current]):
            if neighbor not in distances:
                distances[neighbor] = next_distance
                parents[neighbor].append(current)
                queue.append(neighbor)
            elif distances[neighbor] == next_distance:
                parents[neighbor].append(current)
    return distances, parents


def count_shortest_paths(
    source_id: str,
    target_id: str,
    distances: dict[str, int],
    parents: dict[str, list[str]],
    limit: int,
) -> int:
    if target_id not in distances:
        return 0
    counts = {source_id: 1}
    for node_id in sorted(distances, key=lambda item: (distances[item], item)):
        if node_id == source_id:
            continue
        counts[node_id] = min(
            limit + 1,
            sum(counts.get(parent, 0) for parent in parents[node_id]),
        )
    return counts.get(target_id, 0)


def restore_shortest_paths(
    source_id: str,
    target_id: str,
    parents: dict[str, list[str]],
) -> list[list[str]]:
    paths: list[list[str]] = []

    def backtrack(node_id: str, suffix: list[str]) -> None:
        if node_id == source_id:
            paths.append([source_id, *suffix])
            return
        for parent in sorted(parents.get(node_id, [])):
            backtrack(parent, [node_id, *suffix])

    backtrack(target_id, [])
    return paths


def assign_unique_nearest_cores(
    ap_ids: list[str],
    core_ids: list[str],
    core_trees: dict[str, tuple[dict[str, int], dict[str, list[str]]]],
) -> tuple[dict[str, str], int, int]:
    unique_assignments: dict[str, str] = {}
    unreachable = 0
    tied = 0
    for ap_id in ap_ids:
        distances = {
            core_id: core_trees[core_id][0][ap_id]
            for core_id in core_ids
            if ap_id in core_trees[core_id][0]
        }
        if not distances:
            unreachable += 1
            continue
        minimum = min(distances.values())
        nearest = sorted(
            core_id for core_id, distance in distances.items() if distance == minimum
        )
        if len(nearest) != 1:
            tied += 1
            continue
        unique_assignments[ap_id] = nearest[0]
    return unique_assignments, unreachable, tied


def constrained_paths_for_triple(
    source_ap_id: str,
    target_ap_id: str,
    core_id: str,
    adjacency: dict[str, set[str]],
    core_tree: tuple[dict[str, int], dict[str, list[str]]],
    ap_tree_cache: dict[str, tuple[dict[str, int], dict[str, list[str]]]],
    max_answer_paths: int,
) -> tuple[Candidate | None, str]:
    if source_ap_id not in ap_tree_cache:
        ap_tree_cache[source_ap_id] = shortest_path_tree(adjacency, source_ap_id)
    source_distances, source_parents = ap_tree_cache[source_ap_id]
    core_distances, core_parents = core_tree
    if core_id not in source_distances or target_ap_id not in core_distances:
        return None, "segment-unreachable"
    baseline_length = source_distances.get(target_ap_id)
    if baseline_length is None:
        return None, "ap-pair-unreachable"

    left_count = count_shortest_paths(
        source_ap_id,
        core_id,
        source_distances,
        source_parents,
        max_answer_paths,
    )
    right_count = count_shortest_paths(
        core_id,
        target_ap_id,
        core_distances,
        core_parents,
        max_answer_paths,
    )
    if left_count > max_answer_paths or right_count > max_answer_paths:
        return None, "segment-shortest-path-count-exceeds-limit"

    left_paths = restore_shortest_paths(source_ap_id, core_id, source_parents)
    right_paths = restore_shortest_paths(core_id, target_ap_id, core_parents)
    combined: set[tuple[str, ...]] = set()
    for left_path in left_paths:
        left_without_core = set(left_path[:-1])
        for right_path in right_paths:
            if not left_without_core.isdisjoint(right_path[1:]):
                continue
            combined.add(tuple([*left_path, *right_path[1:]]))
            if len(combined) > max_answer_paths:
                return None, "answer-path-count-exceeds-limit"
    if not combined:
        return None, "no-simple-shortest-segment-combination"

    paths = tuple(sorted(combined))
    constrained_length = len(paths[0]) - 1
    expected_length = source_distances[core_id] + core_distances[target_ap_id]
    if constrained_length != expected_length:
        raise AssertionError("约束路径长度与两段最短距离之和不一致")
    category = DETOUR if constrained_length > baseline_length else NATURAL
    return (
        Candidate(
            source_ap_id=source_ap_id,
            target_ap_id=target_ap_id,
            required_core_id=core_id,
            baseline_path_length=baseline_length,
            constrained_path_length=constrained_length,
            paths=paths,
            category=category,
        ),
        "",
    )


def collect_candidates(
    graph: dict[str, Any],
    args: argparse.Namespace,
    rng: random.Random,
) -> tuple[list[Candidate], dict[str, Any], str]:
    node_ids, role_by_id, node_issue = collect_nodes(graph)
    if node_issue:
        return [], {"node_issue": node_issue}, node_issue.split(":", 1)[0]
    ap_ids = sorted(node_id for node_id in node_ids if role_by_id[node_id] == "AP")
    core_ids = sorted(
        node_id for node_id in node_ids if role_by_id[node_id] == "CORE"
    )
    if len(ap_ids) < 2:
        return [], {"ap_nodes": len(ap_ids)}, "fewer-than-two-ap-nodes"
    if not core_ids:
        return [], {"ap_nodes": len(ap_ids)}, "no-core-role-node"

    adjacency, valid_links, link_reasons = build_adjacency(graph, node_ids)
    if not valid_links:
        return [], {"valid_links": 0}, "no-valid-links"
    core_trees = {
        core_id: shortest_path_tree(adjacency, core_id) for core_id in core_ids
    }
    assignments, unreachable_aps, tied_aps = assign_unique_nearest_cores(
        ap_ids,
        core_ids,
        core_trees,
    )
    aps_by_core: dict[str, list[str]] = defaultdict(list)
    for ap_id, core_id in assignments.items():
        aps_by_core[core_id].append(ap_id)

    triples = [
        (left, right, core_id)
        for core_id, assigned_aps in sorted(aps_by_core.items())
        for left, right in itertools.combinations(sorted(assigned_aps), 2)
    ]
    eligible_triple_count = len(triples)
    rng.shuffle(triples)
    triples = triples[: args.max_candidate_attempts_per_graph]
    candidate_reasons: Counter[str] = Counter()
    selected_by_category: dict[str, list[Candidate]] = {
        DETOUR: [],
        NATURAL: [],
    }
    quotas = {
        DETOUR: args.detour_samples_per_graph,
        NATURAL: args.natural_samples_per_graph,
    }
    ap_tree_cache: dict[
        str,
        tuple[dict[str, int], dict[str, list[str]]],
    ] = {}
    for source_ap_id, target_ap_id, core_id in triples:
        candidate, reason = constrained_paths_for_triple(
            source_ap_id,
            target_ap_id,
            core_id,
            adjacency,
            core_trees[core_id],
            ap_tree_cache,
            args.max_answer_paths,
        )
        if candidate is None:
            candidate_reasons[reason] += 1
            continue
        values = selected_by_category[candidate.category]
        if len(values) < quotas[candidate.category]:
            values.append(candidate)
        if all(
            len(selected_by_category[category]) >= quota
            for category, quota in quotas.items()
        ):
            break

    selected = [*selected_by_category[DETOUR], *selected_by_category[NATURAL]]
    counters: dict[str, Any] = {
        "node_count": len(node_ids),
        "valid_links": valid_links,
        "ignored_link_reasons": dict(link_reasons),
        "ap_nodes": len(ap_ids),
        "core_nodes": len(core_ids),
        "unique_nearest_core_aps": len(assignments),
        "unreachable_from_all_cores_aps": unreachable_aps,
        "equidistant_nearest_core_aps": tied_aps,
        "eligible_ap_pair_core_combinations": eligible_triple_count,
        "attempted_ap_pair_core_combinations": len(triples),
        "candidate_reasons": dict(candidate_reasons),
        "selected_detours": len(selected_by_category[DETOUR]),
        "selected_natural": len(selected_by_category[NATURAL]),
    }
    if not selected:
        if not triples:
            return [], counters, "no-two-aps-share-unique-nearest-core"
        return [], counters, "no-valid-constrained-path-candidate"
    return selected, counters, ""


def build_task_graph(
    graph: dict[str, Any],
    candidate: Candidate,
    split: str,
    source_file: str,
) -> dict[str, Any]:
    task_graph = copy.deepcopy(graph)
    for key in list(task_graph):
        if key.startswith("task_"):
            task_graph.pop(key)
    task_graph["task_source_ap_node_id"] = candidate.source_ap_id
    task_graph["task_target_ap_node_id"] = candidate.target_ap_id
    task_graph["task_required_core_node_id"] = candidate.required_core_id
    task_graph["task_question"] = QUESTION_TEMPLATE.format(
        source_ap_id=candidate.source_ap_id,
        target_ap_id=candidate.target_ap_id,
        required_core_id=candidate.required_core_id,
    )
    task_graph["task_answer"] = {
        "path_length": candidate.constrained_path_length,
        "paths": [list(path) for path in candidate.paths],
    }
    task_graph["task_metadata"] = {
        "task_name": "ap_pair_shortest_path_via_required_core",
        "split": split,
        "source_file": source_file,
        "graph_policy": "undirected_physical_topology",
        "ap_core_policy": "two_aps_share_unique_nearest_core",
    }
    return task_graph


def output_relative_path(relative_input: Path, sample_index: int) -> Path:
    return relative_input.with_name(
        f"{relative_input.stem}__via_core_{sample_index:03d}.json"
    )


def remove_stale_outputs(output_root: Path, split: str, relative_input: Path) -> None:
    prefix = f"{relative_input.stem}__via_core_"
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
        "source_ap_node_id",
        "target_ap_node_id",
        "required_core_node_id",
        "category",
        "baseline_path_length",
        "constrained_path_length",
        "path_count",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


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
        "sample_quotas_per_graph": {
            DETOUR: args.detour_samples_per_graph,
            NATURAL: args.natural_samples_per_graph,
        },
        "max_candidate_attempts_per_graph": args.max_candidate_attempts_per_graph,
        "max_answer_paths": args.max_answer_paths,
        "splits": {},
    }

    for split in args.splits:
        files = iter_json_files(dataset_root, split)
        split_summary: dict[str, Any] = {
            "input_files": len(files),
            "graphs_with_samples": 0,
            "skipped_graphs": 0,
            "generated_samples": 0,
            "forced_core_detour_samples": 0,
            "natural_via_core_samples": 0,
            "skip_reasons": {},
        }
        skip_reasons: Counter[str] = Counter()
        print(f"[{split}] found {len(files)} json files", flush=True)
        for file_index, source_path in enumerate(files, start=1):
            relative_input = source_path.relative_to(dataset_root / split)
            remove_stale_outputs(output_root, split, relative_input)
            graph, error = load_graph(source_path)
            if graph is None:
                selected: list[Candidate] = []
                counters: dict[str, Any] = {}
                reason = "load-json-error"
                counters["detail"] = error
            else:
                selected, counters, reason = collect_candidates(graph, args, rng)

            if graph is None or not selected:
                split_summary["skipped_graphs"] += 1
                skip_reasons[reason] += 1
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
                    with_path = output_root / WITH_ANSWER_DIR / split / relative_output
                    without_path = (
                        output_root / WITHOUT_ANSWER_DIR / split / relative_output
                    )
                    task_graph = build_task_graph(
                        graph,
                        candidate,
                        split,
                        str(relative_input),
                    )
                    write_json(with_path, task_graph, args.indent)
                    hidden_graph = copy.deepcopy(task_graph)
                    hidden_graph.pop("task_answer", None)
                    write_json(without_path, hidden_graph, args.indent)
                    split_summary["generated_samples"] += 1
                    split_summary[f"{candidate.category}_samples"] += 1
                    stats_rows.append(
                        {
                            "split": split,
                            "source_file": str(relative_input),
                            "sample_file": str(relative_output),
                            "source_ap_node_id": candidate.source_ap_id,
                            "target_ap_node_id": candidate.target_ap_id,
                            "required_core_node_id": candidate.required_core_id,
                            "category": candidate.category,
                            "baseline_path_length": candidate.baseline_path_length,
                            "constrained_path_length": candidate.constrained_path_length,
                            "path_count": len(candidate.paths),
                        }
                    )

            if args.progress_interval > 0 and (
                file_index % args.progress_interval == 0 or file_index == len(files)
            ):
                print(
                    f"[{split}] {file_index}/{len(files)}，"
                    f"图 {split_summary['graphs_with_samples']}，"
                    f"样本 {split_summary['generated_samples']}，"
                    f"跳过 {split_summary['skipped_graphs']}",
                    flush=True,
                )

        split_summary["skip_reasons"] = dict(sorted(skip_reasons.items()))
        summary["splits"][split] = split_summary

    write_stats(output_root / STATS_FILE, stats_rows)
    write_json(output_root / SUMMARY_FILE, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


if __name__ == "__main__":
    build_dataset(parse_args())
