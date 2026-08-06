#!/usr/bin/env python3
"""排除指定角色共现文件后，统计剩余文件的 DEVICEROLE 组合分布。"""

from __future__ import annotations

import argparse
import csv
import json
import time
from collections import Counter
from pathlib import Path
from typing import Any


DEFAULT_DATASET_ROOT = Path("datasets")
DEFAULT_OUTPUT_DIR = Path("/tmp/device_role_combination_analysis")
DEFAULT_EXCLUDED_COOCCURRING_ROLES = ("AP", "CORE")
DEFAULT_SPLIT = "all"
DEFAULT_PROGRESS_INTERVAL = 100

ROLE_DISPLAY_ORDER = (
    "AP",
    "ACC",
    "AGG",
    "CORE",
    "Gateway+CORE",
    "Gateway_vRR",
    "Gateway",
    "Firewall",
    "WAC",
)
NO_VALID_ROLE = "<no-valid-role>"

SUMMARY_FILE = "device_role_combination_summary.json"
DISTRIBUTION_FILE = "device_role_combination_distribution.csv"
FILE_DETAILS_FILE = "retained_file_role_combinations.csv"
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
        "--exclude-cooccurring-roles",
        nargs="+",
        default=list(DEFAULT_EXCLUDED_COOCCURRING_ROLES),
        metavar="ROLE",
        help="同时出现时排除该文件的角色集合，默认: AP CORE",
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
    args.exclude_cooccurring_roles = list(
        dict.fromkeys(args.exclude_cooccurring_roles)
    )
    if not args.exclude_cooccurring_roles or any(
        not role for role in args.exclude_cooccurring_roles
    ):
        parser.error("--exclude-cooccurring-roles 至少需要一个非空角色")
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
    role_counts: Counter[str] = Counter()
    nodes = graph.get("nodes")
    if not isinstance(nodes, list):
        return role_counts
    for node in nodes:
        if not isinstance(node, dict):
            continue
        topology_node = node.get("topologyNode")
        if not isinstance(topology_node, dict):
            continue
        role = topology_node.get("DEVICEROLE")
        if role is not None and str(role):
            role_counts[str(role)] += 1
    return role_counts


def role_sort_key(role: str) -> tuple[int, str]:
    try:
        return ROLE_DISPLAY_ORDER.index(role), role
    except ValueError:
        return len(ROLE_DISPLAY_ORDER), role


def role_combination(role_counts: Counter[str]) -> tuple[str, ...]:
    if not role_counts:
        return (NO_VALID_ROLE,)
    return tuple(sorted(role_counts, key=role_sort_key))


def combination_text(combination: tuple[str, ...]) -> str:
    return " + ".join(combination)


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


def distribution_rows(
    scope: str,
    counts: Counter[tuple[str, ...]],
) -> list[dict[str, Any]]:
    total = sum(counts.values())
    return [
        {
            "scope": scope,
            "role_combination": combination_text(combination),
            "role_types": len(combination) if combination != (NO_VALID_ROLE,) else 0,
            "file_count": count,
            "ratio_among_retained_files": round(count / total if total else 0.0, 8),
        }
        for combination, count in sorted(
            counts.items(),
            key=lambda item: (-item[1], combination_text(item[0])),
        )
    ]


def run(args: argparse.Namespace) -> dict[str, Any]:
    dataset_root = args.dataset_root.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    splits = ["train", "val"] if args.split == "all" else [args.split]
    excluded_roles = set(args.exclude_cooccurring_roles)

    file_rows: list[dict[str, Any]] = []
    error_rows: list[dict[str, str]] = []
    distribution: Counter[tuple[str, ...]] = Counter()
    distribution_by_split: dict[str, Counter[tuple[str, ...]]] = {}
    by_split: dict[str, dict[str, Any]] = {}

    for split in splits:
        files = iter_json_files(dataset_root, split)
        split_distribution: Counter[tuple[str, ...]] = Counter()
        valid_files = 0
        excluded_files = 0
        retained_files = 0
        started_at = time.monotonic()
        print(
            f"[{split}] 开始统计 {len(files)} 个 JSON；排除角色共现："
            + ", ".join(args.exclude_cooccurring_roles),
            flush=True,
        )

        for index, path in enumerate(files, start=1):
            source_file = str(path.relative_to(dataset_root / split))
            try:
                graph = load_json_object(path)
                role_counts = collect_role_counts(graph)
                valid_files += 1
                if excluded_roles.issubset(role_counts):
                    excluded_files += 1
                else:
                    retained_files += 1
                    combination = role_combination(role_counts)
                    split_distribution[combination] += 1
                    distribution[combination] += 1
                    file_rows.append(
                        {
                            "split": split,
                            "source_file": source_file,
                            "role_combination": combination_text(combination),
                            "role_types": (
                                len(combination)
                                if combination != (NO_VALID_ROLE,)
                                else 0
                            ),
                            "role_counts": json.dumps(
                                {
                                    role: role_counts[role]
                                    for role in combination
                                    if role != NO_VALID_ROLE
                                },
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
                    f"[{split}] {index}/{len(files)}，排除 {excluded_files}，"
                    f"保留 {retained_files}，错误 {index - valid_files}，"
                    f"预计剩余 {eta:.1f} 秒",
                    flush=True,
                )

        distribution_by_split[split] = split_distribution
        by_split[split] = {
            "input_files": len(files),
            "valid_files": valid_files,
            "invalid_files": len(files) - valid_files,
            "excluded_cooccurrence_files": excluded_files,
            "retained_files": retained_files,
            "distinct_role_combinations": len(split_distribution),
        }

    distribution_output_rows: list[dict[str, Any]] = []
    if len(splits) > 1:
        distribution_output_rows.extend(distribution_rows("all", distribution))
    for split in splits:
        distribution_output_rows.extend(
            distribution_rows(split, distribution_by_split[split])
        )

    summary = {
        "dataset_root": str(dataset_root),
        "output_dir": str(output_dir),
        "splits": splits,
        "excluded_cooccurring_roles": args.exclude_cooccurring_roles,
        "exclusion_rule": (
            "指定角色全部在同一文件的 nodes[].topologyNode.DEVICEROLE 中"
            "至少出现一次时排除；严格区分大小写"
        ),
        "combination_rule": "对保留文件中的 DEVICEROLE 去重后形成精确角色组合",
        "input_files": sum(item["input_files"] for item in by_split.values()),
        "valid_files": sum(item["valid_files"] for item in by_split.values()),
        "invalid_files": sum(item["invalid_files"] for item in by_split.values()),
        "excluded_cooccurrence_files": sum(
            item["excluded_cooccurrence_files"] for item in by_split.values()
        ),
        "retained_files": sum(item["retained_files"] for item in by_split.values()),
        "distinct_role_combinations": len(distribution),
        "by_split": by_split,
    }

    write_csv(
        output_dir / DISTRIBUTION_FILE,
        [
            "scope",
            "role_combination",
            "role_types",
            "file_count",
            "ratio_among_retained_files",
        ],
        distribution_output_rows,
    )
    write_csv(
        output_dir / FILE_DETAILS_FILE,
        [
            "split",
            "source_file",
            "role_combination",
            "role_types",
            "role_counts",
        ],
        file_rows,
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
