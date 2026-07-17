#!/usr/bin/env python3
"""统计原始数据集中每张图的最大有限最短路长度。

“最大有限最短路长度”定义为：一张图中所有可达节点对的最短路径长度的最大值。
路径长度按链路跳数计算。对于不连通图，只比较可达节点对；存在有效节点但没有
任何有效链路时，结果记为 0。

输出格式参考 link_field_stats.py：只生成一个格式化 JSON 文件，顶层包含全局
汇总 summary 和逐图结果 per_file，并在终端打印进度、耗时、ETA 和长度分布。
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter, deque
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any, Dict, Iterable, List, Tuple


DEFAULT_DATASET_ROOT = Path("datasets")
DEFAULT_OUTPUT_DIR = Path("/tmp/max_finite_shortest_path_analysis")
DEFAULT_PROGRESS_INTERVAL = 50
OUTPUT_FILE_NAME = "max_finite_shortest_path_statistics.json"


@dataclass
class GraphPathLengthResult:
    split: str
    source_file: str
    node_count: int
    link_count: int
    directed: bool
    max_finite_shortest_path_length: int | None
    status: str
    detail: str = ""


def iter_json_files(
    dataset_root: Path,
    splits: Iterable[str],
) -> Iterable[Tuple[str, Path]]:
    """按 split 递归枚举 JSON 文件。"""

    for split in splits:
        split_dir = dataset_root / split
        if not split_dir.exists():
            continue
        for path in sorted(split_dir.rglob("*.json")):
            if path.is_file():
                yield split, path


def list_split_json_files(dataset_root: Path, split: str) -> List[Path]:
    return [path for _, path in iter_json_files(dataset_root, [split])]


def load_graph(path: Path) -> Tuple[Dict[str, Any] | None, str, str]:
    try:
        graph = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - 坏文件需要记录并继续分析。
        return None, "bad_json", str(exc)
    if not isinstance(graph, dict):
        return None, "graph_not_object", type(graph).__name__
    return graph, "", ""


def build_adjacency(
    graph: Dict[str, Any],
) -> Tuple[Dict[str, set[str]], int, bool, str, str]:
    """根据 nodes 和 links 构造邻接表，并返回数据质量状态。"""

    nodes = graph.get("nodes")
    if not isinstance(nodes, list):
        return (
            {},
            0,
            bool(graph.get("directed", False)),
            "nodes_not_list",
            type(nodes).__name__,
        )

    node_ids: List[str] = []
    seen_ids: set[str] = set()
    missing_id_count = 0
    duplicate_id_count = 0
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
    adjacency: Dict[str, set[str]] = {node_id: set() for node_id in node_ids}
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

        adjacency[source_id].add(target_id)
        if not directed:
            adjacency[target_id].add(source_id)
        valid_link_count += 1

    details: List[str] = []
    if missing_id_count:
        details.append(f"missing_id_nodes={missing_id_count}")
    if duplicate_id_count:
        details.append(f"duplicate_node_ids={duplicate_id_count}")
    if invalid_link_count:
        details.append(f"invalid_links={invalid_link_count}")
    return adjacency, valid_link_count, directed, "ok", "; ".join(details)


def maximum_finite_shortest_path_length(adjacency: Dict[str, set[str]]) -> int:
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
                maximum_distance = max(maximum_distance, next_distance)
                queue.append(neighbor)
    return maximum_distance


def analyze_file(
    dataset_root: Path,
    split: str,
    path: Path,
) -> GraphPathLengthResult:
    source_file = str(path.relative_to(dataset_root))
    graph, status, detail = load_graph(path)
    if graph is None:
        return GraphPathLengthResult(
            split=split,
            source_file=source_file,
            node_count=0,
            link_count=0,
            directed=False,
            max_finite_shortest_path_length=None,
            status=status,
            detail=detail,
        )

    adjacency, link_count, directed, status, detail = build_adjacency(graph)
    if status != "ok":
        return GraphPathLengthResult(
            split=split,
            source_file=source_file,
            node_count=len(adjacency),
            link_count=link_count,
            directed=directed,
            max_finite_shortest_path_length=None,
            status=status,
            detail=detail,
        )

    return GraphPathLengthResult(
        split=split,
        source_file=source_file,
        node_count=len(adjacency),
        link_count=link_count,
        directed=directed,
        max_finite_shortest_path_length=maximum_finite_shortest_path_length(
            adjacency
        ),
        status="ok",
        detail=detail,
    )


def number_summary(values: List[int]) -> Dict[str, int | float | None]:
    if not values:
        return {"count": 0, "min": None, "max": None, "mean": None}
    return {
        "count": len(values),
        "min": min(values),
        "max": max(values),
        "mean": round(mean(values), 4),
    }


def value_distribution(values: List[int]) -> Dict[str, Dict[str, int | float]]:
    counts = Counter(values)
    total = len(values)
    return {
        str(length): {
            "count": count,
            "percentage": round(count / total * 100, 2) if total else 0.0,
        }
        for length, count in sorted(counts.items())
    }


def build_scope_statistics(results: List[GraphPathLengthResult]) -> Dict[str, Any]:
    valid_results = [result for result in results if result.status == "ok"]
    values = [
        result.max_finite_shortest_path_length
        for result in valid_results
        if result.max_finite_shortest_path_length is not None
    ]
    return {
        "input_files": len(results),
        "analyzed_graphs": len(valid_results),
        "skipped_files": len(results) - len(valid_results),
        "length_summary": number_summary(values),
        "length_distribution": value_distribution(values),
    }


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def terminal_bar(count: int, total: int) -> str:
    percentage = count / total * 100 if total else 0.0
    bar_length = max(1, int(percentage / 2)) if count else 0
    return "█" * bar_length


def print_terminal_summary(results: List[GraphPathLengthResult]) -> None:
    valid_results = [result for result in results if result.status == "ok"]
    values = [
        result.max_finite_shortest_path_length
        for result in valid_results
        if result.max_finite_shortest_path_length is not None
    ]
    summary = number_summary(values)
    counts = Counter(values)

    print(f"\n{'=' * 60}")
    print(f"统计完成：{len(valid_results)} 张图")
    print(f"{'=' * 60}")
    print("\n--- 最大有限最短路长度汇总 ---")
    print(f"  count: {summary['count']}")
    print(f"  min:   {summary['min']}")
    print(f"  max:   {summary['max']}")
    print(f"  mean:  {summary['mean']}")

    print("\n--- 最大有限最短路长度分布 ---")
    for length, count in sorted(counts.items()):
        percentage = count / len(values) * 100 if values else 0.0
        print(
            f"  {length:>5}  {terminal_bar(count, len(values))}  "
            f"{count} ({percentage:.2f}%)"
        )

    skipped_files = len(results) - len(valid_results)
    if skipped_files:
        print(f"\n跳过 {skipped_files} 个无法分析的文件")
    print(f"\n{'=' * 60}")


def build_statistics(
    dataset_root: Path,
    output_dir: Path,
    splits: List[str],
    progress_interval: int,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    results: List[GraphPathLengthResult] = []

    for split in splits:
        split_files = list_split_json_files(dataset_root, split)
        split_total = len(split_files)
        started_at = time.time()

        if progress_interval > 0:
            print(f"[{split}] start: {split_total} files", flush=True)

        for file_index, path in enumerate(split_files, start=1):
            results.append(analyze_file(dataset_root, split, path))

            if progress_interval > 0 and (
                file_index % progress_interval == 0 or file_index == split_total
            ):
                elapsed = max(0.001, time.time() - started_at)
                speed = file_index / elapsed
                remaining = max(0, split_total - file_index)
                eta = remaining / speed if speed > 0 else 0.0
                percentage = (
                    file_index / split_total * 100 if split_total else 100.0
                )
                print(
                    f"[{split}] {file_index}/{split_total} files "
                    f"({percentage:.2f}%), elapsed {elapsed:.1f}s, "
                    f"{speed:.2f} files/s, eta {eta:.1f}s",
                    flush=True,
                )

    issues = [
        {
            "split": result.split,
            "file": result.source_file,
            "status": result.status,
            "detail": result.detail,
        }
        for result in results
        if result.status != "ok" or result.detail
    ]
    per_file = [
        {
            "split": result.split,
            "source_file": result.source_file,
            "node_count": result.node_count,
            "link_count": result.link_count,
            "directed": result.directed,
            "max_finite_shortest_path_length": (
                result.max_finite_shortest_path_length
            ),
        }
        for result in results
        if result.status == "ok"
    ]
    summary = {
        "dataset_root": str(dataset_root),
        "splits": splits,
        "overall": build_scope_statistics(results),
        "by_split": {
            split: build_scope_statistics(
                [result for result in results if result.split == split]
            )
            for split in splits
        },
        "issues": issues,
    }

    output_path = output_dir / OUTPUT_FILE_NAME
    write_json(
        output_path,
        {
            "summary": summary,
            "per_file": per_file,
        },
    )
    print_terminal_summary(results)
    print(f"统计结果已写入 {output_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="统计每张拓扑图的最大有限最短路长度。"
    )
    parser.add_argument(
        "dataset_root",
        nargs="?",
        type=Path,
        default=DEFAULT_DATASET_ROOT,
        help=f"数据集根目录，内含 train/ 和 val/。默认：{DEFAULT_DATASET_ROOT}",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"统计结果输出目录。默认：{DEFAULT_OUTPUT_DIR}",
    )
    parser.add_argument(
        "--split",
        choices=["train", "val", "all"],
        default="all",
        help="统计范围：train、val 或 all。默认：all",
    )
    parser.add_argument(
        "--progress-interval",
        type=int,
        default=DEFAULT_PROGRESS_INTERVAL,
        help="每 N 张图打印一次进度。0 表示不打印。默认：%(default)s",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    splits = ["train", "val"] if args.split == "all" else [args.split]
    build_statistics(
        args.dataset_root,
        args.output_dir,
        splits,
        args.progress_interval,
    )


if __name__ == "__main__":
    main()
