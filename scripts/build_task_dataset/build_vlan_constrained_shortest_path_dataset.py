#!/usr/bin/env python3
"""构造指定 VLAN 下的交换机约束最短路径绕行任务数据集。"""

from __future__ import annotations

import argparse
import copy
import csv
import json
import re
from collections import Counter, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional


DEFAULT_DATASET_ROOT = Path("datasets")
DEFAULT_OUTPUT_ROOT = Path("vlan_constrained_shortest_path_dataset")
DEFAULT_SPLITS = ("train", "val")
DEFAULT_MAX_ANSWER_PATHS = 1000
DEFAULT_MAX_RANGE_SIZE = 4096
DEFAULT_PROGRESS_INTERVAL = 100
DEFAULT_CONFIG_FIELDS = ("configs",)

WITH_ANSWER_DIR = "with_answer"
WITHOUT_ANSWER_DIR = "without_answer"
STATS_FILE = "vlan_constrained_shortest_path_stats.csv"
SUMMARY_FILE = "build_summary.json"
ISSUES_FILE = "build_issues.jsonl"

RANGE_PATTERN = re.compile(r"^(\d+)\s*-\s*(\d+)$")
INTEGER_PATTERN = re.compile(r"^\d+$")
VlanSupport = Optional[frozenset[int]]

QUESTION_TEMPLATE = """请根据交换机配置，查找 LSW 节点 {source_node_id} 与节点 {target_node_id} 在 VLAN {vlan_id} 约束下能够端到端通行的全部最短路径。路径中的每条链路，其两端端口均须允许 VLAN {vlan_id} 通行。

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
      "description": "最短路径的链路跳数"
    }},
    "paths": {{
      "type": "array",
      "description": "全部等长最短路径，路径中的节点使用节点 ID",
      "items": {{
        "type": "array",
        "items": {{
          "type": "string"
        }}
      }}
    }}
  }}
}}

只输出 JSON，不要输出解释、Markdown 或代码块。

输出示例如下：
{{
  "path_length": 3,
  "paths": [
    ["LSW_A", "LSW_B", "LSW_C", "LSW_D"],
    ["LSW_A", "LSW_E", "LSW_F", "LSW_D"]
  ]
}}"""


@dataclass(frozen=True)
class Candidate:
    source_node_id: str
    target_node_id: str
    vlan_id: int
    baseline_path_length: int
    vlan_path_length: int
    paths: tuple[tuple[str, ...], ...]

    @property
    def hop_increase(self) -> int:
        return self.vlan_path_length - self.baseline_path_length


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
        "--max-answer-paths",
        type=int,
        default=DEFAULT_MAX_ANSWER_PATHS,
        help="答案路径数超过该值时跳过候选，默认: %(default)s",
    )
    parser.add_argument(
        "--max-range-size",
        type=int,
        default=DEFAULT_MAX_RANGE_SIZE,
        help="单个 VLAN 范围允许展开的最大数量，默认: %(default)s",
    )
    parser.add_argument(
        "--config-fields",
        nargs="+",
        default=list(DEFAULT_CONFIG_FIELDS),
        help="需要扫描的节点配置字段，默认只扫描 configs",
    )
    parser.add_argument(
        "--progress-interval",
        type=int,
        default=DEFAULT_PROGRESS_INTERVAL,
        help="每处理 N 个文件打印进度，0 表示关闭，默认: %(default)s",
    )
    parser.add_argument("--indent", type=int, default=2)
    args = parser.parse_args()
    if args.max_answer_paths <= 0:
        parser.error("--max-answer-paths 必须大于 0")
    if args.max_range_size <= 0:
        parser.error("--max-range-size 必须大于 0")
    if not args.config_fields or any(not field for field in args.config_fields):
        parser.error("--config-fields 至少需要一个非空字段名")
    if len(args.config_fields) != len(set(args.config_fields)):
        parser.error("--config-fields 不能包含重复字段名")
    if args.progress_interval < 0 or args.indent < 0:
        parser.error("进度间隔和 JSON 缩进不能小于 0")
    return args


def iter_json_files(dataset_root: Path, split: str) -> list[Path]:
    split_root = dataset_root / split
    if not split_root.is_dir():
        return []
    return sorted(path for path in split_root.rglob("*.json") if path.is_file())


def load_graph(path: Path) -> tuple[Optional[dict[str, Any]], str]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as error:  # noqa: BLE001 - 坏文件应记录后继续。
        return None, f"{type(error).__name__}: {error}"
    if not isinstance(value, dict):
        return None, f"top-level type is {type(value).__name__}, expected object"
    return value, ""


def object_items(value: Any) -> Iterable[tuple[int, dict[str, Any]]]:
    if isinstance(value, dict):
        yield 0, value
    elif isinstance(value, list):
        for index, item in enumerate(value):
            if isinstance(item, dict):
                yield index, item


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


def collect_interface_matches(
    node: dict[str, Any],
    port_name: Optional[str],
    config_fields: list[str],
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    if port_name is None:
        return matches
    for config_field in config_fields:
        for _, config in object_items(node.get(config_field)):
            for _, business in object_items(config.get("lsw-interfaces-business")):
                for _, interface in object_items(business.get("lsw-interface")):
                    if scalar_text(interface.get("interface-name")) == port_name:
                        matches.append(interface)
    return matches


def parse_vlan_value(
    value: Any,
    max_range_size: int,
) -> tuple[VlanSupport, list[str]]:
    vlan_ids: set[int] = set()
    errors: list[str] = []
    contains_all = False

    def visit(item: Any) -> None:
        nonlocal contains_all
        if isinstance(item, bool) or item is None:
            errors.append(f"unsupported-value:{json.dumps(item)}")
            return
        if isinstance(item, int):
            vlan_ids.add(item)
            return
        if isinstance(item, float):
            if item.is_integer():
                vlan_ids.add(int(item))
            else:
                errors.append(f"non-integer-number:{item}")
            return
        if isinstance(item, list):
            if not item:
                errors.append("empty-list")
                return
            for child in item:
                visit(child)
            return
        if not isinstance(item, str):
            errors.append(f"unsupported-type:{type(item).__name__}")
            return

        tokens = [
            token.strip()
            for token in re.split(r"[,，]", item)
            if token.strip()
        ]
        if not tokens:
            errors.append("empty-string")
            return
        for token in tokens:
            if token.lower() == "all":
                contains_all = True
                continue
            if INTEGER_PATTERN.fullmatch(token):
                vlan_ids.add(int(token))
                continue
            match = RANGE_PATTERN.fullmatch(token)
            if match is None:
                errors.append(f"invalid-token:{token}")
                continue
            start = int(match.group(1))
            end = int(match.group(2))
            if start > end:
                errors.append(f"descending-range:{token}")
                continue
            if end - start + 1 > max_range_size:
                errors.append(f"range-too-large:{token}")
                continue
            vlan_ids.update(range(start, end + 1))

    visit(value)
    return (None if contains_all else frozenset(vlan_ids)), errors


def intersect_support(left: VlanSupport, right: VlanSupport) -> VlanSupport:
    if left is None:
        return right
    if right is None:
        return left
    return left & right


def union_support(left: VlanSupport, right: VlanSupport) -> VlanSupport:
    if left is None or right is None:
        return None
    return left | right


def add_edge(adjacency: dict[str, set[str]], left: str, right: str) -> None:
    adjacency.setdefault(left, set()).add(right)
    adjacency.setdefault(right, set()).add(left)


def add_supported_edge(
    edge_supports: dict[tuple[str, str], VlanSupport],
    left: str,
    right: str,
    support: VlanSupport,
) -> None:
    edge = tuple(sorted((left, right)))
    if edge in edge_supports:
        support = union_support(edge_supports[edge], support)
    edge_supports[edge] = support


def build_strict_graphs(
    graph: dict[str, Any],
    config_fields: list[str],
    max_range_size: int,
) -> tuple[
    dict[str, set[str]],
    dict[tuple[str, str], VlanSupport],
    set[int],
    Counter[str],
    str,
]:
    """仅使用接口唯一匹配且 VLAN 完整可解析的 LSW 链路。"""

    base_adjacency: dict[str, set[str]] = {}
    edge_supports: dict[tuple[str, str], VlanSupport] = {}
    observed_vlan_ids: set[int] = set()
    counters: Counter[str] = Counter()
    nodes = graph.get("nodes")
    links = graph.get("links")
    if not isinstance(nodes, list):
        return base_adjacency, edge_supports, observed_vlan_ids, counters, "nodes-not-list"
    if not isinstance(links, list):
        return base_adjacency, edge_supports, observed_vlan_ids, counters, "links-not-list"

    node_by_id: dict[str, dict[str, Any]] = {}
    duplicate_ids: set[str] = set()
    for node in nodes:
        if not isinstance(node, dict):
            counters["invalid-node-item"] += 1
            continue
        node_id = scalar_text(node.get("id"))
        if node_id is None:
            counters["node-without-id"] += 1
            continue
        if node_id in node_by_id:
            duplicate_ids.add(node_id)
            continue
        node_by_id[node_id] = node
    if duplicate_ids:
        return (
            base_adjacency,
            edge_supports,
            observed_vlan_ids,
            counters,
            "duplicate-node-id",
        )

    counters["input-links"] = len(links)
    for link in links:
        if not isinstance(link, dict):
            counters["invalid-link-item"] += 1
            continue
        source_id = scalar_text(link.get("source"))
        target_id = scalar_text(link.get("target"))
        if source_id is None or target_id is None:
            counters["missing-link-endpoint"] += 1
            continue
        if source_id == target_id:
            counters["self-loop"] += 1
            continue
        source_node = node_by_id.get(source_id)
        target_node = node_by_id.get(target_id)
        if source_node is None or target_node is None:
            counters["unresolved-link-endpoint"] += 1
            continue
        if not (is_lsw_node(source_node) and is_lsw_node(target_node)):
            counters["not-lsw-to-lsw"] += 1
            continue

        counters["lsw-to-lsw-links"] += 1
        detail = link.get("link")
        if not isinstance(detail, dict):
            detail = {}
        left_matches = collect_interface_matches(
            source_node,
            scalar_text(detail.get("LEFTPORT")),
            config_fields,
        )
        right_matches = collect_interface_matches(
            target_node,
            scalar_text(detail.get("RIGHTPORT")),
            config_fields,
        )
        if len(left_matches) != 1 or len(right_matches) != 1:
            counters["non-unique-interface-match"] += 1
            continue
        left_interface = left_matches[0]
        right_interface = right_matches[0]
        if (
            "allow-through-vlan" not in left_interface
            or "allow-through-vlan" not in right_interface
        ):
            counters["missing-bilateral-allow-through-vlan"] += 1
            continue

        left_support, left_errors = parse_vlan_value(
            left_interface["allow-through-vlan"],
            max_range_size,
        )
        right_support, right_errors = parse_vlan_value(
            right_interface["allow-through-vlan"],
            max_range_size,
        )
        if left_errors or right_errors:
            counters["vlan-parse-error-link"] += 1
            continue

        counters["strict-base-link-records"] += 1
        add_edge(base_adjacency, source_id, target_id)
        if left_support is not None:
            observed_vlan_ids.update(left_support)
        if right_support is not None:
            observed_vlan_ids.update(right_support)
        common_support = intersect_support(left_support, right_support)
        if common_support is not None and not common_support:
            counters["link-without-common-vlan"] += 1
            continue
        counters["vlan-supported-link-records"] += 1
        add_supported_edge(edge_supports, source_id, target_id, common_support)

    if not base_adjacency:
        return base_adjacency, edge_supports, observed_vlan_ids, counters, "no-strict-base-link"
    if not edge_supports:
        return base_adjacency, edge_supports, observed_vlan_ids, counters, "no-vlan-supported-link"
    if not observed_vlan_ids:
        return base_adjacency, edge_supports, observed_vlan_ids, counters, "no-explicit-vlan-id"
    return base_adjacency, edge_supports, observed_vlan_ids, counters, ""


def vlan_adjacency(
    edge_supports: dict[tuple[str, str], VlanSupport],
    vlan_id: int,
) -> dict[str, set[str]]:
    adjacency: dict[str, set[str]] = {}
    for (left, right), support in edge_supports.items():
        if support is None or vlan_id in support:
            add_edge(adjacency, left, right)
    return adjacency


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
) -> tuple[tuple[str, ...], ...]:
    paths: list[tuple[str, ...]] = []
    stack: list[tuple[str, tuple[str, ...]]] = [(target, (target,))]
    while stack:
        node, reversed_path = stack.pop()
        if node == source:
            paths.append(tuple(reversed(reversed_path)))
            continue
        for predecessor in reversed(sorted(predecessors.get(node, []))):
            stack.append((predecessor, reversed_path + (predecessor,)))
    return tuple(sorted(paths))


def collect_candidates(
    graph: dict[str, Any],
    args: argparse.Namespace,
) -> tuple[list[Candidate], dict[str, Any], str]:
    base_adjacency, edge_supports, vlan_ids, counters, reason = build_strict_graphs(
        graph,
        args.config_fields,
        args.max_range_size,
    )
    if reason:
        return [], dict(counters), reason

    base_tree_cache: dict[str, dict[str, int]] = {}
    longest_candidates: list[Candidate] = []
    longest_path_length = -1
    candidate_reasons: Counter[str] = Counter()

    for vlan_id in sorted(vlan_ids):
        constrained_adjacency = vlan_adjacency(edge_supports, vlan_id)
        for source in sorted(constrained_adjacency):
            if source not in base_tree_cache:
                base_tree_cache[source] = shortest_path_tree(
                    source,
                    base_adjacency,
                )[0]
            base_distances = base_tree_cache[source]
            distances, predecessors, path_counts = shortest_path_tree(
                source,
                constrained_adjacency,
            )
            targets = sorted(target for target in distances if source < target)
            for target in targets:
                counters["checked-vlan-node-pairs"] += 1
                baseline_distance = base_distances.get(target)
                if baseline_distance is None:
                    candidate_reasons["not-reachable-in-strict-base-graph"] += 1
                    continue
                constrained_distance = distances[target]
                if constrained_distance <= baseline_distance:
                    candidate_reasons["no-vlan-detour"] += 1
                    continue
                if constrained_distance < longest_path_length:
                    candidate_reasons["shorter-than-current-longest"] += 1
                    continue
                path_count = path_counts[target]
                if path_count > args.max_answer_paths:
                    candidate_reasons["too-many-answer-paths"] += 1
                    continue
                paths = restore_paths(source, target, predecessors)
                if len(paths) != path_count:
                    candidate_reasons["path-count-mismatch"] += 1
                    continue
                candidate = Candidate(
                    source_node_id=source,
                    target_node_id=target,
                    vlan_id=vlan_id,
                    baseline_path_length=baseline_distance,
                    vlan_path_length=constrained_distance,
                    paths=paths,
                )
                if constrained_distance > longest_path_length:
                    longest_path_length = constrained_distance
                    longest_candidates = [candidate]
                else:
                    longest_candidates.append(candidate)

    longest_candidates.sort(
        key=lambda candidate: (
            candidate.source_node_id,
            candidate.target_node_id,
            candidate.vlan_id,
        )
    )
    selected = longest_candidates[:1]

    details: dict[str, Any] = {
        **dict(counters),
        "explicit_vlan_ids": len(vlan_ids),
        "strict_base_unique_edges": sum(
            len(neighbors) for neighbors in base_adjacency.values()
        ) // 2,
        "vlan_supported_unique_edges": len(edge_supports),
        "candidate_reasons": dict(sorted(candidate_reasons.items())),
        "longest_candidate_count": len(longest_candidates),
        "longest_vlan_path_length": (
            longest_path_length if longest_path_length >= 0 else None
        ),
        "selected_samples": len(selected),
    }
    if not selected:
        return [], details, "no-strict-vlan-detour-candidate"
    return selected, details, ""


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
    task_graph["task_source_node_id"] = candidate.source_node_id
    task_graph["task_target_node_id"] = candidate.target_node_id
    task_graph["task_vlan_id"] = candidate.vlan_id
    task_graph["task_question"] = QUESTION_TEMPLATE.format(
        source_node_id=candidate.source_node_id,
        target_node_id=candidate.target_node_id,
        vlan_id=candidate.vlan_id,
    )
    task_graph["task_answer"] = {
        "path_length": candidate.vlan_path_length,
        "paths": [list(path) for path in candidate.paths],
    }
    task_graph["task_metadata"] = {
        "task_name": "vlan_constrained_shortest_path_detour",
        "split": split,
        "source_file": source_file,
        "graph_policy": "undirected_lsw_physical_topology",
        "vlan_policy": "fixed_vlan_allowed_by_both_ports_on_every_link",
        "candidate_policy": "vlan_path_is_longer_than_strict_base_shortest_path",
    }
    return task_graph


def output_relative_path(relative_input: Path) -> Path:
    return relative_input


def remove_stale_outputs(
    output_root: Path,
    split: str,
    relative_input: Path,
) -> None:
    prefix = f"{relative_input.stem}__vlan_path_"
    for version in (WITH_ANSWER_DIR, WITHOUT_ANSWER_DIR):
        parent = output_root / version / split / relative_input.parent
        if not parent.is_dir():
            continue
        current_output = parent / relative_input.name
        if current_output.is_file():
            current_output.unlink()
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
        "vlan_id",
        "baseline_path_length",
        "vlan_path_length",
        "hop_increase",
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
    stats_rows: list[dict[str, Any]] = []
    summary: dict[str, Any] = {
        "dataset_root": str(dataset_root),
        "output_root": str(output_root),
        "samples_per_graph": 1,
        "candidate_selection": "maximum vlan_path_length, then stable ID order",
        "max_answer_paths": args.max_answer_paths,
        "max_range_size": args.max_range_size,
        "config_fields": args.config_fields,
        "splits": {},
    }

    for split in args.splits:
        files = iter_json_files(dataset_root, split)
        split_summary: dict[str, Any] = {
            "input_files": len(files),
            "graphs_with_samples": 0,
            "skipped_graphs": 0,
            "generated_samples": 0,
            "skip_reasons": {},
        }
        skip_reasons: Counter[str] = Counter()
        print(f"[{split}] found {len(files)} json files", flush=True)
        for file_index, source_path in enumerate(files, start=1):
            relative_input = source_path.relative_to(dataset_root / split)
            remove_stale_outputs(output_root, split, relative_input)
            graph, error = load_graph(source_path)
            if graph is None:
                candidates: list[Candidate] = []
                counters: dict[str, Any] = {"detail": error}
                reason = "load-json-error"
            else:
                candidates, counters, reason = collect_candidates(graph, args)

            if graph is None or not candidates:
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
                for candidate in candidates:
                    relative_output = output_relative_path(relative_input)
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
                    stats_rows.append(
                        {
                            "split": split,
                            "source_file": str(relative_input),
                            "sample_file": str(relative_output),
                            "source_node_id": candidate.source_node_id,
                            "target_node_id": candidate.target_node_id,
                            "vlan_id": candidate.vlan_id,
                            "baseline_path_length": candidate.baseline_path_length,
                            "vlan_path_length": candidate.vlan_path_length,
                            "hop_increase": candidate.hop_increase,
                            "path_count": len(candidate.paths),
                        }
                    )

            if args.progress_interval > 0 and (
                file_index % args.progress_interval == 0 or file_index == len(files)
            ):
                print(
                    f"[{split}] {file_index}/{len(files)}，"
                    f"有效图 {split_summary['graphs_with_samples']}，"
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
