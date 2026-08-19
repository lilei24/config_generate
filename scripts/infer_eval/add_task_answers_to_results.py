#!/usr/bin/env python3
"""按相同相对路径将标准 task_answer 补充到推理结果 JSON。"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from pathlib import Path
from typing import Any


DEFAULT_OUTPUT_ROOT = Path("/tmp/results_with_task_answer")
DEFAULT_SPLIT = "all"
DEFAULT_PROGRESS_INTERVAL = 100

SUMMARY_FILE = "add_task_answers_summary.json"
ISSUES_FILE = "add_task_answers_issues.jsonl"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "result_root",
        type=Path,
        help="缺少 task_answer 的推理结果根目录，目录下包含 train/val",
    )
    parser.add_argument(
        "answer_root",
        type=Path,
        help="包含 task_answer 的标准答案根目录，目录下包含 train/val",
    )
    parser.add_argument(
        "-o",
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="补全结果输出根目录，默认: %(default)s",
    )
    parser.add_argument(
        "--split",
        choices=["train", "val", "all"],
        default=DEFAULT_SPLIT,
        help="处理 train、val 或全部数据，默认: %(default)s",
    )
    parser.add_argument(
        "--progress-interval",
        type=int,
        default=DEFAULT_PROGRESS_INTERVAL,
        help="每处理 N 个文件打印一次进度，0 表示关闭，默认: %(default)s",
    )
    parser.add_argument("--indent", type=int, default=2)
    args = parser.parse_args()
    if args.progress_interval < 0:
        parser.error("--progress-interval 不能小于 0")
    if args.indent < 0:
        parser.error("--indent 不能小于 0")
    return args


def load_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON 顶层必须是对象，实际为 {type(value).__name__}")
    return value


def write_json(path: Path, value: Any, indent: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=indent) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def append_issue(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(value, ensure_ascii=False) + "\n")


def json_files(split_root: Path) -> list[Path]:
    if not split_root.is_dir():
        raise FileNotFoundError(f"数据划分目录不存在: {split_root}")
    return sorted(path for path in split_root.rglob("*.json") if path.is_file())


def remove_stale_output(path: Path) -> None:
    if path.is_file():
        path.unlink()
    temporary = path.with_name(path.name + ".tmp")
    if temporary.is_file():
        temporary.unlink()


def issue_record(
    split: str,
    relative_path: Path,
    issue: str,
    detail: str,
) -> dict[str, str]:
    return {
        "split": split,
        "source_file": str(relative_path),
        "issue": issue,
        "detail": detail,
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    result_root = args.result_root.resolve()
    answer_root = args.answer_root.resolve()
    output_root = args.output_root.resolve()
    if output_root == result_root:
        raise ValueError("output_root 不能与 result_root 相同，以免覆盖原始推理结果")
    if output_root == answer_root:
        raise ValueError("output_root 不能与 answer_root 相同，以免覆盖标准答案")

    output_root.mkdir(parents=True, exist_ok=True)
    issues_path = output_root / ISSUES_FILE
    if issues_path.exists():
        issues_path.unlink()
    splits = ["train", "val"] if args.split == "all" else [args.split]
    summary: dict[str, Any] = {
        "result_root": str(result_root),
        "answer_root": str(answer_root),
        "output_root": str(output_root),
        "matching_rule": "same split and relative JSON path",
        "splits": {},
    }

    for split in splits:
        result_split_root = result_root / split
        answer_split_root = answer_root / split
        output_split_root = output_root / split
        files = json_files(result_split_root)
        counts: Counter[str] = Counter()
        started_at = time.time()
        print(f"[{split}] found {len(files)} result JSON files", flush=True)

        for index, result_path in enumerate(files, start=1):
            relative_path = result_path.relative_to(result_split_root)
            answer_path = answer_split_root / relative_path
            output_path = output_split_root / relative_path
            remove_stale_output(output_path)

            try:
                result_document = load_json_object(result_path)
            except Exception as error:  # noqa: BLE001 - 单文件错误不能中断批处理。
                issue = "result-json-error"
                counts[issue] += 1
                append_issue(
                    issues_path,
                    issue_record(
                        split,
                        relative_path,
                        issue,
                        f"{type(error).__name__}: {error}",
                    ),
                )
            else:
                if "model-output" not in result_document:
                    issue = "result-missing-model-output"
                    counts[issue] += 1
                    append_issue(
                        issues_path,
                        issue_record(
                            split,
                            relative_path,
                            issue,
                            "结果 JSON 不包含 model-output 字段",
                        ),
                    )
                elif "task_answer" in result_document:
                    write_json(output_path, result_document, args.indent)
                    counts["existing_task_answer_files"] += 1
                    counts["output_files"] += 1
                elif not answer_path.is_file():
                    issue = "answer-file-not-found"
                    counts[issue] += 1
                    append_issue(
                        issues_path,
                        issue_record(
                            split,
                            relative_path,
                            issue,
                            str(answer_path),
                        ),
                    )
                else:
                    try:
                        answer_document = load_json_object(answer_path)
                    except Exception as error:  # noqa: BLE001
                        issue = "answer-json-error"
                        counts[issue] += 1
                        append_issue(
                            issues_path,
                            issue_record(
                                split,
                                relative_path,
                                issue,
                                f"{type(error).__name__}: {error}",
                            ),
                        )
                    else:
                        task_answer = answer_document.get("task_answer")
                        if not isinstance(task_answer, dict):
                            issue = "answer-missing-valid-task-answer"
                            counts[issue] += 1
                            append_issue(
                                issues_path,
                                issue_record(
                                    split,
                                    relative_path,
                                    issue,
                                    "task_answer 必须是 JSON 对象",
                                ),
                            )
                        else:
                            result_document["task_answer"] = task_answer
                            write_json(output_path, result_document, args.indent)
                            counts["injected_task_answer_files"] += 1
                            counts["output_files"] += 1

            if args.progress_interval > 0 and (
                index % args.progress_interval == 0 or index == len(files)
            ):
                elapsed = max(time.time() - started_at, 0.001)
                speed = index / elapsed
                eta = (len(files) - index) / speed if speed else 0.0
                print(
                    f"[{split}] {index}/{len(files)}，"
                    f"已补全 {counts['injected_task_answer_files']}，"
                    f"已输出 {counts['output_files']}，"
                    f"失败 {index - counts['output_files']}，"
                    f"预计剩余 {eta:.1f} 秒",
                    flush=True,
                )

        summary["splits"][split] = {
            "input_result_files": len(files),
            "output_files": counts["output_files"],
            "injected_task_answer_files": counts[
                "injected_task_answer_files"
            ],
            "existing_task_answer_files": counts["existing_task_answer_files"],
            "failed_files": len(files) - counts["output_files"],
            "issue_counts": {
                key: value
                for key, value in sorted(counts.items())
                if key
                not in {
                    "output_files",
                    "injected_task_answer_files",
                    "existing_task_answer_files",
                }
            },
        }

    write_json(output_root / SUMMARY_FILE, summary, args.indent)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return summary


if __name__ == "__main__":
    run(parse_args())
