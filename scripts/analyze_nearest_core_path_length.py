#!/usr/bin/env python3
"""统计“AP 到最近 CORE”任务数据集中的最短路径长度。

默认读取 ``nearest_core_dataset/with_answer/{train,val}``，直接使用已经构造好的
``task_answer.path_length``，避免重新随机选择 AP 后与实际任务样本不一致。

输出格式与 analyze_graph_max_finite_shortest_path.py 一致：只生成一个格式化 JSON，
顶层包含全局汇总 summary 和逐文件结果 per_file；终端打印进度、速度、ETA、
长度汇总与长度分布。
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any, Dict, Iterable, List, Tuple


DEFAULT_INPUT_ROOT = Path("nearest_core_dataset/with_answer")
DEFAULT_OUTPUT_DIR = Path("/tmp/nearest_core_path_length_analysis")
DEFAULT_PROGRESS_INTERVAL = 50
OUTPUT_FILE_NAME = "nearest_core_path_length_statistics.json"


@dataclass
class NearestCorePathLengthResult:
    split: str
    source_file: str
    source_node_name: str
    nearest_core_node_names: List[str]
    nearest_core_count: int
    shortest_path_length: int | None
    shortest_path_count: int
    status: str
    detail: str = ""


def iter_json_files(
    input_root: Path,
    splits: Iterable[str],
) -> Iterable[Tuple[str, Path]]:
    for split in splits:
        split_dir = input_root / split
        if not split_dir.exists():
            continue
        for path in sorted(split_dir.rglob("*.json")):
            if path.is_file():
                yield split, path


def list_split_json_files(input_root: Path, split: str) -> List[Path]:
    return [path for _, path in iter_json_files(input_root, [split])]


def load_json(path: Path) -> Tuple[Dict[str, Any] | None, str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - 坏文件需要记录并继续分析。
        return None, str(exc)
    if not isinstance(data, dict):
        return None, f"top-level JSON type is {type(data).__name__}, expected object"
    return data, ""


def analyze_file(
    input_root: Path,
    split: str,
    path: Path,
) -> NearestCorePathLengthResult:
    source_file = str(path.relative_to(input_root))
    sample, error = load_json(path)
    if sample is None:
        return NearestCorePathLengthResult(
            split=split,
            source_file=source_file,
            source_node_name="",
            nearest_core_node_names=[],
            nearest_core_count=0,
            shortest_path_length=None,
            shortest_path_count=0,
            status="bad_json",
            detail=error,
        )

    source_node_name = sample.get("task_source_node_name")
    if not isinstance(source_node_name, str) or not source_node_name:
        return NearestCorePathLengthResult(
            split=split,
            source_file=source_file,
            source_node_name="",
            nearest_core_node_names=[],
            nearest_core_count=0,
            shortest_path_length=None,
            shortest_path_count=0,
            status="missing_source_node_name",
        )

    task_answer = sample.get("task_answer")
    if not isinstance(task_answer, dict):
        return NearestCorePathLengthResult(
            split=split,
            source_file=source_file,
            source_node_name=source_node_name,
            nearest_core_node_names=[],
            nearest_core_count=0,
            shortest_path_length=None,
            shortest_path_count=0,
            status="missing_task_answer",
        )

    path_length = task_answer.get("path_length")
    if (
        isinstance(path_length, bool)
        or not isinstance(path_length, int)
        or path_length < 0
    ):
        return NearestCorePathLengthResult(
            split=split,
            source_file=source_file,
            source_node_name=source_node_name,
            nearest_core_node_names=[],
            nearest_core_count=0,
            shortest_path_length=None,
            shortest_path_count=0,
            status="invalid_path_length",
            detail=f"value={path_length!r}",
        )

    nearest_core_names_raw = task_answer.get("nearest_core_node_names")
    if not isinstance(nearest_core_names_raw, list) or not all(
        isinstance(name, str) and name for name in nearest_core_names_raw
    ):
        return NearestCorePathLengthResult(
            split=split,
            source_file=source_file,
            source_node_name=source_node_name,
            nearest_core_node_names=[],
            nearest_core_count=0,
            shortest_path_length=None,
            shortest_path_count=0,
            status="invalid_nearest_core_node_names",
        )

    paths = task_answer.get("paths")
    if not isinstance(paths, list) or not paths:
        return NearestCorePathLengthResult(
            split=split,
            source_file=source_file,
            source_node_name=source_node_name,
            nearest_core_node_names=nearest_core_names_raw,
            nearest_core_count=len(nearest_core_names_raw),
            shortest_path_length=None,
            shortest_path_count=0,
            status="invalid_paths",
        )

    invalid_path_count = 0
    for node_path in paths:
        if (
            not isinstance(node_path, list)
            or not all(isinstance(name, str) and name for name in node_path)
            or len(node_path) - 1 != path_length
        ):
            invalid_path_count += 1
    if invalid_path_count:
        return NearestCorePathLengthResult(
            split=split,
            source_file=source_file,
            source_node_name=source_node_name,
            nearest_core_node_names=nearest_core_names_raw,
            nearest_core_count=len(nearest_core_names_raw),
            shortest_path_length=None,
            shortest_path_count=len(paths),
            status="path_length_mismatch",
            detail=f"invalid_paths={invalid_path_count}",
        )

    return NearestCorePathLengthResult(
        split=split,
        source_file=source_file,
        source_node_name=source_node_name,
        nearest_core_node_names=nearest_core_names_raw,
        nearest_core_count=len(nearest_core_names_raw),
        shortest_path_length=path_length,
        shortest_path_count=len(paths),
        status="ok",
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
        str(path_length): {
            "count": count,
            "percentage": round(count / total * 100, 2) if total else 0.0,
        }
        for path_length, count in sorted(counts.items())
    }


def build_scope_statistics(
    results: List[NearestCorePathLengthResult],
) -> Dict[str, Any]:
    valid_results = [result for result in results if result.status == "ok"]
    values = [
        result.shortest_path_length
        for result in valid_results
        if result.shortest_path_length is not None
    ]
    return {
        "input_files": len(results),
        "analyzed_samples": len(valid_results),
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


def print_terminal_summary(results: List[NearestCorePathLengthResult]) -> None:
    valid_results = [result for result in results if result.status == "ok"]
    values = [
        result.shortest_path_length
        for result in valid_results
        if result.shortest_path_length is not None
    ]
    summary = number_summary(values)
    counts = Counter(values)

    print(f"\n{'=' * 60}")
    print(f"统计完成：{len(valid_results)} 个最近 CORE 任务样本")
    print(f"{'=' * 60}")
    print("\n--- AP 到最近 CORE 最短路径长度汇总 ---")
    print(f"  count: {summary['count']}")
    print(f"  min:   {summary['min']}")
    print(f"  max:   {summary['max']}")
    print(f"  mean:  {summary['mean']}")

    print("\n--- 最短路径长度分布 ---")
    for path_length, count in sorted(counts.items()):
        percentage = count / len(values) * 100 if values else 0.0
        print(
            f"  {path_length:>5}  {terminal_bar(count, len(values))}  "
            f"{count} ({percentage:.2f}%)"
        )

    skipped_files = len(results) - len(valid_results)
    if skipped_files:
        print(f"\n跳过 {skipped_files} 个无法分析的文件")
    print(f"\n{'=' * 60}")


def build_statistics(
    input_root: Path,
    output_dir: Path,
    splits: List[str],
    progress_interval: int,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    results: List[NearestCorePathLengthResult] = []

    for split in splits:
        split_files = list_split_json_files(input_root, split)
        split_total = len(split_files)
        started_at = time.time()
        if progress_interval > 0:
            print(f"[{split}] start: {split_total} files", flush=True)

        for file_index, path in enumerate(split_files, start=1):
            results.append(analyze_file(input_root, split, path))
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
        if result.status != "ok"
    ]
    per_file = [
        {
            "split": result.split,
            "source_file": result.source_file,
            "source_node_name": result.source_node_name,
            "nearest_core_node_names": result.nearest_core_node_names,
            "nearest_core_count": result.nearest_core_count,
            "shortest_path_length": result.shortest_path_length,
            "shortest_path_count": result.shortest_path_count,
        }
        for result in results
        if result.status == "ok"
    ]
    summary = {
        "input_root": str(input_root),
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
        description="统计 AP 到最近 CORE 任务样本的最短路径长度。"
    )
    parser.add_argument(
        "input_root",
        nargs="?",
        type=Path,
        default=DEFAULT_INPUT_ROOT,
        help=(
            "最近 CORE 有答案数据集根目录，内含 train/ 和 val/。"
            f"默认：{DEFAULT_INPUT_ROOT}"
        ),
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
        help="每 N 个样本打印一次进度。0 表示不打印。默认：%(default)s",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    splits = ["train", "val"] if args.split == "all" else [args.split]
    build_statistics(
        args.input_root,
        args.output_dir,
        splits,
        args.progress_interval,
    )


if __name__ == "__main__":
    main()
