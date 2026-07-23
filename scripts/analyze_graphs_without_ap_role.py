#!/usr/bin/env python3
"""统计原始拓扑数据中不包含 DEVICEROLE=AP 节点的 JSON 文件。"""

from __future__ import annotations

import argparse
import csv
import json
import time
from collections import Counter
from pathlib import Path
from typing import Any


DEFAULT_DATASET_ROOT = Path("datasets")
DEFAULT_OUTPUT_DIR = Path("/tmp/graphs_without_ap_role_analysis")
DEFAULT_SPLIT = "all"
DEFAULT_PROGRESS_INTERVAL = 100

SUMMARY_FILE = "graphs_without_ap_role_summary.json"
DETAIL_FILE = "graphs_without_ap_role.csv"
ERROR_FILE = "analysis_errors.csv"
MISSING_ROLE = "<missing>"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "dataset_root",
        nargs="?",
        type=Path,
        default=DEFAULT_DATASET_ROOT,
        help="原始数据集根目录，目录下应包含 train/val，默认: %(default)s",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="统计结果目录，默认: %(default)s",
    )
    parser.add_argument(
        "--split",
        choices=["train", "val", "all"],
        default=DEFAULT_SPLIT,
        help="统计 train、val 或全部数据，默认: %(default)s",
    )
    parser.add_argument(
        "--progress-interval",
        type=int,
        default=DEFAULT_PROGRESS_INTERVAL,
        help="每处理 N 个文件打印进度，0 表示关闭，默认: %(default)s",
    )
    args = parser.parse_args()
    if args.progress_interval < 0:
        parser.error("--progress-interval 不能小于 0")
    return args


def iter_json_files(dataset_root: Path, split: str) -> list[Path]:
    split_root = dataset_root / split
    if not split_root.is_dir():
        raise FileNotFoundError(f"数据划分目录不存在: {split_root}")
    return sorted(path for path in split_root.rglob("*.json") if path.is_file())


def load_json_object(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"JSON 顶层必须是对象，实际为 {type(data).__name__}")
    return data


def analyze_roles(graph: dict[str, Any]) -> tuple[int, Counter[str]]:
    """返回有效节点数量和严格 DEVICEROLE 字符串分布。"""

    nodes = graph.get("nodes")
    if not isinstance(nodes, list):
        return 0, Counter()

    node_count = 0
    role_counts: Counter[str] = Counter()
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_count += 1
        topology_node = node.get("topologyNode")
        role = (
            topology_node.get("DEVICEROLE")
            if isinstance(topology_node, dict)
            else None
        )
        role_text = str(role) if role is not None else MISSING_ROLE
        role_counts[role_text] += 1
    return node_count, role_counts


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def run(args: argparse.Namespace) -> None:
    dataset_root = args.dataset_root.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    splits = ["train", "val"] if args.split == "all" else [args.split]

    details: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    by_split: dict[str, dict[str, Any]] = {}

    for split in splits:
        files = iter_json_files(dataset_root, split)
        valid_files = 0
        files_with_ap = 0
        files_without_ap = 0
        started_at = time.time()
        print(f"[{split}] 开始统计：{len(files)} 个 JSON", flush=True)

        for index, path in enumerate(files, start=1):
            source_file = str(path.relative_to(dataset_root / split))
            try:
                graph = load_json_object(path)
                node_count, role_counts = analyze_roles(graph)
                valid_files += 1
                if role_counts.get("AP", 0) > 0:
                    files_with_ap += 1
                else:
                    files_without_ap += 1
                    details.append(
                        {
                            "split": split,
                            "source_file": source_file,
                            "node_count": node_count,
                            "role_counts": json.dumps(
                                dict(
                                    sorted(
                                        role_counts.items(),
                                        key=lambda item: (-item[1], item[0]),
                                    )
                                ),
                                ensure_ascii=False,
                            ),
                        }
                    )
            except Exception as error:  # noqa: BLE001 - 坏文件单独记录并继续。
                errors.append(
                    {
                        "split": split,
                        "source_file": source_file,
                        "error": f"{type(error).__name__}: {error}",
                    }
                )

            if args.progress_interval > 0 and (
                index % args.progress_interval == 0 or index == len(files)
            ):
                elapsed = max(time.time() - started_at, 0.001)
                speed = index / elapsed
                eta = (len(files) - index) / speed if speed else 0.0
                print(
                    f"[{split}] {index}/{len(files)}，无 AP {files_without_ap}，"
                    f"错误 {index - valid_files}，预计剩余 {eta:.1f} 秒",
                    flush=True,
                )

        by_split[split] = {
            "input_files": len(files),
            "valid_files": valid_files,
            "invalid_files": len(files) - valid_files,
            "files_with_ap_role": files_with_ap,
            "files_without_ap_role": files_without_ap,
            "without_ap_ratio_among_valid_files": round(
                files_without_ap / valid_files if valid_files else 0.0,
                8,
            ),
        }

    valid_file_count = sum(item["valid_files"] for item in by_split.values())
    without_ap_count = sum(
        item["files_without_ap_role"] for item in by_split.values()
    )
    summary = {
        "dataset_root": str(dataset_root),
        "output_dir": str(output_dir),
        "splits": splits,
        "match_rule": "nodes[].topologyNode.DEVICEROLE == 'AP' (exact match)",
        "input_files": sum(item["input_files"] for item in by_split.values()),
        "valid_files": valid_file_count,
        "invalid_files": len(errors),
        "files_with_ap_role": sum(
            item["files_with_ap_role"] for item in by_split.values()
        ),
        "files_without_ap_role": without_ap_count,
        "without_ap_ratio_among_valid_files": round(
            without_ap_count / valid_file_count if valid_file_count else 0.0,
            8,
        ),
        "by_split": by_split,
    }

    write_csv(
        output_dir / DETAIL_FILE,
        ["split", "source_file", "node_count", "role_counts"],
        details,
    )
    write_csv(
        output_dir / ERROR_FILE,
        ["split", "source_file", "error"],
        errors,
    )
    (output_dir / SUMMARY_FILE).write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(
        f"完成：有效 JSON {valid_file_count} 个，其中无 AP 角色文件 "
        f"{without_ap_count} 个，占比 "
        f"{summary['without_ap_ratio_among_valid_files']:.2%}",
        flush=True,
    )
    print(f"结果目录：{output_dir}", flush=True)


if __name__ == "__main__":
    run(parse_args())
