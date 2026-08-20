#!/usr/bin/env python3
"""统计双端接口均含 allow-through-vlan 的 LSW 链路路径分布。"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter, deque
from pathlib import Path
from typing import Any

import analyze_lsw_link_interfaces as link_analysis


DEFAULT_DATASET_ROOT = Path("datasets")
DEFAULT_OUTPUT_FILE = Path("/tmp/lsw_allow_vlan_path_distribution.json")
DEFAULT_SPLIT = "all"
DEFAULT_CONFIG_FIELDS = ("configs",)
DEFAULT_PROGRESS_INTERVAL = 100

SUMMARY_COUNTER_KEYS = (
    "input-files",
    "valid-files",
    "invalid-files",
    "files-with-eligible-lsw-links",
    "files-without-eligible-lsw-links",
    "files-with-multi-hop-paths",
    "input-links",
    "self-loop-links",
    "lsw-to-lsw-links",
    "links-with-both-interfaces-matched",
    "links-with-incomplete-interface-match",
    "links-without-bilateral-allow-through-vlan",
    "allow-through-vlan-missing-at-both-ends",
    "allow-through-vlan-missing-at-left-end",
    "allow-through-vlan-missing-at-right-end",
    "eligible-link-records",
    "duplicate-eligible-edges",
    "eligible-unique-edges",
    "reachable-node-pairs",
    "shortest-paths",
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
    if args.progress_interval < 0:
        parser.error("--progress-interval 不能小于 0")
    return args


def build_eligible_graph(
    graph: dict[str, Any],
    config_fields: list[str],
) -> tuple[dict[str, set[str]], Counter[str]]:
    """构建满足接口匹配和 allow-through-vlan 条件的无向 LSW 子图。"""

    adjacency: dict[str, set[str]] = {}
    counters: Counter[str] = Counter()
    nodes = graph.get("nodes")
    links = graph.get("links")
    if not isinstance(nodes, list):
        counters["files-with-nodes-not-list"] += 1
        return adjacency, counters
    if not isinstance(links, list):
        counters["files-with-links-not-list"] += 1
        return adjacency, counters

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
    unique_edges: set[tuple[str, str]] = set()
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
            counters[
                f"interface-match:left={left_status},right={right_status}"
            ] += 1
            continue

        counters["links-with-both-interfaces-matched"] += 1
        left_interface = left_matches[0]["interface_config"]
        right_interface = right_matches[0]["interface_config"]
        left_has_allow = "allow-through-vlan" in left_interface
        right_has_allow = "allow-through-vlan" in right_interface
        if not left_has_allow or not right_has_allow:
            counters["links-without-bilateral-allow-through-vlan"] += 1
            if not left_has_allow and not right_has_allow:
                counters["allow-through-vlan-missing-at-both-ends"] += 1
            elif not left_has_allow:
                counters["allow-through-vlan-missing-at-left-end"] += 1
            else:
                counters["allow-through-vlan-missing-at-right-end"] += 1
            continue

        counters["eligible-link-records"] += 1
        edge = tuple(sorted((source_id or "", target_id or "")))
        if edge in unique_edges:
            counters["duplicate-eligible-edges"] += 1
            continue
        unique_edges.add(edge)
        adjacency.setdefault(edge[0], set()).add(edge[1])
        adjacency.setdefault(edge[1], set()).add(edge[0])

    counters["eligible-unique-edges"] = len(unique_edges)
    counters["eligible-lsw-nodes"] = len(adjacency)
    return adjacency, counters


def component_sizes(adjacency: dict[str, set[str]]) -> list[int]:
    remaining = set(adjacency)
    sizes: list[int] = []
    while remaining:
        start = min(remaining)
        queue = deque([start])
        remaining.remove(start)
        size = 0
        while queue:
            node = queue.popleft()
            size += 1
            for neighbor in adjacency[node]:
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    queue.append(neighbor)
        sizes.append(size)
    return sorted(sizes, reverse=True)


def shortest_path_statistics(
    adjacency: dict[str, set[str]],
) -> dict[str, Any]:
    """按无序节点对统计最短距离及全部等长最短路径数量。"""

    nodes = sorted(adjacency)
    pair_distance_distribution: Counter[int] = Counter()
    path_length_distribution: Counter[int] = Counter()
    reachable_pairs = 0
    shortest_paths = 0
    multiple_path_pairs = 0
    max_shortest_paths_per_pair = 0
    max_distance = 0

    for source_index, source in enumerate(nodes):
        distances = {source: 0}
        path_counts = {source: 1}
        queue = deque([source])
        while queue:
            node = queue.popleft()
            next_distance = distances[node] + 1
            for neighbor in adjacency[node]:
                if neighbor not in distances:
                    distances[neighbor] = next_distance
                    path_counts[neighbor] = path_counts[node]
                    queue.append(neighbor)
                elif distances[neighbor] == next_distance:
                    path_counts[neighbor] += path_counts[node]

        for target in nodes[source_index + 1:]:
            if target not in distances:
                continue
            distance = distances[target]
            path_count = path_counts[target]
            reachable_pairs += 1
            shortest_paths += path_count
            pair_distance_distribution[distance] += 1
            path_length_distribution[distance] += path_count
            if path_count > 1:
                multiple_path_pairs += 1
            max_shortest_paths_per_pair = max(
                max_shortest_paths_per_pair,
                path_count,
            )
            max_distance = max(max_distance, distance)

    return {
        "connected_component_count": len(component_sizes(adjacency)),
        "connected_component_sizes": component_sizes(adjacency),
        "reachable_node_pair_count": reachable_pairs,
        "shortest_path_count": shortest_paths,
        "multiple_shortest_path_pair_count": multiple_path_pairs,
        "max_shortest_paths_per_pair": max_shortest_paths_per_pair,
        "max_shortest_path_length": max_distance,
        "node_pair_distance_distribution": {
            str(length): pair_distance_distribution[length]
            for length in sorted(pair_distance_distribution)
        },
        "shortest_path_length_distribution": {
            str(length): path_length_distribution[length]
            for length in sorted(path_length_distribution)
        },
    }


def merge_distribution(target: Counter[int], source: dict[str, int]) -> None:
    for key, count in source.items():
        target[int(key)] += count


def sorted_distribution(counter: Counter[int]) -> dict[str, int]:
    return {str(key): counter[key] for key in sorted(counter)}


def counter_values(counter: Counter[str]) -> dict[str, int]:
    values = {
        key.replace("-", "_"): counter[key]
        for key in SUMMARY_COUNTER_KEYS
    }
    known_keys = set(SUMMARY_COUNTER_KEYS)
    values.update(
        {
            key.replace("-", "_"): value
            for key, value in sorted(counter.items())
            if key not in known_keys and value
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
    total_pair_distribution: Counter[int] = Counter()
    total_path_distribution: Counter[int] = Counter()
    max_length_distribution: Counter[int] = Counter()
    by_split: dict[str, dict[str, Any]] = {}

    for split in splits:
        split_root = dataset_root / split
        files = link_analysis.iter_json_files(dataset_root, split)
        split_counters: Counter[str] = Counter()
        split_pair_distribution: Counter[int] = Counter()
        split_path_distribution: Counter[int] = Counter()
        split_max_length_distribution: Counter[int] = Counter()
        split_counters["input-files"] = len(files)
        started_at = time.time()

        for index, path in enumerate(files, start=1):
            relative_path = path.relative_to(split_root).as_posix()
            try:
                graph = link_analysis.load_json_object(path)
                adjacency, counters = build_eligible_graph(
                    graph,
                    args.config_fields,
                )
                path_stats = shortest_path_statistics(adjacency)
                split_counters.update(counters)
                split_counters["valid-files"] += 1
                if counters["eligible-unique-edges"]:
                    split_counters["files-with-eligible-lsw-links"] += 1
                else:
                    split_counters["files-without-eligible-lsw-links"] += 1
                if path_stats["max_shortest_path_length"] >= 2:
                    split_counters["files-with-multi-hop-paths"] += 1

                split_counters["reachable-node-pairs"] += path_stats[
                    "reachable_node_pair_count"
                ]
                split_counters["shortest-paths"] += path_stats[
                    "shortest_path_count"
                ]
                merge_distribution(
                    split_pair_distribution,
                    path_stats["node_pair_distance_distribution"],
                )
                merge_distribution(
                    split_path_distribution,
                    path_stats["shortest_path_length_distribution"],
                )
                split_max_length_distribution[
                    path_stats["max_shortest_path_length"]
                ] += 1
                file_results.append(
                    {
                        "split": split,
                        "source_file": path.name,
                        "source_relative_path": relative_path,
                        "eligible_lsw_node_count": counters["eligible-lsw-nodes"],
                        "eligible_link_record_count": counters[
                            "eligible-link-records"
                        ],
                        "eligible_unique_edge_count": counters[
                            "eligible-unique-edges"
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
                    f"[{split}] {index}/{len(files)}，满足条件文件 "
                    f"{split_counters['files-with-eligible-lsw-links']}，"
                    f"最短路径 {split_counters['shortest-paths']}，"
                    f"预计剩余 {eta:.1f} 秒",
                    flush=True,
                )

        by_split[split] = {
            **counter_values(split_counters),
            "node_pair_distance_distribution": sorted_distribution(
                split_pair_distribution
            ),
            "shortest_path_length_distribution": sorted_distribution(
                split_path_distribution
            ),
            "max_shortest_path_length_distribution": sorted_distribution(
                split_max_length_distribution
            ),
        }
        total_counters.update(split_counters)
        total_pair_distribution.update(split_pair_distribution)
        total_path_distribution.update(split_path_distribution)
        max_length_distribution.update(split_max_length_distribution)

    result = {
        "dataset_root": str(dataset_root),
        "splits": splits,
        "config_fields": args.config_fields,
        "eligibility_rule": {
            "node_type": "both endpoint devices.TYPE values equal LSW",
            "self_loop": "source must differ from target",
            "interface_match": (
                "LEFTPORT and RIGHTPORT each exactly match one "
                "lsw-interface[].interface-name"
            ),
            "vlan_field": (
                "both matched lsw-interface objects explicitly contain "
                "allow-through-vlan"
            ),
            "graph": "undirected graph with duplicate edges collapsed",
            "path": "all shortest paths between unordered reachable node pairs",
        },
        "summary": {
            **counter_values(total_counters),
            "node_pair_distance_distribution": sorted_distribution(
                total_pair_distribution
            ),
            "shortest_path_length_distribution": sorted_distribution(
                total_path_distribution
            ),
            "max_shortest_path_length_distribution": sorted_distribution(
                max_length_distribution
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
