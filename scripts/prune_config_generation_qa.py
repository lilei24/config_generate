#!/usr/bin/env python3
"""对已生成的配置生成 QA 样本再次裁剪 input 图上下文。

这个脚本的输入是 build_config_generation_dataset_pruned.py 已经生成的 QA JSON，
不是原始 datasets 图文件。它不会重新选择 target node 或 target key，只使用
metadata.target 里已有的目标信息，然后只修改样本中的 input 字段。

默认目录结构：

输入：
  QA/train/node_config_qa/*.json
  QA/train/device_config_qa/*.json
  QA/val/node_config_qa/*.json
  QA/val/device_config_qa/*.json

输出：
  QA_post_pruned/train/node_config_qa/*.json
  QA_post_pruned/train/device_config_qa/*.json
  QA_post_pruned/val/node_config_qa/*.json
  QA_post_pruned/val/device_config_qa/*.json
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import time
from collections import Counter, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Deque, Dict, Iterable, List, Optional, Set, Tuple


DEFAULT_QA_ROOT = Path("QA")
DEFAULT_OUTPUT_DIR = Path("QA_post_pruned")
DEFAULT_MAX_INPUT_TOKENS = 100000
DEFAULT_PROGRESS_INTERVAL = 100
DEFAULT_SPLITS = ["train", "val"]
DEFAULT_TASK_DIRS = ["node_config_qa", "device_config_qa"]


@dataclass(frozen=True)
class PruneResult:
    """单个 QA 样本 input 的二次裁剪结果。"""

    graph: Dict[str, Any]
    center_node_id: Optional[str]
    center_source: str
    original_token_estimate: int
    final_token_estimate: int
    original_node_count: int
    final_node_count: int
    removed_node_count: int
    pruned: bool
    still_over_limit: bool
    skipped_reason: str = ""


@dataclass(frozen=True)
class ProcessIssue:
    """处理 QA 样本时需要记录的问题。"""

    split: str
    task_dir: str
    file: str
    issue: str
    detail: str = ""


def stable_json_text(value: Any) -> str:
    """把 JSON 值转成稳定文本，用于粗略 token 估算。"""

    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def rough_bpe_token_count(text: str) -> int:
    """粗略估算 BPE token 数，与现有数据分析脚本保持接近口径。"""

    count = 0
    index = 0
    while index < len(text):
        char = text[index]
        code = ord(char)
        if char.isspace():
            index += 1
            continue
        if 0x4E00 <= code <= 0x9FFF:
            count += 1
            index += 1
            continue
        if char.isascii() and (char.isalnum() or char in "_-./"):
            start = index
            while index < len(text):
                current = text[index]
                if current.isascii() and (current.isalnum() or current in "_-./"):
                    index += 1
                    continue
                break
            count += max(1, math.ceil((index - start) / 4))
            continue
        count += 1
        index += 1
    return count


def graph_token_estimate(graph: Dict[str, Any]) -> int:
    """估算 input 图上下文 token 数。"""

    return rough_bpe_token_count(stable_json_text(graph))


def load_json(path: Path) -> Tuple[Optional[Dict[str, Any]], str]:
    """读取单个 QA JSON。"""

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - bad source files are recorded and skipped.
        return None, str(exc)
    if not isinstance(data, dict):
        return None, f"top-level JSON type is {type(data).__name__}, expected object"
    return data, ""


def write_json(path: Path, data: Any) -> None:
    """写格式化 JSON，并保留字段顺序，方便人工查看。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    """写 JSONL 问题文件。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def node_id_at(node: Any) -> Optional[str]:
    """读取节点 id。"""

    if not isinstance(node, dict):
        return None
    node_id = node.get("id")
    return str(node_id) if node_id is not None else None


def graph_nodes(graph: Dict[str, Any]) -> List[Any]:
    """安全读取 nodes 列表。"""

    nodes = graph.get("nodes")
    return nodes if isinstance(nodes, list) else []


def valid_node_ids(graph: Dict[str, Any]) -> List[str]:
    """返回 input 图中的有效 node id。"""

    return [node_id for node_id in (node_id_at(node) for node in graph_nodes(graph)) if node_id is not None]


def build_adjacency(graph: Dict[str, Any]) -> Dict[str, Set[str]]:
    """根据 input.links 构造无向邻接表。"""

    node_ids = set(valid_node_ids(graph))
    adjacency: Dict[str, Set[str]] = {node_id: set() for node_id in node_ids}
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
        if source_id not in adjacency or target_id not in adjacency:
            continue
        adjacency[source_id].add(target_id)
        adjacency[target_id].add(source_id)
    return adjacency


def shortest_distances(graph: Dict[str, Any], center_node_id: str) -> Dict[str, float]:
    """计算中心节点到其他节点的最短路，不连通节点距离为无穷。"""

    adjacency = build_adjacency(graph)
    distances: Dict[str, float] = {node_id: math.inf for node_id in adjacency}
    if center_node_id not in adjacency:
        return distances
    distances[center_node_id] = 0
    queue: Deque[str] = deque([center_node_id])
    while queue:
        current = queue.popleft()
        for neighbor in adjacency[current]:
            if distances[neighbor] != math.inf:
                continue
            distances[neighbor] = distances[current] + 1
            queue.append(neighbor)
    return distances


def farthest_removable_node_id(graph: Dict[str, Any], center_node_id: str) -> Optional[str]:
    """选择距离中心最远的可删除节点，永远不删除中心节点。"""

    distances = shortest_distances(graph, center_node_id)
    best_node_id: Optional[str] = None
    best_rank: Tuple[int, float, int] = (-1, -1.0, -1)
    for node_index, node in enumerate(graph_nodes(graph)):
        node_id = node_id_at(node)
        if node_id is None or node_id == center_node_id:
            continue
        distance = distances.get(node_id, math.inf)
        rank = (1 if distance == math.inf else 0, distance, node_index)
        if rank > best_rank:
            best_rank = rank
            best_node_id = node_id
    return best_node_id


def remove_node_from_graph(graph: Dict[str, Any], removed_node_id: str) -> None:
    """从 input.nodes 删除一个节点，并同步删除关联 links。"""

    nodes = graph.get("nodes")
    if isinstance(nodes, list):
        graph["nodes"] = [node for node in nodes if node_id_at(node) != removed_node_id]

    links = graph.get("links")
    if isinstance(links, list):
        graph["links"] = [
            link
            for link in links
            if not (
                isinstance(link, dict)
                and (str(link.get("source")) == removed_node_id or str(link.get("target")) == removed_node_id)
            )
        ]


def resolve_center_node_id(sample: Dict[str, Any], graph: Dict[str, Any]) -> Tuple[Optional[str], str]:
    """从已有 metadata 中确定二次裁剪中心节点。

    node_config_qa 优先使用 metadata.target.node_id。device_config_qa 没有目标节点
    时，沿用第一次构建时记录的 metadata.context_pruning.center_node_id。
    """

    metadata = sample.get("metadata")
    if isinstance(metadata, dict):
        target = metadata.get("target")
        if isinstance(target, dict) and target.get("node_id") is not None:
            return str(target["node_id"]), "metadata.target.node_id"

        context_pruning = metadata.get("context_pruning")
        if isinstance(context_pruning, dict) and context_pruning.get("center_node_id") is not None:
            return str(context_pruning["center_node_id"]), "metadata.context_pruning.center_node_id"

    node_ids = valid_node_ids(graph)
    if node_ids:
        return node_ids[0], "first_node_id"
    return None, "missing"


def prune_graph_to_token_limit(
    graph: Dict[str, Any],
    center_node_id: Optional[str],
    center_source: str,
    max_input_tokens: int,
) -> PruneResult:
    """围绕已有中心节点裁剪 input 图上下文。"""

    working_graph = copy.deepcopy(graph)
    original_token_estimate = graph_token_estimate(working_graph)
    original_node_count = len(graph_nodes(working_graph))

    if not center_node_id:
        return PruneResult(
            graph=working_graph,
            center_node_id=center_node_id,
            center_source=center_source,
            original_token_estimate=original_token_estimate,
            final_token_estimate=original_token_estimate,
            original_node_count=original_node_count,
            final_node_count=original_node_count,
            removed_node_count=0,
            pruned=False,
            still_over_limit=max_input_tokens > 0 and original_token_estimate > max_input_tokens,
            skipped_reason="missing_center_node_id",
        )

    if center_node_id not in set(valid_node_ids(working_graph)):
        return PruneResult(
            graph=working_graph,
            center_node_id=center_node_id,
            center_source=center_source,
            original_token_estimate=original_token_estimate,
            final_token_estimate=original_token_estimate,
            original_node_count=original_node_count,
            final_node_count=original_node_count,
            removed_node_count=0,
            pruned=False,
            still_over_limit=max_input_tokens > 0 and original_token_estimate > max_input_tokens,
            skipped_reason="center_node_not_in_input",
        )

    if max_input_tokens <= 0 or original_token_estimate <= max_input_tokens:
        return PruneResult(
            graph=working_graph,
            center_node_id=center_node_id,
            center_source=center_source,
            original_token_estimate=original_token_estimate,
            final_token_estimate=original_token_estimate,
            original_node_count=original_node_count,
            final_node_count=original_node_count,
            removed_node_count=0,
            pruned=False,
            still_over_limit=max_input_tokens > 0 and original_token_estimate > max_input_tokens,
        )

    current_token_estimate = original_token_estimate
    removed_node_count = 0
    while current_token_estimate > max_input_tokens:
        removed_node_id = farthest_removable_node_id(working_graph, center_node_id)
        if removed_node_id is None:
            break
        remove_node_from_graph(working_graph, removed_node_id)
        removed_node_count += 1
        current_token_estimate = graph_token_estimate(working_graph)

    return PruneResult(
        graph=working_graph,
        center_node_id=center_node_id,
        center_source=center_source,
        original_token_estimate=original_token_estimate,
        final_token_estimate=current_token_estimate,
        original_node_count=original_node_count,
        final_node_count=len(graph_nodes(working_graph)),
        removed_node_count=removed_node_count,
        pruned=removed_node_count > 0,
        still_over_limit=max_input_tokens > 0 and current_token_estimate > max_input_tokens,
    )


def prune_metadata(prune_result: PruneResult, max_input_tokens: int) -> Dict[str, Any]:
    """整理写入 metadata.post_context_pruning 的裁剪信息。"""

    return {
        "max_input_tokens": max_input_tokens,
        "center_node_id": prune_result.center_node_id,
        "center_source": prune_result.center_source,
        "original_token_estimate": prune_result.original_token_estimate,
        "final_token_estimate": prune_result.final_token_estimate,
        "original_node_count": prune_result.original_node_count,
        "final_node_count": prune_result.final_node_count,
        "removed_node_count": prune_result.removed_node_count,
        "pruned": prune_result.pruned,
        "still_over_limit": prune_result.still_over_limit,
        "skipped_reason": prune_result.skipped_reason,
    }


def iter_task_files(qa_root: Path, split: str, task_dir: str) -> List[Path]:
    """按稳定顺序枚举一个 split/task 下的 QA JSON 文件。"""

    root = qa_root / split / task_dir
    if not root.exists():
        return []
    return [path for path in sorted(root.rglob("*.json")) if path.is_file()]


def process_task(
    qa_root: Path,
    output_dir: Path,
    split: str,
    task_dir: str,
    files: List[Path],
    max_input_tokens: int,
    progress_interval: int,
) -> Tuple[List[ProcessIssue], Counter[str]]:
    """处理单个 split/task 目录。"""

    issues: List[ProcessIssue] = []
    counts: Counter[str] = Counter()
    started_at = time.time()
    total_files = len(files)

    if progress_interval > 0:
        print(f"[{split}/{task_dir}] start: {total_files} files", flush=True)

    for file_index, path in enumerate(files, start=1):
        counts["files"] += 1
        relative_path = path.relative_to(qa_root)
        sample, load_detail = load_json(path)
        if sample is None:
            counts["skipped_bad_json"] += 1
            issues.append(ProcessIssue(split, task_dir, str(relative_path), "bad_json", load_detail))
            continue

        graph = sample.get("input")
        if not isinstance(graph, dict):
            counts["skipped_bad_input"] += 1
            issues.append(
                ProcessIssue(split, task_dir, str(relative_path), "bad_input", "sample.input is not a JSON object")
            )
            continue

        center_node_id, center_source = resolve_center_node_id(sample, graph)
        prune_result = prune_graph_to_token_limit(graph, center_node_id, center_source, max_input_tokens)

        output_sample = copy.deepcopy(sample)
        output_sample["input"] = prune_result.graph
        metadata = output_sample.setdefault("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {"original_metadata": metadata}
            output_sample["metadata"] = metadata
        metadata["post_context_pruning"] = prune_metadata(prune_result, max_input_tokens)

        write_json(output_dir / relative_path, output_sample)

        counts["written_files"] += 1
        counts["original_token_estimate_total"] += prune_result.original_token_estimate
        counts["final_token_estimate_total"] += prune_result.final_token_estimate
        counts["original_node_count_total"] += prune_result.original_node_count
        counts["final_node_count_total"] += prune_result.final_node_count
        counts["removed_node_count_total"] += prune_result.removed_node_count
        if prune_result.pruned:
            counts["pruned_files"] += 1
        if prune_result.still_over_limit:
            counts["files_still_over_limit"] += 1
        if prune_result.skipped_reason:
            counts[f"skipped_{prune_result.skipped_reason}"] += 1
            issues.append(ProcessIssue(split, task_dir, str(relative_path), prune_result.skipped_reason))

        if progress_interval > 0 and (file_index % progress_interval == 0 or file_index == total_files):
            elapsed = max(0.001, time.time() - started_at)
            speed = file_index / elapsed
            eta = (total_files - file_index) / speed if speed > 0 else 0
            percent = (file_index / total_files * 100) if total_files else 100.0
            print(
                f"[{split}/{task_dir}] {file_index}/{total_files} files ({percent:.2f}%), "
                f"elapsed {elapsed:.1f}s, {speed:.2f} files/s, eta {eta:.1f}s, "
                f"pruned {counts['pruned_files']}",
                flush=True,
            )

    return issues, counts


def build_summary_row(counts: Counter[str]) -> Dict[str, Any]:
    """补充均值统计，便于快速判断二次裁剪效果。"""

    row = dict(counts)
    files = counts.get("written_files", 0)
    if files:
        row["original_token_estimate_mean"] = counts.get("original_token_estimate_total", 0) / files
        row["final_token_estimate_mean"] = counts.get("final_token_estimate_total", 0) / files
        row["original_node_count_mean"] = counts.get("original_node_count_total", 0) / files
        row["final_node_count_mean"] = counts.get("final_node_count_total", 0) / files
        row["removed_node_count_mean"] = counts.get("removed_node_count_total", 0) / files
    return row


def process_qa_root(
    qa_root: Path,
    output_dir: Path,
    splits: List[str],
    task_dirs: List[str],
    max_input_tokens: int,
    progress_interval: int,
) -> None:
    """按 split/task 处理已有 QA 目录。"""

    output_dir.mkdir(parents=True, exist_ok=True)
    all_issues: List[Dict[str, Any]] = []
    summary: Dict[str, Any] = {
        "qa_root": str(qa_root),
        "output_dir": str(output_dir),
        "max_input_tokens": max_input_tokens,
        "token_estimator": "rough_bpe",
        "splits": {},
    }

    for split in splits:
        split_summary: Dict[str, Any] = {}
        for task_dir in task_dirs:
            files = iter_task_files(qa_root, split, task_dir)
            issues, counts = process_task(
                qa_root,
                output_dir,
                split,
                task_dir,
                files,
                max_input_tokens,
                progress_interval,
            )
            all_issues.extend(
                {
                    "split": issue.split,
                    "task_dir": issue.task_dir,
                    "file": issue.file,
                    "issue": issue.issue,
                    "detail": issue.detail,
                }
                for issue in issues
            )
            split_summary[task_dir] = build_summary_row(counts)
        summary["splits"][split] = split_summary

    write_json(output_dir / "post_prune_summary.json", summary)
    write_jsonl(output_dir / "post_prune_issues.jsonl", all_issues)


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""

    parser = argparse.ArgumentParser(description="Post-prune generated config QA JSON files.")
    parser.add_argument(
        "qa_root",
        nargs="?",
        type=Path,
        default=DEFAULT_QA_ROOT,
        help=f"Existing QA root containing split/task JSON files. Default: {DEFAULT_QA_ROOT}",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory for post-pruned QA files. Default: {DEFAULT_OUTPUT_DIR}",
    )
    parser.add_argument("--splits", nargs="+", default=DEFAULT_SPLITS, help="Split names to process.")
    parser.add_argument("--task-dirs", nargs="+", default=DEFAULT_TASK_DIRS, help="Task directories to process.")
    parser.add_argument(
        "--max-input-tokens",
        type=int,
        default=DEFAULT_MAX_INPUT_TOKENS,
        help="Rough token limit for sample.input. Use 0 to disable pruning. Default: %(default)s",
    )
    parser.add_argument(
        "--progress-interval",
        type=int,
        default=DEFAULT_PROGRESS_INTERVAL,
        help="Print progress every N QA files. Use 0 to disable. Default: %(default)s",
    )
    return parser.parse_args()


def main() -> None:
    """脚本入口。"""

    args = parse_args()
    process_qa_root(
        args.qa_root,
        args.output_dir,
        args.splits,
        args.task_dirs,
        args.max_input_tokens,
        args.progress_interval,
    )
    print(f"Wrote post-pruned QA data to {args.output_dir}")


if __name__ == "__main__":
    main()
