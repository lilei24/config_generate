#!/usr/bin/env python3
"""构造隐藏目标链路 LEFTPORT、RIGHTPORT 和 LABEL 的端口预测任务数据集。"""

from __future__ import annotations

import argparse
import copy
import csv
import json
import random
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_DATASET_ROOT = Path("datasets")
DEFAULT_OUTPUT_ROOT = Path("link_port_prediction_dataset")
DEFAULT_RANDOM_SEED = 20260804
DEFAULT_SPLITS = ("train", "val")
DEFAULT_PROGRESS_INTERVAL = 100

WITH_ANSWER_DIR = "with_answer"
WITHOUT_ANSWER_DIR = "without_answer"
STATS_FILE = "link_port_prediction_stats.csv"
SUMMARY_FILE = "build_summary.json"
ISSUES_FILE = "build_issues.jsonl"

QUESTION_TEMPLATE = """请根据完整网络拓扑、目标链路两端设备信息、其他链路的端口信息和端口命名规律，补全指定链路两端的端口。

目标链路：
- 链路索引：{link_index}
- source 节点 ID：{source_node_id}
- target 节点 ID：{target_node_id}

LEFTPORT 对应 source 侧端口，RIGHTPORT 对应 target 侧端口。目标链路中的 LEFTPORT、RIGHTPORT 和可能泄漏答案的 LABEL 已被隐藏，其他链路信息保持不变。

端口值必须保持原始字符串格式。只输出 JSON：

{{
  "LEFTPORT": "source侧端口",
  "RIGHTPORT": "target侧端口"
}}"""


@dataclass(frozen=True)
class LinkCandidate:
    index: int
    source_node_id: str
    target_node_id: str
    left_port: str
    right_port: str
    label: Any


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
        "--progress-interval",
        type=int,
        default=DEFAULT_PROGRESS_INTERVAL,
        help="每处理 N 个文件打印进度，0 表示关闭",
    )
    parser.add_argument("--indent", type=int, default=2)
    args = parser.parse_args()
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


def load_graph(path: Path) -> tuple[dict[str, Any] | None, str]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as error:  # noqa: BLE001 - 单文件异常不能中断批处理。
        return None, f"{type(error).__name__}: {error}"
    if not isinstance(value, dict):
        return None, f"top-level type is {type(value).__name__}, expected object"
    return value, ""


def valid_node_ids(graph: dict[str, Any]) -> set[str]:
    nodes = graph.get("nodes")
    if not isinstance(nodes, list):
        return set()
    return {
        str(node["id"])
        for node in nodes
        if isinstance(node, dict) and node.get("id") is not None
    }


def nonempty_string(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value


def collect_candidates(graph: dict[str, Any]) -> tuple[list[LinkCandidate], Counter[str]]:
    reasons: Counter[str] = Counter()
    node_ids = valid_node_ids(graph)
    links = graph.get("links")
    if not isinstance(links, list):
        reasons["links-not-list"] += 1
        return [], reasons

    candidates: list[LinkCandidate] = []
    for index, item in enumerate(links):
        if not isinstance(item, dict):
            reasons["link-item-not-object"] += 1
            continue
        source = item.get("source")
        target = item.get("target")
        if source is None or target is None:
            reasons["missing-source-or-target"] += 1
            continue
        source_id = str(source)
        target_id = str(target)
        if source_id not in node_ids or target_id not in node_ids:
            reasons["endpoint-not-in-nodes"] += 1
            continue
        link_data = item.get("link")
        if not isinstance(link_data, dict):
            reasons["missing-link-object"] += 1
            continue
        left_port = nonempty_string(link_data.get("LEFTPORT"))
        right_port = nonempty_string(link_data.get("RIGHTPORT"))
        if left_port is None or right_port is None:
            reasons["missing-or-empty-port"] += 1
            continue
        candidates.append(
            LinkCandidate(
                index=index,
                source_node_id=source_id,
                target_node_id=target_id,
                left_port=left_port,
                right_port=right_port,
                label=link_data.get("LABEL"),
            )
        )
    return candidates, reasons


def build_task_graph(
    graph: dict[str, Any],
    candidate: LinkCandidate,
    split: str,
    source_file: str,
) -> dict[str, Any]:
    task_graph = copy.deepcopy(graph)
    for key in list(task_graph):
        if key.startswith("task_"):
            task_graph.pop(key)

    links = task_graph.get("links")
    if not isinstance(links, list) or candidate.index >= len(links):
        raise ValueError("目标链路索引在复制后的图中无效")
    target_item = links[candidate.index]
    if not isinstance(target_item, dict) or not isinstance(target_item.get("link"), dict):
        raise ValueError("目标链路结构在复制后的图中无效")
    target_link = target_item["link"]
    target_link.pop("LEFTPORT", None)
    target_link.pop("RIGHTPORT", None)
    target_link.pop("LABEL", None)

    task_graph["task_source_node_id"] = candidate.source_node_id
    task_graph["task_target_node_id"] = candidate.target_node_id
    task_graph["task_target_link_index"] = candidate.index
    task_graph["task_question"] = QUESTION_TEMPLATE.format(
        link_index=candidate.index,
        source_node_id=candidate.source_node_id,
        target_node_id=candidate.target_node_id,
    )
    task_graph["task_answer"] = {
        "LEFTPORT": candidate.left_port,
        "RIGHTPORT": candidate.right_port,
    }
    task_graph["task_metadata"] = {
        "task_name": "link_endpoint_port_prediction",
        "split": split,
        "source_file": source_file,
        "target_link_index": candidate.index,
        "leftport_endpoint": "source",
        "rightport_endpoint": "target",
        "mask_strategy": "remove_leftport_rightport_and_label",
    }
    return task_graph


def write_json(path: Path, value: dict[str, Any], indent: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=indent) + "\n",
        encoding="utf-8",
    )


def write_issue(path: Path, issue: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(issue, ensure_ascii=False) + "\n")


def remove_stale_outputs(output_root: Path, split: str, relative_path: Path) -> None:
    for directory in (WITH_ANSWER_DIR, WITHOUT_ANSWER_DIR):
        path = output_root / directory / split / relative_path
        if path.is_file():
            path.unlink()


def write_stats(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "split",
        "source_file",
        "output_file",
        "eligible_link_count",
        "target_link_index",
        "source_node_id",
        "target_node_id",
        "left_port",
        "right_port",
        "label_was_present",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
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
        "samples_per_graph": 1,
        "mask_strategy": "remove LEFTPORT, RIGHTPORT and LABEL from one random eligible link",
        "port_direction": {"LEFTPORT": "source", "RIGHTPORT": "target"},
        "splits": {},
    }

    for split in args.splits:
        files = iter_json_files(dataset_root, split)
        split_summary: dict[str, Any] = {
            "input_files": len(files),
            "generated_files": 0,
            "skipped_files": 0,
            "eligible_links": 0,
            "labels_removed": 0,
            "skip_reasons": {},
            "ineligible_link_reasons": {},
        }
        skip_reasons: Counter[str] = Counter()
        ineligible_reasons: Counter[str] = Counter()
        print(f"[{split}] found {len(files)} json files", flush=True)

        for file_index, source_path in enumerate(files, start=1):
            relative_path = source_path.relative_to(dataset_root / split)
            remove_stale_outputs(output_root, split, relative_path)
            graph, load_error = load_graph(source_path)
            if graph is None:
                reason = "load-json-error"
                skip_reasons[reason] += 1
                write_issue(
                    issue_path,
                    {
                        "split": split,
                        "source_file": str(relative_path),
                        "issue": reason,
                        "detail": load_error,
                    },
                )
            else:
                candidates, candidate_reasons = collect_candidates(graph)
                ineligible_reasons.update(candidate_reasons)
                split_summary["eligible_links"] += len(candidates)
                if not candidates:
                    reason = "no-link-with-complete-endpoint-ports"
                    skip_reasons[reason] += 1
                    write_issue(
                        issue_path,
                        {
                            "split": split,
                            "source_file": str(relative_path),
                            "issue": reason,
                            "detail": dict(candidate_reasons),
                        },
                    )
                else:
                    candidate = rng.choice(candidates)
                    task_graph = build_task_graph(
                        graph,
                        candidate,
                        split,
                        str(relative_path),
                    )
                    with_path = output_root / WITH_ANSWER_DIR / split / relative_path
                    without_path = output_root / WITHOUT_ANSWER_DIR / split / relative_path
                    write_json(with_path, task_graph, args.indent)
                    hidden_graph = copy.deepcopy(task_graph)
                    hidden_graph.pop("task_answer", None)
                    write_json(without_path, hidden_graph, args.indent)

                    split_summary["generated_files"] += 1
                    if candidate.label is not None:
                        split_summary["labels_removed"] += 1
                    stats_rows.append(
                        {
                            "split": split,
                            "source_file": str(relative_path),
                            "output_file": str(with_path.relative_to(output_root)),
                            "eligible_link_count": len(candidates),
                            "target_link_index": candidate.index,
                            "source_node_id": candidate.source_node_id,
                            "target_node_id": candidate.target_node_id,
                            "left_port": candidate.left_port,
                            "right_port": candidate.right_port,
                            "label_was_present": candidate.label is not None,
                        }
                    )

            if args.progress_interval > 0 and (
                file_index % args.progress_interval == 0 or file_index == len(files)
            ):
                print(
                    f"[{split}] {file_index}/{len(files)}，"
                    f"已生成 {split_summary['generated_files']}，"
                    f"跳过 {sum(skip_reasons.values())}",
                    flush=True,
                )

        split_summary["skipped_files"] = sum(skip_reasons.values())
        split_summary["skip_reasons"] = dict(sorted(skip_reasons.items()))
        split_summary["ineligible_link_reasons"] = dict(
            sorted(ineligible_reasons.items())
        )
        summary["splits"][split] = split_summary

    write_stats(output_root / STATS_FILE, stats_rows)
    write_json(output_root / SUMMARY_FILE, summary, args.indent)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


if __name__ == "__main__":
    build_dataset(parse_args())
