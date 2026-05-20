#!/usr/bin/env python3
"""Analyze graph JSON datasets for node config generation.

The script expects a dataset root containing train/ and val/ folders. Each JSON
file should describe one graph with nodes and links. It intentionally uses only
the Python standard library so it can run on the data host without extra setup.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean
from typing import Any, Iterable


# Local defaults. Edit these paths on the data host if you want to run the
# script without passing paths on the command line.
DEFAULT_DATASET_ROOT = Path("/data/my_dataset")
DEFAULT_OUTPUT_DIR = Path("/tmp/config_analysis")


GROUP_FIELDS = {
    "devices.TYPE": ("devices", "TYPE"),
    "devices.MODEL": ("devices", "MODEL"),
    "devices.MANUFACTURER": ("devices", "MANUFACTURER"),
    "devices.SUBTYPE": ("devices", "SUBTYPE"),
    "topologyNode.DEVICEROLE": ("topologyNode", "DEVICEROLE"),
    "topologyNode.NODECLASS": ("topologyNode", "NODECLASS"),
}


@dataclass
class PathStat:
    occurrences: int = 0
    nodes_present: int = 0
    type_counts: Counter[str] = field(default_factory=Counter)
    value_counts: Counter[str] = field(default_factory=Counter)


@dataclass
class GroupStat:
    nodes: int = 0
    config_nodes: int = 0
    template_counts: Counter[int] = field(default_factory=Counter)


def type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int) and not isinstance(value, bool):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "dict"
    return type(value).__name__


def stable_value(value: Any, max_len: int = 160) -> str:
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    else:
        text = str(value)
    return text if len(text) <= max_len else text[: max_len - 3] + "..."


def iter_json_files(dataset_root: Path, splits: Iterable[str]) -> Iterable[tuple[str, Path]]:
    for split in splits:
        split_dir = dataset_root / split
        if not split_dir.exists():
            continue
        for path in sorted(split_dir.rglob("*.json")):
            if path.is_file():
                yield split, path


def flatten_leaf_paths(value: Any, prefix: str = "") -> list[tuple[str, Any]]:
    """Return leaf paths with [] used as a wildcard for list elements."""
    if isinstance(value, dict):
        if not value:
            return [(prefix, value)] if prefix else []
        leaves: list[tuple[str, Any]] = []
        for key, child in value.items():
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            leaves.extend(flatten_leaf_paths(child, child_prefix))
        return leaves
    if isinstance(value, list):
        if not value:
            return [(f"{prefix}[]", value)] if prefix else []
        leaves = []
        list_prefix = f"{prefix}[]" if prefix else "[]"
        for child in value:
            leaves.extend(flatten_leaf_paths(child, list_prefix))
        return leaves
    return [(prefix, value)] if prefix else []


def flatten_config_leaf_paths(config: Any) -> list[tuple[str, Any]]:
    """Flatten config while treating the root config list as a container."""
    if isinstance(config, list):
        leaves: list[tuple[str, Any]] = []
        for item in config:
            leaves.extend(flatten_leaf_paths(item))
        return leaves
    return flatten_leaf_paths(config)


def update_path_stats(stats: dict[str, PathStat], leaves: list[tuple[str, Any]]) -> set[str]:
    paths_seen = {path for path, _ in leaves}
    for path in paths_seen:
        stats[path].nodes_present += 1
    for path, value in leaves:
        stat = stats[path]
        stat.occurrences += 1
        stat.type_counts[type_name(value)] += 1
        stat.value_counts[stable_value(value)] += 1
    return paths_seen


def nested_get(data: dict[str, Any], keys: tuple[str, str]) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def config_top_keys(config: Any) -> Counter[str]:
    keys: Counter[str] = Counter()
    items = config if isinstance(config, list) else [config]
    for item in items:
        if isinstance(item, dict):
            keys.update(str(key) for key in item.keys())
    return keys


def graph_degrees(nodes: list[dict[str, Any]], links: list[dict[str, Any]]) -> Counter[str]:
    ids = {str(node.get("id", "")) for node in nodes}
    degrees: Counter[str] = Counter({node_id: 0 for node_id in ids})
    for link in links:
        source = str(link.get("source", ""))
        target = str(link.get("target", ""))
        if source in degrees:
            degrees[source] += 1
        if target in degrees and target != source:
            degrees[target] += 1
    return degrees


def connected_components(nodes: list[dict[str, Any]], links: list[dict[str, Any]]) -> int:
    ids = {str(node.get("id", "")) for node in nodes}
    adjacency: dict[str, set[str]] = {node_id: set() for node_id in ids}
    for link in links:
        source = str(link.get("source", ""))
        target = str(link.get("target", ""))
        if source in adjacency and target in adjacency:
            adjacency[source].add(target)
            adjacency[target].add(source)

    seen: set[str] = set()
    components = 0
    for node_id in ids:
        if node_id in seen:
            continue
        components += 1
        stack = [node_id]
        seen.add(node_id)
        while stack:
            current = stack.pop()
            for neighbor in adjacency[current]:
                if neighbor not in seen:
                    seen.add(neighbor)
                    stack.append(neighbor)
    return components


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def counter_json(counter: Counter[Any], limit: int | None = None) -> dict[str, int]:
    items = counter.most_common(limit)
    return {str(key): count for key, count in items}


def summarize_numbers(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "min": None, "max": None, "mean": None}
    return {
        "count": len(values),
        "min": min(values),
        "max": max(values),
        "mean": round(mean(values), 4),
    }


def analyze(dataset_root: Path, output_dir: Path, splits: list[str]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    summary: dict[str, Any] = {
        "dataset_root": str(dataset_root),
        "splits": {split: {"files": 0, "bad_json": 0, "graphs": 0, "nodes": 0, "links": 0} for split in splits},
        "totals": {"files": 0, "bad_json": 0, "graphs": 0, "nodes": 0, "links": 0, "config_nodes": 0},
        "missing_split_dirs": [split for split in splits if not (dataset_root / split).exists()],
    }

    issues: list[dict[str, Any]] = []
    graph_rows: list[dict[str, Any]] = []
    node_field_stats: dict[str, PathStat] = defaultdict(PathStat)
    link_field_stats: dict[str, PathStat] = defaultdict(PathStat)
    config_path_stats: dict[str, PathStat] = defaultdict(PathStat)
    template_counts: Counter[tuple[str, ...]] = Counter()
    template_ids: dict[tuple[str, ...], int] = {}
    node_template_ids: list[int | None] = []
    top_config_keys: Counter[str] = Counter()
    group_stats: dict[tuple[str, str], GroupStat] = defaultdict(GroupStat)
    graph_node_counts: list[int] = []
    graph_link_counts: list[int] = []
    graph_config_node_counts: list[int] = []

    for split, path in iter_json_files(dataset_root, splits):
        split_summary = summary["splits"][split]
        split_summary["files"] += 1
        summary["totals"]["files"] += 1

        try:
            graph = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - record parse failures and continue.
            split_summary["bad_json"] += 1
            summary["totals"]["bad_json"] += 1
            issues.append({"severity": "error", "split": split, "file": str(path), "issue": "bad_json", "detail": str(exc)})
            continue

        nodes = graph.get("nodes", [])
        links = graph.get("links", [])
        if not isinstance(nodes, list):
            issues.append({"severity": "error", "split": split, "file": str(path), "issue": "nodes_not_list"})
            nodes = []
        if not isinstance(links, list):
            issues.append({"severity": "error", "split": split, "file": str(path), "issue": "links_not_list"})
            links = []

        split_summary["graphs"] += 1
        summary["totals"]["graphs"] += 1
        split_summary["nodes"] += len(nodes)
        split_summary["links"] += len(links)
        summary["totals"]["nodes"] += len(nodes)
        summary["totals"]["links"] += len(links)
        graph_node_counts.append(len(nodes))
        graph_link_counts.append(len(links))

        node_ids = [str(node.get("id", "")) for node in nodes if isinstance(node, dict)]
        id_counts = Counter(node_ids)
        duplicate_ids = [node_id for node_id, count in id_counts.items() if count > 1]
        if duplicate_ids:
            issues.append({"severity": "warning", "split": split, "file": str(path), "issue": "duplicate_node_ids", "ids": duplicate_ids[:20]})

        node_id_set = set(node_ids)
        invalid_links = 0
        self_loops = 0
        edge_counts: Counter[tuple[str, str]] = Counter()
        for link in links:
            if not isinstance(link, dict):
                issues.append({"severity": "warning", "split": split, "file": str(path), "issue": "link_not_object"})
                continue
            source = str(link.get("source", ""))
            target = str(link.get("target", ""))
            if source not in node_id_set or target not in node_id_set:
                invalid_links += 1
            if source == target:
                self_loops += 1
            edge_counts[tuple(sorted((source, target)))] += 1
            update_path_stats(link_field_stats, flatten_leaf_paths(link))
        duplicate_edges = sum(count - 1 for count in edge_counts.values() if count > 1)
        if invalid_links:
            issues.append({"severity": "error", "split": split, "file": str(path), "issue": "link_endpoint_missing", "count": invalid_links})

        degrees = graph_degrees(nodes, links)
        degree_values = list(degrees.values())
        config_nodes = 0

        for index, node in enumerate(nodes):
            if not isinstance(node, dict):
                issues.append({"severity": "warning", "split": split, "file": str(path), "issue": "node_not_object", "node_index": index})
                node_template_ids.append(None)
                continue

            node_without_config = {key: value for key, value in node.items() if key != "config"}
            update_path_stats(node_field_stats, flatten_leaf_paths(node_without_config))

            config = node.get("config")
            has_config = config not in (None, [], {})
            template_id: int | None = None
            if has_config:
                config_nodes += 1
                summary["totals"]["config_nodes"] += 1
                if not isinstance(config, list):
                    issues.append({"severity": "warning", "split": split, "file": str(path), "issue": "config_not_list", "node_id": node.get("id")})
                top_config_keys.update(config_top_keys(config))
                config_paths = update_path_stats(config_path_stats, flatten_config_leaf_paths(config))
                template = tuple(sorted(config_paths))
                template_counts[template] += 1
                if template not in template_ids:
                    template_ids[template] = len(template_ids) + 1
                template_id = template_ids[template]
            node_template_ids.append(template_id)

            for group_name, keys in GROUP_FIELDS.items():
                value = nested_get(node, keys)
                value_text = "<missing>" if value is None or value == "" else stable_value(value)
                stat = group_stats[(group_name, value_text)]
                stat.nodes += 1
                if has_config:
                    stat.config_nodes += 1
                    if template_id is not None:
                        stat.template_counts[template_id] += 1

        graph_config_node_counts.append(config_nodes)
        graph_rows.append(
            {
                "split": split,
                "file": str(path.relative_to(dataset_root)),
                "directed": graph.get("directed"),
                "multigraph": graph.get("multigraph"),
                "nodes": len(nodes),
                "links": len(links),
                "config_nodes": config_nodes,
                "config_node_ratio": round(config_nodes / len(nodes), 6) if nodes else 0,
                "isolated_nodes": sum(1 for degree in degree_values if degree == 0),
                "avg_degree": round(mean(degree_values), 6) if degree_values else 0,
                "max_degree": max(degree_values) if degree_values else 0,
                "connected_components": connected_components(nodes, links),
                "invalid_links": invalid_links,
                "self_loops": self_loops,
                "duplicate_edges": duplicate_edges,
            }
        )

    summary["graph_size"] = {
        "nodes_per_graph": summarize_numbers(graph_node_counts),
        "links_per_graph": summarize_numbers(graph_link_counts),
        "config_nodes_per_graph": summarize_numbers(graph_config_node_counts),
    }
    summary["top_config_keys"] = counter_json(top_config_keys, 100)
    summary["unique_config_templates"] = len(template_counts)

    template_rows = []
    for template, count in template_counts.most_common():
        template_id = template_ids[template]
        template_rows.append(
            {
                "template_id": template_id,
                "node_count": count,
                "path_count": len(template),
                "paths": json.dumps(list(template), ensure_ascii=False),
            }
        )

    def path_rows(stats: dict[str, PathStat], total_nodes: int) -> list[dict[str, Any]]:
        rows = []
        for path, stat in sorted(stats.items(), key=lambda item: (-item[1].nodes_present, item[0])):
            rows.append(
                {
                    "path": path,
                    "nodes_present": stat.nodes_present,
                    "node_presence_ratio": round(stat.nodes_present / total_nodes, 6) if total_nodes else 0,
                    "occurrences": stat.occurrences,
                    "type_counts": json.dumps(counter_json(stat.type_counts), ensure_ascii=False),
                    "top_values": json.dumps(counter_json(stat.value_counts, 20), ensure_ascii=False),
                    "unique_values": len(stat.value_counts),
                }
            )
        return rows

    total_nodes = summary["totals"]["nodes"]
    write_json(output_dir / "dataset_summary.json", summary)
    write_jsonl(output_dir / "data_quality_issues.jsonl", issues)
    write_csv(
        output_dir / "graph_stats.csv",
        [
            "split",
            "file",
            "directed",
            "multigraph",
            "nodes",
            "links",
            "config_nodes",
            "config_node_ratio",
            "isolated_nodes",
            "avg_degree",
            "max_degree",
            "connected_components",
            "invalid_links",
            "self_loops",
            "duplicate_edges",
        ],
        graph_rows,
    )
    write_csv(
        output_dir / "node_field_stats.csv",
        ["path", "nodes_present", "node_presence_ratio", "occurrences", "type_counts", "top_values", "unique_values"],
        path_rows(node_field_stats, total_nodes),
    )
    write_csv(
        output_dir / "link_field_stats.csv",
        ["path", "nodes_present", "node_presence_ratio", "occurrences", "type_counts", "top_values", "unique_values"],
        path_rows(link_field_stats, summary["totals"]["links"]),
    )
    write_csv(
        output_dir / "config_path_stats.csv",
        ["path", "nodes_present", "node_presence_ratio", "occurrences", "type_counts", "top_values", "unique_values"],
        path_rows(config_path_stats, total_nodes),
    )
    write_csv(output_dir / "config_template_stats.csv", ["template_id", "node_count", "path_count", "paths"], template_rows)

    group_rows = []
    for (group_name, value), stat in sorted(group_stats.items(), key=lambda item: (item[0][0], -item[1].nodes, item[0][1])):
        top_template_id, top_template_count = (None, 0)
        if stat.template_counts:
            top_template_id, top_template_count = stat.template_counts.most_common(1)[0]
        group_rows.append(
            {
                "group": group_name,
                "value": value,
                "nodes": stat.nodes,
                "config_nodes": stat.config_nodes,
                "config_node_ratio": round(stat.config_nodes / stat.nodes, 6) if stat.nodes else 0,
                "top_template_id": top_template_id or "",
                "top_template_count": top_template_count,
                "template_counts": json.dumps(counter_json(stat.template_counts, 20), ensure_ascii=False),
            }
        )
    write_csv(
        output_dir / "group_config_stats.csv",
        ["group", "value", "nodes", "config_nodes", "config_node_ratio", "top_template_id", "top_template_count", "template_counts"],
        group_rows,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze train/val graph JSON datasets for config generation.")
    parser.add_argument(
        "dataset_root",
        nargs="?",
        type=Path,
        default=DEFAULT_DATASET_ROOT,
        help=f"Dataset root containing train/ and val/ directories. Default: {DEFAULT_DATASET_ROOT}",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Directory for generated reports. Default: {DEFAULT_OUTPUT_DIR}",
    )
    parser.add_argument("--splits", nargs="+", default=["train", "val"], help="Split directory names to analyze.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    analyze(args.dataset_root, args.output_dir, args.splits)
    print(f"Wrote analysis reports to {args.output_dir}")


if __name__ == "__main__":
    main()
