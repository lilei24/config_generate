#!/usr/bin/env python3
"""统计多个 DEVICEROLE 在同一个拓扑 JSON 中同时出现的文件数。"""

from __future__ import annotations

import argparse
import csv
import json
import time
from collections import Counter
from pathlib import Path
from typing import Any


DEFAULT_DATASET_ROOT = Path("datasets")
DEFAULT_OUTPUT_DIR = Path("/tmp/device_role_cooccurrence_analysis")
DEFAULT_DEVICE_ROLES = ("AP", "CORE")
DEFAULT_SPLIT = "all"
DEFAULT_PROGRESS_INTERVAL = 100

SUMMARY_FILE = "device_role_cooccurrence_summary.json"
MATCHED_FILES_FILE = "matching_files.csv"
ERROR_FILE = "analysis_errors.csv"


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
        "--device-roles",
        nargs="+",
        default=list(DEFAULT_DEVICE_ROLES),
        metavar="ROLE",
        help="要求在同一文件中同时存在的角色，默认: AP CORE",
    )
    parser.add_argument(
        "--split",
        choices=["train", "val", "all"],
        default=DEFAULT_SPLIT,
        help="统计的数据划分，默认: %(default)s",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="统计结果目录，默认: %(default)s",
    )
    parser.add_argument(
        "--progress-interval",
        type=int,
        default=DEFAULT_PROGRESS_INTERVAL,
        help="每处理 N 个文件打印进度，0 表示关闭，默认: %(default)s",
    )
    args = parser.parse_args()
    args.device_roles = list(dict.fromkeys(args.device_roles))
    if not args.device_roles or any(not role for role in args.device_roles):
        parser.error("--device-roles 至少需要一个非空角色")
    if args.progress_interval < 0:
        parser.error("--progress-interval 不能小于 0")
    return args


def iter_json_files(dataset_root: Path, split: str) -> list[Path]:
    split_root = dataset_root / split
    if not split_root.is_dir():
        raise FileNotFoundError(f"数据划分目录不存在: {split_root}")
    return sorted(path for path in split_root.rglob("*.json") if path.is_file())


def load_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON 顶层必须是对象，实际为 {type(value).__name__}")
    return value


def collect_role_counts(graph: dict[str, Any]) -> Counter[str]:
    roles: Counter[str] = Counter()
    nodes = graph.get("nodes")
    if not isinstance(nodes, list):
        return roles
    for node in nodes:
        if not isinstance(node, dict):
            continue
        topology_node = node.get("topologyNode")
        if not isinstance(topology_node, dict):
            continue
        role = topology_node.get("DEVICEROLE")
        if role is not None:
            roles[str(role)] += 1
    return roles


def write_csv(
    path: Path,
    fieldnames: list[str],
    rows: list[dict[str, Any]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def run(args: argparse.Namespace) -> dict[str, Any]:
    dataset_root = args.dataset_root.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    splits = ["train", "val"] if args.split == "all" else [args.split]
    required_roles = set(args.device_roles)

    matched_rows: list[dict[str, Any]] = []
    error_rows: list[dict[str, str]] = []
    by_split: dict[str, dict[str, Any]] = {}

    for split in splits:
        files = iter_json_files(dataset_root, split)
        valid_files = 0
        matching_files = 0
        started_at = time.monotonic()
        print(
            f"[{split}] 开始统计 {len(files)} 个 JSON；要求角色："
            + ", ".join(args.device_roles),
            flush=True,
        )

        for index, path in enumerate(files, start=1):
            source_file = str(path.relative_to(dataset_root / split))
            try:
                graph = load_json_object(path)
                role_counts = collect_role_counts(graph)
                valid_files += 1
                if required_roles.issubset(role_counts):
                    matching_files += 1
                    matched_rows.append(
                        {
                            "split": split,
                            "source_file": source_file,
                            "required_role_counts": json.dumps(
                                {
                                    role: role_counts[role]
                                    for role in args.device_roles
                                },
                                ensure_ascii=False,
                            ),
                            "all_role_counts": json.dumps(
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
            except Exception as error:  # noqa: BLE001 - 坏文件单独记录。
                error_rows.append(
                    {
                        "split": split,
                        "source_file": source_file,
                        "error": f"{type(error).__name__}: {error}",
                    }
                )

            if args.progress_interval > 0 and (
                index % args.progress_interval == 0 or index == len(files)
            ):
                elapsed = max(time.monotonic() - started_at, 0.001)
                speed = index / elapsed
                eta = (len(files) - index) / speed if speed else 0.0
                print(
                    f"[{split}] {index}/{len(files)}，匹配 {matching_files}，"
                    f"错误 {index - valid_files}，预计剩余 {eta:.1f} 秒",
                    flush=True,
                )

        invalid_files = len(files) - valid_files
        by_split[split] = {
            "input_files": len(files),
            "valid_files": valid_files,
            "invalid_files": invalid_files,
            "matching_files": matching_files,
            "matching_ratio_among_valid_files": round(
                matching_files / valid_files if valid_files else 0.0,
                8,
            ),
        }

    valid_file_count = sum(item["valid_files"] for item in by_split.values())
    matching_file_count = sum(item["matching_files"] for item in by_split.values())
    summary = {
        "dataset_root": str(dataset_root),
        "output_dir": str(output_dir),
        "splits": splits,
        "required_device_roles": args.device_roles,
        "match_rule": (
            "每个指定角色在 nodes[].topologyNode.DEVICEROLE 中至少出现一次；"
            "严格区分大小写"
        ),
        "input_files": sum(item["input_files"] for item in by_split.values()),
        "valid_files": valid_file_count,
        "invalid_files": sum(item["invalid_files"] for item in by_split.values()),
        "matching_files": matching_file_count,
        "matching_ratio_among_valid_files": round(
            matching_file_count / valid_file_count if valid_file_count else 0.0,
            8,
        ),
        "by_split": by_split,
    }

    write_csv(
        output_dir / MATCHED_FILES_FILE,
        [
            "split",
            "source_file",
            "required_role_counts",
            "all_role_counts",
        ],
        matched_rows,
    )
    write_csv(
        output_dir / ERROR_FILE,
        ["split", "source_file", "error"],
        error_rows,
    )
    (output_dir / SUMMARY_FILE).write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


if __name__ == "__main__":
    run(parse_args())
