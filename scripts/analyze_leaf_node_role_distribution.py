#!/usr/bin/env python3
"""统计原始拓扑数据中叶子节点的 DEVICEROLE 分布。

叶子节点严格定义为物理邻居数量 degree == 1 的节点：

- links 统一按无向物理连接处理，不考虑 source/target 方向；
- 同一对节点之间的重复链路只贡献一个邻居；
- 自环不计入邻居；
- degree == 0 的节点单独统计为孤立节点，不算叶子节点。

脚本输出一个格式化 JSON，顶层包含 summary 和 per_file；终端打印处理进度、
速度、ETA，以及叶子节点内部的 DEVICEROLE 分布。
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


DEFAULT_DATASET_ROOT = Path("datasets")
DEFAULT_OUTPUT_DIR = Path("/tmp/leaf_node_role_analysis")
DEFAULT_PROGRESS_INTERVAL = 50
OUTPUT_FILE_NAME = "leaf_node_role_statistics.json"
MISSING_ROLE = "<missing>"


@dataclass
class GraphLeafRoleResult:
    split: str
    source_file: str
    directed: bool
    node_count: int
    valid_link_count: int
    leaf_node_count: int
    isolated_node_count: int
    role_counts: Counter[str]
    leaf_role_counts: Counter[str]
    status: str
    detail: str = ""


def iter_json_files(
    dataset_root: Path,
    splits: Iterable[str],
) -> Iterable[Tuple[str, Path]]:
    for split in splits:
        split_dir = dataset_root / split
        if not split_dir.exists():
            continue
        for path in sorted(split_dir.rglob("*.json")):
            if path.is_file():
                yield split, path


def list_split_json_files(dataset_root: Path, split: str) -> List[Path]:
    return [path for _, path in iter_json_files(dataset_root, [split])]


def load_graph(path: Path) -> Tuple[Dict[str, Any] | None, str]:
    try:
        graph = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - 坏文件需要记录并继续统计。
        return None, str(exc)
    if not isinstance(graph, dict):
        return None, f"top-level JSON type is {type(graph).__name__}, expected object"
    return graph, ""


def get_device_role(node: Dict[str, Any]) -> str:
    topology_node = node.get("topologyNode")
    if not isinstance(topology_node, dict):
        return MISSING_ROLE
    role = topology_node.get("DEVICEROLE")
    if role is None or role == "":
        return MISSING_ROLE
    return str(role)


def analyze_graph(
    dataset_root: Path,
    split: str,
    path: Path,
) -> GraphLeafRoleResult:
    source_file = str(path.relative_to(dataset_root))
    graph, error = load_graph(path)
    if graph is None:
        return GraphLeafRoleResult(
            split=split,
            source_file=source_file,
            directed=False,
            node_count=0,
            valid_link_count=0,
            leaf_node_count=0,
            isolated_node_count=0,
            role_counts=Counter(),
            leaf_role_counts=Counter(),
            status="bad_json",
            detail=error,
        )

    nodes = graph.get("nodes")
    if not isinstance(nodes, list):
        return GraphLeafRoleResult(
            split=split,
            source_file=source_file,
            directed=bool(graph.get("directed", False)),
            node_count=0,
            valid_link_count=0,
            leaf_node_count=0,
            isolated_node_count=0,
            role_counts=Counter(),
            leaf_role_counts=Counter(),
            status="nodes_not_list",
            detail=type(nodes).__name__,
        )

    node_by_id: Dict[str, Dict[str, Any]] = {}
    missing_id_count = 0
    duplicate_id_count = 0
    for node in nodes:
        if not isinstance(node, dict) or node.get("id") is None:
            missing_id_count += 1
            continue
        node_id = str(node["id"])
        if node_id in node_by_id:
            duplicate_id_count += 1
            continue
        node_by_id[node_id] = node

    if not node_by_id:
        detail = (
            f"raw_node_count={len(nodes)}, missing_id_count={missing_id_count}, "
            f"duplicate_id_count={duplicate_id_count}"
        )
        return GraphLeafRoleResult(
            split=split,
            source_file=source_file,
            directed=bool(graph.get("directed", False)),
            node_count=0,
            valid_link_count=0,
            leaf_node_count=0,
            isolated_node_count=0,
            role_counts=Counter(),
            leaf_role_counts=Counter(),
            status="no_valid_nodes",
            detail=detail,
        )

    adjacency: Dict[str, set[str]] = {
        node_id: set() for node_id in node_by_id
    }
    valid_edges: set[tuple[str, str]] = set()
    invalid_link_count = 0
    self_loop_count = 0
    duplicate_link_count = 0
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
        if source_id == target_id:
            self_loop_count += 1
            continue

        # 无论原图 directed 取值如何，都按无向物理邻居统计叶子节点。
        edge = tuple(sorted((source_id, target_id)))
        if edge in valid_edges:
            duplicate_link_count += 1
        else:
            valid_edges.add(edge)
        adjacency[source_id].add(target_id)
        adjacency[target_id].add(source_id)

    role_by_id = {
        node_id: get_device_role(node) for node_id, node in node_by_id.items()
    }
    role_counts = Counter(role_by_id.values())
    leaf_node_ids = [
        node_id for node_id, neighbors in adjacency.items() if len(neighbors) == 1
    ]
    isolated_node_count = sum(
        1 for neighbors in adjacency.values() if not neighbors
    )
    leaf_role_counts = Counter(role_by_id[node_id] for node_id in leaf_node_ids)

    details: List[str] = []
    if missing_id_count:
        details.append(f"missing_id_nodes={missing_id_count}")
    if duplicate_id_count:
        details.append(f"duplicate_node_ids={duplicate_id_count}")
    if invalid_link_count:
        details.append(f"invalid_links={invalid_link_count}")
    if self_loop_count:
        details.append(f"ignored_self_loops={self_loop_count}")
    if duplicate_link_count:
        details.append(f"duplicate_links={duplicate_link_count}")

    return GraphLeafRoleResult(
        split=split,
        source_file=source_file,
        directed=bool(graph.get("directed", False)),
        node_count=len(node_by_id),
        valid_link_count=len(valid_edges),
        leaf_node_count=len(leaf_node_ids),
        isolated_node_count=isolated_node_count,
        role_counts=role_counts,
        leaf_role_counts=leaf_role_counts,
        status="ok",
        detail="; ".join(details),
    )


def distribution(
    counter: Counter[str],
) -> Dict[str, Dict[str, int | float]]:
    total = sum(counter.values())
    return {
        role: {
            "count": count,
            "percentage": round(count / total * 100, 2) if total else 0.0,
        }
        for role, count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    }


def build_role_leaf_rates(
    role_counts: Counter[str],
    leaf_role_counts: Counter[str],
) -> Dict[str, Dict[str, int | float]]:
    """计算每种角色内部的叶子节点比例，而不是角色在叶子节点中的占比。"""
    return {
        role: {
            "total_nodes": total_count,
            "leaf_nodes": leaf_role_counts.get(role, 0),
            "leaf_percentage_within_role": round(
                leaf_role_counts.get(role, 0) / total_count * 100,
                2,
            )
            if total_count
            else 0.0,
        }
        for role, total_count in sorted(
            role_counts.items(),
            key=lambda item: (-item[1], item[0]),
        )
    }


def build_scope_statistics(results: List[GraphLeafRoleResult]) -> Dict[str, Any]:
    valid_results = [result for result in results if result.status == "ok"]
    role_counts: Counter[str] = Counter()
    leaf_role_counts: Counter[str] = Counter()
    for result in valid_results:
        role_counts.update(result.role_counts)
        leaf_role_counts.update(result.leaf_role_counts)

    total_nodes = sum(result.node_count for result in valid_results)
    total_leaf_nodes = sum(result.leaf_node_count for result in valid_results)
    total_isolated_nodes = sum(
        result.isolated_node_count for result in valid_results
    )
    return {
        "input_files": len(results),
        "analyzed_graphs": len(valid_results),
        "skipped_files": len(results) - len(valid_results),
        "total_nodes": total_nodes,
        "leaf_nodes": total_leaf_nodes,
        "leaf_node_percentage": round(
            total_leaf_nodes / total_nodes * 100,
            2,
        )
        if total_nodes
        else 0.0,
        "isolated_nodes": total_isolated_nodes,
        "isolated_node_percentage": round(
            total_isolated_nodes / total_nodes * 100,
            2,
        )
        if total_nodes
        else 0.0,
        "leaf_role_distribution": distribution(leaf_role_counts),
        "role_leaf_rates": build_role_leaf_rates(
            role_counts,
            leaf_role_counts,
        ),
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


def print_terminal_summary(results: List[GraphLeafRoleResult]) -> None:
    valid_results = [result for result in results if result.status == "ok"]
    role_counts: Counter[str] = Counter()
    leaf_role_counts: Counter[str] = Counter()
    for result in valid_results:
        role_counts.update(result.role_counts)
        leaf_role_counts.update(result.leaf_role_counts)
    total_nodes = sum(result.node_count for result in valid_results)
    total_leaf_nodes = sum(result.leaf_node_count for result in valid_results)
    total_isolated_nodes = sum(
        result.isolated_node_count for result in valid_results
    )

    print(f"\n{'=' * 60}")
    print(f"统计完成：{len(valid_results)} 张图，{total_nodes} 个节点")
    print(f"{'=' * 60}")
    leaf_percentage = (
        total_leaf_nodes / total_nodes * 100 if total_nodes else 0.0
    )
    isolated_percentage = (
        total_isolated_nodes / total_nodes * 100 if total_nodes else 0.0
    )
    print(
        f"\n叶子节点：{total_leaf_nodes}/{total_nodes} "
        f"({leaf_percentage:.2f}%)"
    )
    print(
        f"孤立节点：{total_isolated_nodes}/{total_nodes} "
        f"({isolated_percentage:.2f}%)"
    )

    print("\n--- 叶子节点 DEVICEROLE 分布 ---")
    for role, count in leaf_role_counts.most_common():
        percentage = count / total_leaf_nodes * 100 if total_leaf_nodes else 0.0
        print(
            f"  {role:24s}  {terminal_bar(count, total_leaf_nodes)}  "
            f"{count} ({percentage:.2f}%)"
        )

    print("\n--- 各 DEVICEROLE 成为叶子节点的比例 ---")
    for role, total_count in role_counts.most_common():
        leaf_count = leaf_role_counts.get(role, 0)
        percentage = leaf_count / total_count * 100 if total_count else 0.0
        print(
            f"  {role:24s}  {terminal_bar(leaf_count, total_count)}  "
            f"{leaf_count}/{total_count} ({percentage:.2f}%)"
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
    results: List[GraphLeafRoleResult] = []

    for split in splits:
        split_files = list_split_json_files(dataset_root, split)
        split_total = len(split_files)
        started_at = time.time()
        if progress_interval > 0:
            print(f"[{split}] start: {split_total} files", flush=True)

        for file_index, path in enumerate(split_files, start=1):
            results.append(analyze_graph(dataset_root, split, path))
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
            "directed": result.directed,
            "node_count": result.node_count,
            "valid_link_count": result.valid_link_count,
            "leaf_node_count": result.leaf_node_count,
            "leaf_node_percentage": round(
                result.leaf_node_count / result.node_count * 100,
                2,
            )
            if result.node_count
            else 0.0,
            "isolated_node_count": result.isolated_node_count,
            "leaf_role_distribution": distribution(result.leaf_role_counts),
            "role_leaf_rates": build_role_leaf_rates(
                result.role_counts,
                result.leaf_role_counts,
            ),
        }
        for result in results
        if result.status == "ok"
    ]
    summary = {
        "definition": {
            "leaf_node": "number of distinct physical neighbors equals 1",
            "isolated_node": "number of distinct physical neighbors equals 0",
            "link_direction": "ignored; all valid links are treated as undirected",
            "self_loop": "ignored",
        },
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
    write_json(output_path, {"summary": summary, "per_file": per_file})
    print_terminal_summary(results)
    print(f"统计结果已写入 {output_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="统计叶子节点的 topologyNode.DEVICEROLE 分布。"
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
