#!/usr/bin/env python3
"""统计原始数据集中每张图的最大有限最短路长度。

“最大有限最短路长度”定义为：一张图中所有可达节点对的最短路径长度的最大值。
路径长度按链路跳数计算。对于不连通图，只比较各个可达节点对，不把不可达距离
视为无穷；存在有效节点但没有可达的不同节点对时，结果记为 0。

默认输入目录结构：

datasets/
  train/*.json
  val/*.json

脚本输出逐文件 CSV、长度分布 CSV 和汇总 JSON，不保存具体路径。
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, deque
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean, median
from typing import Any, Iterable


DEFAULT_DATASET_ROOT = Path("datasets")
DEFAULT_OUTPUT_DIR = Path("/tmp/max_finite_shortest_path_analysis")
DEFAULT_SPLITS = ("train", "val")
DEFAULT_PROGRESS_INTERVAL = 100


@dataclass
class GraphPathLengthRow:
    split: str
    file: str
    node_count: int
    valid_link_count: int
    directed: bool
    max_finite_shortest_path_length: int | None
    status: str
    detail: str = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "dataset_root",
        nargs="?",
        type=Path,
        default=DEFAULT_DATASET_ROOT,
        help=f"包含 train/val 的原始数据集根目录，默认: {DEFAULT_DATASET_ROOT}",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"统计结果输出目录，默认: {DEFAULT_OUTPUT_DIR}",
    )
    parser.add_argument(
        "--splits",
        nargs="+",
        default=list(DEFAULT_SPLITS),
        help="需要分析的数据划分，默认: train val",
    )
    parser.add_argument(
        "--progress-interval",
        type=int,
        default=DEFAULT_PROGRESS_INTERVAL,
        help=f"每处理多少个文件打印一次进度，默认: {DEFAULT_PROGRESS_INTERVAL}",
    )
    return parser.parse_args()


def iter_json_files(
    dataset_root: Path,
    splits: Iterable[str],
) -> Iterable[tuple[str, Path]]:
    for split in splits:
        split_dir = dataset_root / split
        if not split_dir.exists():
            continue
        for path in sorted(split_dir.rglob("*.json")):
            if path.is_file():
                yield split, path


def load_graph(path: Path) -> tuple[dict[str, Any] | None, str, str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - 坏文件需要记录并继续分析。
        return None, "bad_json", str(exc)
    if not isinstance(data, dict):
        return None, "graph_not_object", type(data).__name__
    return data, "", ""


def build_adjacency(
    graph: dict[str, Any],
) -> tuple[dict[str, set[str]], int, bool, str, str]:
    nodes = graph.get("nodes")
    if not isinstance(nodes, list):
        return {}, 0, bool(graph.get("directed", False)), "nodes_not_list", type(nodes).__name__

    node_ids: list[str] = []
    missing_id_count = 0
    duplicate_id_count = 0
    seen_ids: set[str] = set()
    for node in nodes:
        if not isinstance(node, dict) or node.get("id") is None:
            missing_id_count += 1
            continue
        node_id = str(node["id"])
        if node_id in seen_ids:
            duplicate_id_count += 1
            continue
        seen_ids.add(node_id)
        node_ids.append(node_id)

    if not node_ids:
        detail = (
            f"raw_node_count={len(nodes)}, missing_id_count={missing_id_count}, "
            f"duplicate_id_count={duplicate_id_count}"
        )
        return {}, 0, bool(graph.get("directed", False)), "no_valid_nodes", detail

    directed = bool(graph.get("directed", False))
    adjacency: dict[str, set[str]] = {node_id: set() for node_id in node_ids}
    valid_link_count = 0
    invalid_link_count = 0
    links = graph.get("links", [])
    if not isinstance(links, list):
        links = []
        invalid_link_count += 1

    for link in links:
        if not isinstance(link, dict):
            invalid_link_count += 1
            continue
        source = link.get("source")
        target = link.get("target")
        if source is None or target is None:
            invalid_link_count += 1
            continue
        source_id = str(source)
        target_id = str(target)
        if source_id not in adjacency or target_id not in adjacency:
            invalid_link_count += 1
            continue

        # 邻接表使用集合，因此重复链路不会影响最短路；valid_link_count 仍按输入记录数计。
        adjacency[source_id].add(target_id)
        if not directed:
            adjacency[target_id].add(source_id)
        valid_link_count += 1

    details: list[str] = []
    if missing_id_count:
        details.append(f"missing_id_nodes={missing_id_count}")
    if duplicate_id_count:
        details.append(f"duplicate_node_ids={duplicate_id_count}")
    if invalid_link_count:
        details.append(f"invalid_links={invalid_link_count}")
    return adjacency, valid_link_count, directed, "ok", "; ".join(details)


def maximum_finite_shortest_path_length(adjacency: dict[str, set[str]]) -> int:
    """对每个源节点执行 BFS，返回所有有限最短距离中的最大值。"""

    maximum_distance = 0
    for source in adjacency:
        distances = {source: 0}
        queue: deque[str] = deque([source])
        while queue:
            current = queue.popleft()
            next_distance = distances[current] + 1
            for neighbor in adjacency[current]:
                if neighbor in distances:
                    continue
                distances[neighbor] = next_distance
                if next_distance > maximum_distance:
                    maximum_distance = next_distance
                queue.append(neighbor)
    return maximum_distance


def analyze_file(dataset_root: Path, split: str, path: Path) -> GraphPathLengthRow:
    relative_file = str(path.relative_to(dataset_root))
    graph, status, detail = load_graph(path)
    if graph is None:
        return GraphPathLengthRow(
            split=split,
            file=relative_file,
            node_count=0,
            valid_link_count=0,
            directed=False,
            max_finite_shortest_path_length=None,
            status=status,
            detail=detail,
        )

    adjacency, valid_link_count, directed, status, detail = build_adjacency(graph)
    if status != "ok":
        return GraphPathLengthRow(
            split=split,
            file=relative_file,
            node_count=len(adjacency),
            valid_link_count=valid_link_count,
            directed=directed,
            max_finite_shortest_path_length=None,
            status=status,
            detail=detail,
        )

    return GraphPathLengthRow(
        split=split,
        file=relative_file,
        node_count=len(adjacency),
        valid_link_count=valid_link_count,
        directed=directed,
        max_finite_shortest_path_length=maximum_finite_shortest_path_length(adjacency),
        status="ok",
        detail=detail,
    )


def number_summary(values: list[int]) -> dict[str, int | float | None]:
    if not values:
        return {
            "count": 0,
            "min": None,
            "max": None,
            "mean": None,
            "median": None,
        }
    return {
        "count": len(values),
        "min": min(values),
        "max": max(values),
        "mean": round(mean(values), 4),
        "median": median(values),
    }


def build_summary(
    rows: list[GraphPathLengthRow],
    dataset_root: Path,
    output_dir: Path,
    splits: list[str],
) -> dict[str, Any]:
    valid_rows = [row for row in rows if row.status == "ok"]
    summary: dict[str, Any] = {
        "definition": "maximum finite shortest-path length in link hops",
        "dataset_root": str(dataset_root),
        "output_dir": str(output_dir),
        "requested_splits": splits,
        "missing_split_dirs": [
            split for split in splits if not (dataset_root / split).is_dir()
        ],
        "files": len(rows),
        "status_counts": dict(sorted(Counter(row.status for row in rows).items())),
        "max_finite_shortest_path_length": number_summary(
            [
                row.max_finite_shortest_path_length
                for row in valid_rows
                if row.max_finite_shortest_path_length is not None
            ]
        ),
        "splits": {},
        "outputs": {
            "per_graph_csv": "graph_max_finite_shortest_path.csv",
            "distribution_csv": "max_finite_shortest_path_distribution.csv",
            "summary_json": "max_finite_shortest_path_summary.json",
        },
    }
    for split in splits:
        split_rows = [row for row in rows if row.split == split]
        split_values = [
            row.max_finite_shortest_path_length
            for row in split_rows
            if row.status == "ok" and row.max_finite_shortest_path_length is not None
        ]
        summary["splits"][split] = {
            "files": len(split_rows),
            "status_counts": dict(
                sorted(Counter(row.status for row in split_rows).items())
            ),
            "max_finite_shortest_path_length": number_summary(split_values),
        }
    return summary


def write_per_graph_csv(path: Path, rows: list[GraphPathLengthRow]) -> None:
    fieldnames = [field.name for field in GraphPathLengthRow.__dataclass_fields__.values()]
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def write_distribution_csv(path: Path, rows: list[GraphPathLengthRow]) -> None:
    fieldnames = ["scope", "max_finite_shortest_path_length", "graph_count", "ratio"]
    scopes = ["all", *sorted({row.split for row in rows})]
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for scope in scopes:
            scope_rows = [
                row
                for row in rows
                if row.status == "ok" and (scope == "all" or row.split == scope)
            ]
            counts = Counter(
                row.max_finite_shortest_path_length
                for row in scope_rows
                if row.max_finite_shortest_path_length is not None
            )
            total = sum(counts.values())
            for length in sorted(counts):
                count = counts[length]
                writer.writerow(
                    {
                        "scope": scope,
                        "max_finite_shortest_path_length": length,
                        "graph_count": count,
                        "ratio": round(count / total, 8) if total else 0.0,
                    }
                )


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    files = list(iter_json_files(args.dataset_root, args.splits))
    rows: list[GraphPathLengthRow] = []
    print(f"found {len(files)} json files")
    for index, (split, path) in enumerate(files, start=1):
        rows.append(analyze_file(args.dataset_root, split, path))
        if args.progress_interval > 0 and index % args.progress_interval == 0:
            status_counts = Counter(row.status for row in rows)
            print(
                f"processed {index}/{len(files)}, "
                f"ok={status_counts.get('ok', 0)}, "
                f"errors={index - status_counts.get('ok', 0)}"
            )

    write_per_graph_csv(
        args.output_dir / "graph_max_finite_shortest_path.csv",
        rows,
    )
    write_distribution_csv(
        args.output_dir / "max_finite_shortest_path_distribution.csv",
        rows,
    )
    summary = build_summary(
        rows,
        args.dataset_root,
        args.output_dir,
        args.splits,
    )
    (args.output_dir / "max_finite_shortest_path_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
