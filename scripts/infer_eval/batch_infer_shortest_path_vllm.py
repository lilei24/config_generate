#!/usr/bin/env python3
"""使用 OpenAI-compatible vLLM 服务批量执行两节点全部最短路径任务。"""

from __future__ import annotations

import argparse
import csv
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_HIDDEN_ROOT = Path("shortest_path_dataset/without_answer")
DEFAULT_ANSWER_ROOT = Path("shortest_path_dataset/with_answer")
DEFAULT_OUTPUT_ROOT = Path("vllm-results/shortest_path")
DEFAULT_SPLIT = "val"
DEFAULT_BASE_URL = "http://localhost:8000/v1"
DEFAULT_API_KEY = "empty"
DEFAULT_MODEL = "qwen3-8b"
DEFAULT_TEMPERATURE = 0.2
DEFAULT_REQUEST_TIMEOUT = 600.0
DEFAULT_RETRIES = 1
DEFAULT_RETRY_WAIT_SECONDS = 5.0
DEFAULT_WAIT_SECONDS = 0.0
DEFAULT_PROGRESS_INTERVAL = 1

SUMMARY_FILE = "batch_summary.json"
ERROR_FILE = "batch_errors.csv"

SYSTEM_PROMPT = """你是网络物理拓扑分析助手。请严格根据输入的完整拓扑 JSON 计算答案，不得猜测不存在的节点或链路。不要输出解释、Markdown 代码块或思考过程，只输出一个合法 JSON 对象。"""

USER_PROMPT_TEMPLATE = """请完成输入 JSON 中 task_question 描述的两节点全部最短路径任务。

要求：
1. path_length 是链路跳数，即路径节点数减一。
2. 如果存在多条等长最短路径，必须全部输出。
3. paths 使用节点 ID，并按照源节点到目标节点的方向排列。
4. path_role_sequences 与 paths 一一对应，填写每个节点的 topologyNode.DEVICEROLE。
5. path_device_names 与 paths 一一对应，填写每个节点的 devices.NAME 或 device.NAME。
6. 只输出以下结构的 JSON 对象：
{{
  "path_length": 3,
  "paths": [
    ["NODE_A", "NODE_B", "NODE_C", "NODE_D"]
  ],
  "path_role_sequences": [
    ["AP", "ACC", "AGG", "CORE"]
  ],
  "path_device_names": [
    ["AP-01", "SW-01", "SW-02", "CORE-01"]
  ]
}}

【完整任务 JSON】
{task_json}
"""


@dataclass
class InferenceResult:
    success: bool
    answer: dict[str, Any] | None
    error_stage: str | None
    error: str | None
    raw_model_output: str | None
    attempts: int
    duration_seconds: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--hidden-root",
        type=Path,
        default=DEFAULT_HIDDEN_ROOT,
        help="without_answer 数据集根目录，默认: %(default)s",
    )
    parser.add_argument(
        "--answer-root",
        type=Path,
        default=DEFAULT_ANSWER_ROOT,
        help="with_answer 数据集根目录，默认: %(default)s",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="推理结果根目录，默认: %(default)s",
    )
    parser.add_argument(
        "--split",
        choices=["train", "val", "all"],
        default=DEFAULT_SPLIT,
        help="处理的数据划分，默认: %(default)s",
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--api-key", default=DEFAULT_API_KEY)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--temperature", type=float, default=DEFAULT_TEMPERATURE
    )
    parser.add_argument(
        "--request-timeout",
        type=float,
        default=DEFAULT_REQUEST_TIMEOUT,
        help="单次 API 请求超时秒数，默认: %(default)s",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=DEFAULT_RETRIES,
        help="首次请求失败后的重试次数，默认: %(default)s",
    )
    parser.add_argument(
        "--retry-wait-seconds",
        type=float,
        default=DEFAULT_RETRY_WAIT_SECONDS,
    )
    parser.add_argument(
        "--wait-seconds",
        type=float,
        default=DEFAULT_WAIT_SECONDS,
        help="每个样本处理完成后等待秒数，默认: %(default)s",
    )
    parser.add_argument(
        "--progress-interval",
        type=int,
        default=DEFAULT_PROGRESS_INTERVAL,
        help="每处理 N 个文件打印进度，0 表示关闭，默认: %(default)s",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="只处理按文件名字典序排列后的前 N 个样本",
    )
    parser.add_argument(
        "--enable-thinking",
        action="store_true",
        help="开启模型思考模式；默认关闭",
    )
    existing_group = parser.add_mutually_exclusive_group()
    existing_group.add_argument(
        "--skip-existing",
        action="store_true",
        help="结果文件只要存在就跳过，不检查此前推理是否成功",
    )
    existing_group.add_argument(
        "--resume",
        action="store_true",
        help="断点续推：跳过已有成功结果，重新处理失败或损坏的结果",
    )
    parser.add_argument("--indent", type=int, default=2)
    args = parser.parse_args()

    if args.temperature < 0:
        parser.error("--temperature 不能小于 0")
    if args.request_timeout <= 0:
        parser.error("--request-timeout 必须大于 0")
    if args.retries < 0:
        parser.error("--retries 不能小于 0")
    if args.retry_wait_seconds < 0 or args.wait_seconds < 0:
        parser.error("等待时间不能小于 0")
    if args.progress_interval < 0:
        parser.error("--progress-interval 不能小于 0")
    if args.limit is not None and args.limit < 0:
        parser.error("--limit 不能小于 0")
    if args.indent < 0:
        parser.error("--indent 不能小于 0")
    return args


def import_openai() -> Any:
    try:
        from openai import OpenAI
    except ImportError as error:
        raise RuntimeError(
            "缺少 openai 依赖，请先执行: pip install openai"
        ) from error
    return OpenAI


def load_json_object(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"JSON 顶层必须是对象，实际为 {type(data).__name__}")
    return data


def has_successful_result(path: Path, run_field: str) -> bool:
    """仅将状态成功且包含结构化模型回答的结果视为已完成。"""

    if not path.is_file():
        return False
    try:
        document = load_json_object(path)
    except Exception:  # noqa: BLE001 - 损坏结果需要在续推时覆盖。
        return False
    run_info = document.get(run_field)
    return bool(
        isinstance(run_info, dict)
        and run_info.get("success") is True
        and isinstance(document.get("model-output"), dict)
    )


def write_json_atomic(path: Path, data: dict[str, Any], indent: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=indent) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)


def iter_samples(hidden_root: Path, split: str) -> list[Path]:
    split_root = hidden_root / split
    if not split_root.is_dir():
        raise FileNotFoundError(f"without_answer 数据目录不存在: {split_root}")
    return sorted(path for path in split_root.rglob("*.json") if path.is_file())


def build_prompt(hidden_sample: dict[str, Any]) -> str:
    task_json = json.dumps(
        hidden_sample,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return USER_PROMPT_TEMPLATE.format(task_json=task_json)


def strip_markdown_code_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def parse_model_answer(text: str) -> dict[str, Any]:
    cleaned = strip_markdown_code_fence(text)
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    for position, character in enumerate(cleaned):
        if character != "{":
            continue
        try:
            candidate, _ = decoder.raw_decode(cleaned, position)
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict) and (
            "path_length" in candidate or "paths" in candidate
        ):
            return candidate
    raise ValueError("模型回答中没有可解析的最短路径 JSON 对象")


def invoke_vllm(
    client: Any,
    args: argparse.Namespace,
    prompt: str,
) -> InferenceResult:
    started_at = time.monotonic()
    total_attempts = args.retries + 1
    last_error: Exception | None = None
    last_error_stage = "request"
    raw_output: str | None = None

    for attempt in range(1, total_attempts + 1):
        try:
            response = client.chat.completions.create(
                model=args.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=args.temperature,
                stream=False,
                extra_body={
                    "chat_template_kwargs": {
                        "enable_thinking": args.enable_thinking,
                    }
                },
            )
            content = response.choices[0].message.content
            if not isinstance(content, str) or not content.strip():
                raise ValueError("模型返回内容为空")
            raw_output = content
        except Exception as error:  # noqa: BLE001 - API 错误需要重试并记录。
            last_error = error
            last_error_stage = "request"
            if attempt < total_attempts and args.retry_wait_seconds > 0:
                time.sleep(args.retry_wait_seconds)
            continue

        try:
            answer = parse_model_answer(raw_output)
        except Exception as error:  # noqa: BLE001 - 解析错误同样允许重试。
            last_error = error
            last_error_stage = "model_output_parse"
            if attempt < total_attempts and args.retry_wait_seconds > 0:
                time.sleep(args.retry_wait_seconds)
            continue

        return InferenceResult(
            success=True,
            answer=answer,
            error_stage=None,
            error=None,
            raw_model_output=raw_output,
            attempts=attempt,
            duration_seconds=time.monotonic() - started_at,
        )

    error_text = (
        f"{type(last_error).__name__}: {last_error}"
        if last_error is not None
        else "unknown-vllm-error"
    )
    return InferenceResult(
        success=False,
        answer=None,
        error_stage=last_error_stage,
        error=error_text,
        raw_model_output=raw_output,
        attempts=total_attempts,
        duration_seconds=time.monotonic() - started_at,
    )


def build_output_document(
    answer_document: dict[str, Any],
    result: InferenceResult,
    args: argparse.Namespace,
) -> dict[str, Any]:
    output = dict(answer_document)
    output["model-output"] = result.answer
    output["vllm-run"] = {
        "success": result.success,
        "error_stage": result.error_stage,
        "error": result.error,
        "model": args.model,
        "base_url": args.base_url,
        "thinking_enabled": args.enable_thinking,
        "attempts": result.attempts,
        "duration_seconds": round(result.duration_seconds, 6),
    }
    if not result.success and result.raw_model_output is not None:
        output["vllm-run"]["raw_model_output"] = result.raw_model_output
    return output


def write_error_csv(path: Path, errors: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "split",
        "source_file",
        "output_file",
        "error_stage",
        "error",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(errors)


def main() -> None:
    args = parse_args()
    hidden_root = args.hidden_root.resolve()
    answer_root = args.answer_root.resolve()
    output_root = args.output_root.resolve()
    splits = ["train", "val"] if args.split == "all" else [args.split]

    sample_items: list[tuple[str, Path]] = []
    for split in splits:
        sample_items.extend((split, path) for path in iter_samples(hidden_root, split))
    if args.limit is not None:
        sample_items = sample_items[: args.limit]
    if not sample_items:
        raise FileNotFoundError("没有找到需要推理的 without_answer JSON")

    OpenAI = import_openai()
    client = OpenAI(
        base_url=args.base_url,
        api_key=args.api_key,
        timeout=args.request_timeout,
    )
    output_root.mkdir(parents=True, exist_ok=True)

    succeeded = 0
    failed = 0
    skipped = 0
    errors: list[dict[str, Any]] = []
    by_split = {
        split: {"input_files": 0, "succeeded": 0, "failed": 0, "skipped": 0}
        for split in splits
    }
    started_at = time.monotonic()

    for index, (split, hidden_path) in enumerate(sample_items, start=1):
        relative_path = hidden_path.relative_to(hidden_root / split)
        answer_path = answer_root / split / relative_path
        output_path = output_root / split / relative_path
        by_split[split]["input_files"] += 1

        should_skip = (
            args.skip_existing and output_path.is_file()
        ) or (
            args.resume and has_successful_result(output_path, "vllm-run")
        )
        if should_skip:
            skipped += 1
            by_split[split]["skipped"] += 1
        else:
            try:
                answer_document = load_json_object(answer_path)
                hidden_document = load_json_object(hidden_path)
                if "task_answer" in hidden_document:
                    raise ValueError("without_answer 文件不应包含 task_answer")
                result = invoke_vllm(client, args, build_prompt(hidden_document))
                output_document = build_output_document(answer_document, result, args)
                write_json_atomic(output_path, output_document, args.indent)

                if result.success:
                    succeeded += 1
                    by_split[split]["succeeded"] += 1
                else:
                    failed += 1
                    by_split[split]["failed"] += 1
                    errors.append(
                        {
                            "split": split,
                            "source_file": str(relative_path),
                            "output_file": str(output_path),
                            "error_stage": result.error_stage,
                            "error": result.error,
                        }
                    )
            except Exception as error:  # noqa: BLE001 - 单样本错误不能中断批次。
                failed += 1
                by_split[split]["failed"] += 1
                error_text = f"{type(error).__name__}: {error}"
                errors.append(
                    {
                        "split": split,
                        "source_file": str(relative_path),
                        "output_file": str(output_path),
                        "error_stage": "sample_processing",
                        "error": error_text,
                    }
                )
                # 只要标准答案可读，样本处理错误也生成逐文件结果。
                try:
                    answer_document = load_json_object(answer_path)
                    failed_result = InferenceResult(
                        success=False,
                        answer=None,
                        error_stage="sample_processing",
                        error=error_text,
                        raw_model_output=None,
                        attempts=0,
                        duration_seconds=0.0,
                    )
                    write_json_atomic(
                        output_path,
                        build_output_document(answer_document, failed_result, args),
                        args.indent,
                    )
                except Exception:
                    pass

        if args.progress_interval > 0 and (
            index % args.progress_interval == 0 or index == len(sample_items)
        ):
            elapsed = max(time.monotonic() - started_at, 0.001)
            speed = index / elapsed
            eta = (len(sample_items) - index) / speed if speed else 0.0
            print(
                f"进度 {index}/{len(sample_items)}，成功 {succeeded}，"
                f"失败 {failed}，跳过 {skipped}，预计剩余 {eta:.1f} 秒",
                flush=True,
            )

        if args.wait_seconds > 0:
            time.sleep(args.wait_seconds)

    elapsed_seconds = time.monotonic() - started_at
    summary = {
        "hidden_root": str(hidden_root),
        "answer_root": str(answer_root),
        "output_root": str(output_root),
        "splits": splits,
        "model": args.model,
        "base_url": args.base_url,
        "thinking_enabled": args.enable_thinking,
        "resume": args.resume,
        "skip_existing": args.skip_existing,
        "context_mode": "full_without_answer_json",
        "total_files": len(sample_items),
        "succeeded": succeeded,
        "failed": failed,
        "skipped": skipped,
        "elapsed_seconds": round(elapsed_seconds, 3),
        "by_split": by_split,
    }
    write_json_atomic(output_root / SUMMARY_FILE, summary, args.indent)
    write_error_csv(output_root / ERROR_FILE, errors)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
