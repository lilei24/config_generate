#!/usr/bin/env python3
"""通过 OpenAI-compatible vLLM 服务批量推理七类拓扑任务。"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from inference_common import (
    SYSTEM_PROMPT,
    build_prompt,
    collect_samples,
    elapsed_text,
    load_json_object,
    parse_model_output,
    successful_result,
    write_csv,
    write_json_atomic,
)
from task_specs import TASK_SPECS, get_task_spec


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", choices=sorted(TASK_SPECS), required=True)
    parser.add_argument(
        "--dataset-root",
        type=Path,
        default=None,
        help="任务数据集根目录；默认使用任务注册表中的目录",
    )
    parser.add_argument(
        "--hidden-root",
        type=Path,
        default=None,
        help="without_answer 根目录；默认: DATASET_ROOT/without_answer",
    )
    parser.add_argument(
        "--answer-root",
        type=Path,
        default=None,
        help="with_answer 根目录；默认: DATASET_ROOT/with_answer",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help="推理结果根目录；默认使用任务注册表中的目录",
    )
    parser.add_argument("--split", choices=("train", "val", "all"), default="val")
    parser.add_argument("--base-url", default="http://localhost:8000/v1")
    parser.add_argument("--api-key", default="empty")
    parser.add_argument("--model", default="qwen3-8b")
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--request-timeout", type=float, default=600.0)
    parser.add_argument("--retries", type=int, default=1)
    parser.add_argument("--retry-wait-seconds", type=float, default=5.0)
    parser.add_argument("--wait-seconds", type=float, default=0.0)
    parser.add_argument("--enable-thinking", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--progress-interval", type=int, default=1)
    parser.add_argument("--indent", type=int, default=2)
    args = parser.parse_args()
    if args.temperature < 0:
        parser.error("--temperature 不能小于 0")
    if args.request_timeout <= 0:
        parser.error("--request-timeout 必须大于 0")
    if args.retries < 0 or args.retry_wait_seconds < 0:
        parser.error("重试次数和重试等待时间不能小于 0")
    if args.wait_seconds < 0 or args.progress_interval < 0:
        parser.error("等待时间和进度间隔不能小于 0")
    if args.limit is not None and args.limit < 0:
        parser.error("--limit 不能小于 0")
    if args.indent < 0:
        parser.error("--indent 不能小于 0")
    return args


def import_openai() -> Any:
    try:
        from openai import OpenAI
    except ImportError as error:
        raise RuntimeError("缺少 openai 依赖，请执行 pip install openai") from error
    return OpenAI


def request_one(
    client: Any,
    args: argparse.Namespace,
    spec: Any,
    prompt: str,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    started_at = time.monotonic()
    raw_output = ""
    last_error: Exception | None = None
    error_stage = "request"
    attempts = args.retries + 1
    for attempt in range(1, attempts + 1):
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
        except Exception as error:  # 单样本请求失败需要记录并继续。
            last_error = error
            error_stage = "request"
        else:
            try:
                answer = parse_model_output(raw_output, spec)
                return answer, {
                    "success": True,
                    "error_stage": None,
                    "error": None,
                    "model": args.model,
                    "base_url": args.base_url,
                    "thinking_enabled": args.enable_thinking,
                    "attempts": attempt,
                    "duration_seconds": round(time.monotonic() - started_at, 6),
                }
            except Exception as error:  # 解析失败同样允许重试。
                last_error = error
                error_stage = "model_output_parse"
        if attempt < attempts and args.retry_wait_seconds > 0:
            time.sleep(args.retry_wait_seconds)

    error_text = (
        f"{type(last_error).__name__}: {last_error}"
        if last_error is not None
        else "unknown inference error"
    )
    metadata = {
        "success": False,
        "error_stage": error_stage,
        "error": error_text,
        "model": args.model,
        "base_url": args.base_url,
        "thinking_enabled": args.enable_thinking,
        "attempts": attempts,
        "duration_seconds": round(time.monotonic() - started_at, 6),
    }
    if raw_output:
        metadata["raw_model_output"] = raw_output
    return None, metadata


def main() -> None:
    args = parse_args()
    spec = get_task_spec(args.task)
    dataset_root = (args.dataset_root or spec.dataset_root).resolve()
    hidden_root = (args.hidden_root or dataset_root / "without_answer").resolve()
    answer_root = (args.answer_root or dataset_root / "with_answer").resolve()
    output_root = (args.output_root or spec.result_root).resolve()
    samples = collect_samples(hidden_root, answer_root, output_root, args.split)
    if args.limit is not None:
        samples = samples[: args.limit]
    if not samples:
        raise FileNotFoundError("没有找到待推理 JSON")

    OpenAI = import_openai()
    client = OpenAI(
        base_url=args.base_url,
        api_key=args.api_key,
        timeout=args.request_timeout,
    )
    output_root.mkdir(parents=True, exist_ok=True)
    succeeded = failed = skipped = 0
    errors: list[dict[str, Any]] = []
    started_at = time.monotonic()

    for index, sample in enumerate(samples, start=1):
        if args.resume and successful_result(sample.output_path):
            skipped += 1
        else:
            metadata: dict[str, Any]
            model_output: dict[str, Any] | None = None
            try:
                hidden_document = load_json_object(sample.hidden_path)
                if "task_answer" in hidden_document:
                    raise ValueError("without_answer 样本不应包含 task_answer")
                answer_document = load_json_object(sample.answer_path)
                if not isinstance(answer_document.get("task_answer"), dict):
                    raise ValueError("with_answer 样本缺少 task_answer")
                model_output, metadata = request_one(
                    client,
                    args,
                    spec,
                    build_prompt(hidden_document),
                )
            except Exception as error:  # 坏样本不能中断整个批次。
                metadata = {
                    "success": False,
                    "error_stage": "sample_processing",
                    "error": f"{type(error).__name__}: {error}",
                    "model": args.model,
                    "base_url": args.base_url,
                    "attempts": 0,
                    "duration_seconds": 0.0,
                }
                try:
                    answer_document = load_json_object(sample.answer_path)
                except Exception:
                    answer_document = {
                        "source_file": str(sample.relative_path),
                        "task_answer": None,
                    }

            result_document = dict(answer_document)
            result_document["model-output"] = model_output
            result_document["inference_metadata"] = metadata
            write_json_atomic(sample.output_path, result_document, args.indent)
            if metadata["success"]:
                succeeded += 1
            else:
                failed += 1
                errors.append(
                    {
                        "split": sample.split,
                        "source_file": str(sample.relative_path),
                        "output_file": str(sample.output_path),
                        "error_stage": metadata["error_stage"],
                        "error": metadata["error"],
                    }
                )

        if args.progress_interval and (
            index % args.progress_interval == 0 or index == len(samples)
        ):
            print(
                f"[{index}/{len(samples)}] succeeded={succeeded} "
                f"failed={failed} skipped={skipped} elapsed={elapsed_text(started_at)}",
                flush=True,
            )
        if args.wait_seconds > 0:
            time.sleep(args.wait_seconds)

    summary = {
        "task": spec.name,
        "dataset_root": str(dataset_root),
        "output_root": str(output_root),
        "split": args.split,
        "model": args.model,
        "total_samples": len(samples),
        "succeeded": succeeded,
        "failed": failed,
        "skipped": skipped,
        "elapsed_seconds": round(time.monotonic() - started_at, 3),
    }
    write_json_atomic(output_root / "batch_summary.json", summary, args.indent)
    write_csv(output_root / "batch_errors.csv", errors)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

