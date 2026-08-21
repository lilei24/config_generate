#!/usr/bin/env python3
"""统计至少有一个 VLAN 可端到端通过的 LSW 最短路径分布。"""

from __future__ import annotations

import argparse
import json
import re
import time
from collections import Counter, deque
from pathlib import Path
from typing import Any, Optional

import analyze_lsw_link_interfaces as link_analysis


DEFAULT_DATASET_ROOT = Path("datasets")
DEFAULT_OUTPUT_FILE = Path("/tmp/lsw_vlan_constrained_path_distribution.json")
DEFAULT_SPLIT = "all"
DEFAULT_CONFIG_FIELDS = ("configs",)
DEFAULT_PROGRESS_INTERVAL = 100
DEFAULT_MAX_RANGE_SIZE = 4096

RANGE_PATTERN = re.compile(r"^(\d+)\s*-\s*(\d+)$")
INTEGER_PATTERN = re.compile(r"^\d+$")

# None 表示 ALL；frozenset 表示有限 VLAN 集合。
VlanSupport = Optional[frozenset[int]]

SUMMARY_COUNTER_KEYS = (
    "input-files",
    "valid-files",
    "invalid-files",
    "files-with-vlan-eligible-links",
    "files-without-vlan-eligible-links",
    "files-with-vlan-multi-hop-paths",
    "files-with-constrained-detours",
    "input-links",
    "self-loop-links",
    "lsw-to-lsw-links",
    "links-with-both-interfaces-matched",
    "links-with-incomplete-interface-match",
    "links-without-bilateral-allow-through-vlan",
    "links-with-vlan-parse-errors",
    "links-without-common-vlan",
    "vlan-eligible-link-records",
    "duplicate-base-edges",
    "duplicate-vlan-edges",
    "base-unique-edges",
    "vlan-eligible-unique-edges",
    "base-reachable-node-pairs",
    "vlan-reachable-node-pairs",
    "vlan-unreachable-node-pairs",
    "vlan-shortest-paths",
    "multiple-vlan-shortest-path-pairs",
    "same-length-node-pairs",
    "constrained-detour-node-pairs",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "dataset_root",
        nargs="?",
        type=Path,
        default=DEFAULT_DATASET_ROOT,
        help="数据集根目录，目录下应包含 train/val，默认: %(default)s",
    )
    parser.add_argument(
        "-o",
        "--output-file",
        type=Path,
        default=DEFAULT_OUTPUT_FILE,
        help="分析结果 JSON 文件，默认: %(default)s",
    )
    parser.add_argument(
        "--split",
        choices=["train", "val", "all"],
        default=DEFAULT_SPLIT,
        help="分析 train、val 或全部数据，默认: %(default)s",
    )
    parser.add_argument(
        "--config-fields",
        nargs="+",
        default=list(DEFAULT_CONFIG_FIELDS),
        help="需要扫描的节点配置字段，默认只扫描 configs",
    )
    parser.add_argument(
        "--max-range-size",
        type=int,
        default=DEFAULT_MAX_RANGE_SIZE,
        help="单个 VLAN 范围允许展开的最大数量，默认: %(default)s",
    )
    parser.add_argument(
        "--progress-interval",
        type=int,
        default=DEFAULT_PROGRESS_INTERVAL,
        help="每处理 N 个文件打印一次进度，0 表示关闭，默认: %(default)s",
    )
    args = parser.parse_args()
    if not args.config_fields or any(not field for field in args.config_fields):
        parser.error("--config-fields 至少需要一个非空字段名")
    if len(args.config_fields) != len(set(args.config_fields)):
        parser.error("--config-fields 不能包含重复字段名")
    if args.max_range_size <= 0:
        parser.error("--max-range-size 必须大于 0")
    if args.progress_interval < 0:
        parser.error("--progress-interval 不能小于 0")
    return args


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


def support_is_empty(support: VlanSupport) -> bool:
    return support is not None and not support


def add_base_edge(adjacency: dict[str, set[str]], left: str, right: str) -> bool:
    existed = right in adjacency.get(left, set())
    adjacency.setdefault(left, set()).add(right)
    adjacency.setdefault(right, set()).add(left)
    return existed


def add_vlan_edge(
    adjacency: dict[str, dict[str, VlanSupport]],
    left: str,
    right: str,
    support: VlanSupport,
) -> bool:
    existed = right in adjacency.get(left, {})
    if existed:
        support = union_support(adjacency[left][right], support)
    adjacency.setdefault(left, {})[right] = support
    adjacency.setdefault(right, {})[left] = support
    return existed


def build_graphs(
    graph: dict[str, Any],
    config_fields: list[str],
    max_range_size: int,
) -> tuple[dict[str, set[str]], dict[str, dict[str, VlanSupport]], Counter[str]]:
    """构建普通候选图和边携带共同 VLAN 集合的约束图。"""

    base_adjacency: dict[str, set[str]] = {}
    vlan_adjacency: dict[str, dict[str, VlanSupport]] = {}
    counters: Counter[str] = Counter()
    nodes = graph.get("nodes")
    links = graph.get("links")
    if not isinstance(nodes, list):
        counters["files-with-nodes-not-list"] += 1
        return base_adjacency, vlan_adjacency, counters
    if not isinstance(links, list):
        counters["files-with-links-not-list"] += 1
        return base_adjacency, vlan_adjacency, counters

    node_by_id: dict[str, dict[str, Any]] = {}
    for node in nodes:
        if not isinstance(node, dict):
            counters["invalid-node-items"] += 1
            continue
        node_id = link_analysis.scalar_text(node.get("id"))
        if node_id is None:
            counters["nodes-without-id"] += 1
            continue
        if node_id in node_by_id:
            counters["duplicate-node-ids"] += 1
            continue
        node_by_id[node_id] = node

    counters["input-links"] += len(links)
    for link in links:
        if not isinstance(link, dict):
            counters["invalid-link-items"] += 1
            continue
        source_id = link_analysis.scalar_text(link.get("source"))
        target_id = link_analysis.scalar_text(link.get("target"))
        if source_id is not None and source_id == target_id:
            counters["self-loop-links"] += 1
            continue
        source_node = node_by_id.get(source_id or "")
        target_node = node_by_id.get(target_id or "")
        if source_node is None or target_node is None:
            counters["links-with-unresolved-endpoints"] += 1
            continue
        if not (
            link_analysis.is_lsw_node(source_node)
            and link_analysis.is_lsw_node(target_node)
        ):
            counters["non-lsw-to-lsw-links"] += 1
            continue

        counters["lsw-to-lsw-links"] += 1
        attributes = link.get("link")
        if not isinstance(attributes, dict):
            attributes = {}
        left_status, left_matches, _ = link_analysis.collect_interface_configs(
            source_node,
            link_analysis.scalar_text(attributes.get("LEFTPORT")),
            config_fields,
        )
        right_status, right_matches, _ = link_analysis.collect_interface_configs(
            target_node,
            link_analysis.scalar_text(attributes.get("RIGHTPORT")),
            config_fields,
        )
        if left_status != "matched" or right_status != "matched":
            counters["links-with-incomplete-interface-match"] += 1
            continue

        counters["links-with-both-interfaces-matched"] += 1
        left_interface = left_matches[0]["interface_config"]
        right_interface = right_matches[0]["interface_config"]
        if (
            "allow-through-vlan" not in left_interface
            or "allow-through-vlan" not in right_interface
        ):
            counters["links-without-bilateral-allow-through-vlan"] += 1
            continue

        if add_base_edge(base_adjacency, source_id or "", target_id or ""):
            counters["duplicate-base-edges"] += 1

        left_support, left_errors = parse_vlan_value(
            left_interface["allow-through-vlan"],
            max_range_size,
        )
        right_support, right_errors = parse_vlan_value(
            right_interface["allow-through-vlan"],
            max_range_size,
        )
        if left_errors or right_errors:
            counters["links-with-vlan-parse-errors"] += 1
            counters["vlan-parse-errors"] += len(left_errors) + len(right_errors)
            continue

        common_support = intersect_support(left_support, right_support)
        if support_is_empty(common_support):
            counters["links-without-common-vlan"] += 1
            continue

        counters["vlan-eligible-link-records"] += 1
        if add_vlan_edge(
            vlan_adjacency,
            source_id or "",
            target_id or "",
            common_support,
        ):
            counters["duplicate-vlan-edges"] += 1

    counters["base-unique-edges"] = sum(
        len(neighbors) for neighbors in base_adjacency.values()
    ) // 2
    counters["vlan-eligible-unique-edges"] = sum(
        len(neighbors) for neighbors in vlan_adjacency.values()
    ) // 2
    return base_adjacency, vlan_adjacency, counters


def ordinary_distances(
    source: str,
    adjacency: dict[str, set[str]],
) -> dict[str, int]:
    distances = {source: 0}
    queue = deque([source])
    while queue:
        node = queue.popleft()
        for neighbor in adjacency.get(node, set()):
            if neighbor in distances:
                continue
            distances[neighbor] = distances[node] + 1
            queue.append(neighbor)
    return distances


def constrained_paths_from_source(
    source: str,
    adjacency: dict[str, dict[str, VlanSupport]],
) -> tuple[
    dict[str, int],
    dict[str, int],
    dict[str, dict[VlanSupport, int]],
]:
    """按节点和沿途 VLAN 交集状态执行分层 BFS。"""

    initial_state = (source, None)
    current_states: dict[tuple[str, VlanSupport], int] = {initial_state: 1}
    state_distances = {initial_state: 0}
    node_distances = {source: 0}
    node_path_counts = {source: 1}
    node_support_counts: dict[str, dict[VlanSupport, int]] = {
        source: {None: 1}
    }
    depth = 0

    while current_states:
        next_depth = depth + 1
        next_states: dict[tuple[str, VlanSupport], int] = {}
        for (node, current_support), path_count in current_states.items():
            for neighbor, edge_support in adjacency.get(node, {}).items():
                new_support = intersect_support(current_support, edge_support)
                if support_is_empty(new_support):
                    continue
                state = (neighbor, new_support)
                known_distance = state_distances.get(state)
                if known_distance is None:
                    state_distances[state] = next_depth
                    next_states[state] = path_count
                elif known_distance == next_depth:
                    next_states[state] = next_states.get(state, 0) + path_count

        candidates: dict[str, dict[VlanSupport, int]] = {}
        for (node, support), path_count in next_states.items():
            if node in node_distances:
                continue
            support_counts = candidates.setdefault(node, {})
            support_counts[support] = support_counts.get(support, 0) + path_count
        for node, support_counts in candidates.items():
            node_distances[node] = next_depth
            node_support_counts[node] = support_counts
            node_path_counts[node] = sum(support_counts.values())

        current_states = next_states
        depth = next_depth

    return node_distances, node_path_counts, node_support_counts


def analyze_paths(
    base_adjacency: dict[str, set[str]],
    vlan_adjacency: dict[str, dict[str, VlanSupport]],
) -> dict[str, Any]:
    nodes = sorted(base_adjacency)
    pair_distance_distribution: Counter[int] = Counter()
    path_length_distribution: Counter[int] = Counter()
    hop_increase_distribution: Counter[int] = Counter()
    path_vlan_count_distribution: Counter[str] = Counter()
    base_reachable_pairs = 0
    vlan_reachable_pairs = 0
    vlan_unreachable_pairs = 0
    vlan_shortest_paths = 0
    multiple_path_pairs = 0
    same_length_pairs = 0
    constrained_detour_pairs = 0
    max_path_length = 0
    max_paths_per_pair = 0

    for source_index, source in enumerate(nodes):
        base_distances = ordinary_distances(source, base_adjacency)
        vlan_distances, path_counts, support_counts = (
            constrained_paths_from_source(source, vlan_adjacency)
        )
        for target in nodes[source_index + 1:]:
            if target not in base_distances:
                continue
            base_reachable_pairs += 1
            if target not in vlan_distances:
                vlan_unreachable_pairs += 1
                continue

            distance = vlan_distances[target]
            path_count = path_counts[target]
            vlan_reachable_pairs += 1
            vlan_shortest_paths += path_count
            pair_distance_distribution[distance] += 1
            path_length_distribution[distance] += path_count
            max_path_length = max(max_path_length, distance)
            max_paths_per_pair = max(max_paths_per_pair, path_count)
            if path_count > 1:
                multiple_path_pairs += 1

            hop_increase = distance - base_distances[target]
            hop_increase_distribution[hop_increase] += 1
            if hop_increase:
                constrained_detour_pairs += 1
            else:
                same_length_pairs += 1

            for support, count in support_counts[target].items():
                key = "all" if support is None else str(len(support))
                path_vlan_count_distribution[key] += count

    return {
        "base_reachable_node_pair_count": base_reachable_pairs,
        "vlan_reachable_node_pair_count": vlan_reachable_pairs,
        "vlan_unreachable_node_pair_count": vlan_unreachable_pairs,
        "vlan_shortest_path_count": vlan_shortest_paths,
        "multiple_vlan_shortest_path_pair_count": multiple_path_pairs,
        "same_length_node_pair_count": same_length_pairs,
        "constrained_detour_node_pair_count": constrained_detour_pairs,
        "max_vlan_shortest_path_length": max_path_length,
        "max_vlan_shortest_paths_per_pair": max_paths_per_pair,
        "node_pair_distance_distribution": {
            str(key): pair_distance_distribution[key]
            for key in sorted(pair_distance_distribution)
        },
        "shortest_path_length_distribution": {
            str(key): path_length_distribution[key]
            for key in sorted(path_length_distribution)
        },
        "hop_increase_distribution": {
            str(key): hop_increase_distribution[key]
            for key in sorted(hop_increase_distribution)
        },
        "path_vlan_count_distribution": {
            key: path_vlan_count_distribution[key]
            for key in sorted(
                path_vlan_count_distribution,
                key=lambda item: (item == "all", int(item) if item != "all" else 0),
            )
        },
    }


def merge_distribution(target: Counter[str], source: dict[str, int]) -> None:
    target.update(source)


def sorted_numeric_distribution(counter: Counter[str]) -> dict[str, int]:
    return {
        key: counter[key]
        for key in sorted(counter, key=lambda item: int(item))
    }


def sorted_vlan_count_distribution(counter: Counter[str]) -> dict[str, int]:
    return {
        key: counter[key]
        for key in sorted(
            counter,
            key=lambda item: (item == "all", int(item) if item != "all" else 0),
        )
    }


def counter_values(counter: Counter[str]) -> dict[str, int]:
    values = {
        key.replace("-", "_"): counter[key]
        for key in SUMMARY_COUNTER_KEYS
    }
    known = set(SUMMARY_COUNTER_KEYS)
    values.update(
        {
            key.replace("-", "_"): value
            for key, value in sorted(counter.items())
            if key not in known and value
        }
    )
    return values


def run(args: argparse.Namespace) -> dict[str, Any]:
    dataset_root = args.dataset_root.resolve()
    output_file = args.output_file.resolve()
    splits = ["train", "val"] if args.split == "all" else [args.split]
    file_results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    total_counters: Counter[str] = Counter()
    total_pair_distribution: Counter[str] = Counter()
    total_path_distribution: Counter[str] = Counter()
    total_hop_increase_distribution: Counter[str] = Counter()
    total_vlan_count_distribution: Counter[str] = Counter()
    by_split: dict[str, dict[str, Any]] = {}

    for split in splits:
        split_root = dataset_root / split
        files = link_analysis.iter_json_files(dataset_root, split)
        split_counters: Counter[str] = Counter()
        split_counters["input-files"] = len(files)
        pair_distribution: Counter[str] = Counter()
        path_distribution: Counter[str] = Counter()
        hop_increase_distribution: Counter[str] = Counter()
        vlan_count_distribution: Counter[str] = Counter()
        started_at = time.time()

        for index, path in enumerate(files, start=1):
            relative_path = path.relative_to(split_root).as_posix()
            try:
                graph = link_analysis.load_json_object(path)
                base_adjacency, vlan_adjacency, counters = build_graphs(
                    graph,
                    args.config_fields,
                    args.max_range_size,
                )
                path_stats = analyze_paths(base_adjacency, vlan_adjacency)
                split_counters.update(counters)
                split_counters["valid-files"] += 1
                if counters["vlan-eligible-unique-edges"]:
                    split_counters["files-with-vlan-eligible-links"] += 1
                else:
                    split_counters["files-without-vlan-eligible-links"] += 1
                if path_stats["max_vlan_shortest_path_length"] >= 2:
                    split_counters["files-with-vlan-multi-hop-paths"] += 1
                if path_stats["constrained_detour_node_pair_count"]:
                    split_counters["files-with-constrained-detours"] += 1

                split_counters["base-reachable-node-pairs"] += path_stats[
                    "base_reachable_node_pair_count"
                ]
                split_counters["vlan-reachable-node-pairs"] += path_stats[
                    "vlan_reachable_node_pair_count"
                ]
                split_counters["vlan-unreachable-node-pairs"] += path_stats[
                    "vlan_unreachable_node_pair_count"
                ]
                split_counters["vlan-shortest-paths"] += path_stats[
                    "vlan_shortest_path_count"
                ]
                split_counters["multiple-vlan-shortest-path-pairs"] += path_stats[
                    "multiple_vlan_shortest_path_pair_count"
                ]
                split_counters["same-length-node-pairs"] += path_stats[
                    "same_length_node_pair_count"
                ]
                split_counters["constrained-detour-node-pairs"] += path_stats[
                    "constrained_detour_node_pair_count"
                ]

                merge_distribution(
                    pair_distribution,
                    path_stats["node_pair_distance_distribution"],
                )
                merge_distribution(
                    path_distribution,
                    path_stats["shortest_path_length_distribution"],
                )
                merge_distribution(
                    hop_increase_distribution,
                    path_stats["hop_increase_distribution"],
                )
                merge_distribution(
                    vlan_count_distribution,
                    path_stats["path_vlan_count_distribution"],
                )
                file_results.append(
                    {
                        "split": split,
                        "source_file": path.name,
                        "source_relative_path": relative_path,
                        "base_unique_edge_count": counters["base-unique-edges"],
                        "vlan_eligible_unique_edge_count": counters[
                            "vlan-eligible-unique-edges"
                        ],
                        **path_stats,
                    }
                )
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
                split_counters["invalid-files"] += 1
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
                    f"[{split}] {index}/{len(files)}，VLAN 有效文件 "
                    f"{split_counters['files-with-vlan-eligible-links']}，"
                    f"约束绕行节点对 "
                    f"{split_counters['constrained-detour-node-pairs']}，"
                    f"预计剩余 {eta:.1f} 秒",
                    flush=True,
                )

        by_split[split] = {
            **counter_values(split_counters),
            "node_pair_distance_distribution": sorted_numeric_distribution(
                pair_distribution
            ),
            "shortest_path_length_distribution": sorted_numeric_distribution(
                path_distribution
            ),
            "hop_increase_distribution": sorted_numeric_distribution(
                hop_increase_distribution
            ),
            "path_vlan_count_distribution": sorted_vlan_count_distribution(
                vlan_count_distribution
            ),
        }
        total_counters.update(split_counters)
        total_pair_distribution.update(pair_distribution)
        total_path_distribution.update(path_distribution)
        total_hop_increase_distribution.update(hop_increase_distribution)
        total_vlan_count_distribution.update(vlan_count_distribution)

    result = {
        "dataset_root": str(dataset_root),
        "splits": splits,
        "config_fields": args.config_fields,
        "max_range_size": args.max_range_size,
        "analysis_rule": {
            "link": (
                "both LSW interfaces uniquely match and explicitly contain "
                "allow-through-vlan"
            ),
            "vlan_formats": "integer, comma list, inclusive range, nested list, all",
            "edge_support": "intersection of both endpoint VLAN sets",
            "path_support": "intersection of every edge VLAN set on the path",
            "path_selection": (
                "shortest path whose end-to-end VLAN intersection is non-empty"
            ),
            "all_semantics": "universal VLAN wildcard",
        },
        "summary": {
            **counter_values(total_counters),
            "node_pair_distance_distribution": sorted_numeric_distribution(
                total_pair_distribution
            ),
            "shortest_path_length_distribution": sorted_numeric_distribution(
                total_path_distribution
            ),
            "hop_increase_distribution": sorted_numeric_distribution(
                total_hop_increase_distribution
            ),
            "path_vlan_count_distribution": sorted_vlan_count_distribution(
                total_vlan_count_distribution
            ),
            "by_split": by_split,
        },
        "errors": errors,
        "files": file_results,
    }
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"分析完成，结果已写入: {output_file}")
    return result


def main() -> None:
    run(parse_args())


if __name__ == "__main__":
    main()
