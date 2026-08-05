#!/usr/bin/env python3
"""任务 2-5 批量推理脚本共用的 vLLM 与 OpenCode 调用框架。"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


AnswerValidator = Callable[[dict[str, Any]], None]
VllmPromptBuilder = Callable[[dict[str, Any]], str]
OpenCodePromptBuilder = Callable[[str, dict[str, Any]], str]


@dataclass(frozen=True)
class TaskInferenceSpec:
    task_name: str
    default_dataset_root: Path
    default_vllm_output_root: Path
    default_opencode_output_root: Path
    default_model: str
    system_prompt: str
    build_vllm_prompt: VllmPromptBuilder
    build_opencode_prompt: OpenCodePromptBuilder
    validate_answer: AnswerValidator


@dataclass(frozen=True)
class SamplePaths:
    split: str
    relative_path: Path
    hidden_path: Path
    answer_path: Path
    output_path: Path


@dataclass
class InferenceResult:
    success: bool
    answer: dict[str, Any] | None
    error_stage: str | None
    error: str | None
    raw_output: str
    attempts: int
    duration_seconds: float
    raw_error_output: str = ""
    return_code: int | None = None
    session_id: str | None = None


def add_dataset_arguments(
    parser: argparse.ArgumentParser,
    spec: TaskInferenceSpec,
    output_root: Path,
) -> None:
    parser.add_argument(
        "--hidden-root",
        type=Path,
        default=spec.default_dataset_root / "without_answer",
        help="without_answer 数据集根目录，默认: %(default)s",
    )
    parser.add_argument(
        "--answer-root",
        type=Path,
        default=spec.default_dataset_root / "with_answer",
        help="with_answer 数据集根目录，默认: %(default)s",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=output_root,
        help="推理结果根目录，默认: %(default)s",
    )
    parser.add_argument(
        "--split",
        choices=["train", "val", "all"],
        default="val",
        help="处理的数据划分，默认: %(default)s",
    )
    parser.add_argument(
        "--progress-interval",
        type=int,
        default=1,
        help="每处理 N 个文件打印进度，0 表示关闭，默认: %(default)s",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="只处理扫描顺序中的前 N 个 JSON",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="断点续推：跳过已有成功结果，重新处理失败或损坏的结果",
    )
    parser.add_argument("--indent", type=int, default=2)


def validate_common_arguments(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
) -> None:
    if args.progress_interval < 0:
        parser.error("--progress-interval 不能小于 0")
    if args.limit is not None and args.limit < 0:
        parser.error("--limit 不能小于 0")
    if args.indent < 0:
        parser.error("--indent 不能小于 0")


def create_vllm_parser(
    description: str,
    spec: TaskInferenceSpec,
) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    add_dataset_arguments(parser, spec, spec.default_vllm_output_root)
    parser.add_argument("--base-url", default="http://localhost:8000/v1")
    parser.add_argument("--api-key", default="empty")
    parser.add_argument("--model", default=spec.default_model)
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument(
        "--request-timeout",
        type=float,
        default=600.0,
        help="单次 API 请求超时秒数，默认: %(default)s",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=1,
        help="首次请求失败后的重试次数，默认: %(default)s",
    )
    parser.add_argument("--retry-wait-seconds", type=float, default=5.0)
    parser.add_argument(
        "--wait-seconds",
        type=float,
        default=0.0,
        help="每个样本处理完成后等待秒数，默认: %(default)s",
    )
    parser.add_argument(
        "--enable-thinking",
        action="store_true",
        help="开启模型思考模式；默认关闭",
    )
    return parser


def create_opencode_parser(
    description: str,
    spec: TaskInferenceSpec,
) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    add_dataset_arguments(parser, spec, spec.default_opencode_output_root)
    parser.add_argument(
        "--opencode-command",
        default="opencode",
        help="OpenCode 可执行文件名称或路径，默认: %(default)s",
    )
    parser.add_argument(
        "--attach",
        default=None,
        help="可选 OpenCode serve 地址；省略时每个样本直接运行 opencode",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="可选 OpenCode 模型，格式为 provider/model",
    )
    parser.add_argument("--agent", default=None)
    parser.add_argument(
        "--opencode-workdir",
        type=Path,
        default=Path("opencode-harness-workspace"),
        help="OpenCode 项目和工具工作目录，默认: %(default)s",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=600.0,
        help="每次 OpenCode 调用超时秒数，默认: %(default)s",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=1,
        help="首次调用失败后的重试次数，默认: %(default)s",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只扫描样本并打印 Prompt，不调用 OpenCode、不写结果",
    )
    return parser


def validate_vllm_arguments(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
) -> None:
    validate_common_arguments(parser, args)
    if args.temperature < 0:
        parser.error("--temperature 不能小于 0")
    if args.request_timeout <= 0:
        parser.error("--request-timeout 必须大于 0")
    if args.retries < 0:
        parser.error("--retries 不能小于 0")
    if args.retry_wait_seconds < 0 or args.wait_seconds < 0:
        parser.error("等待时间不能小于 0")


def validate_opencode_arguments(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
) -> None:
    validate_common_arguments(parser, args)
    if args.timeout_seconds <= 0:
        parser.error("--timeout-seconds 必须大于 0")
    if args.retries < 0:
        parser.error("--retries 不能小于 0")


def load_json_object(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"JSON 顶层必须是对象，实际为 {type(data).__name__}")
    return data


def write_json_atomic(path: Path, data: dict[str, Any], indent: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=indent) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)


def collect_samples(
    hidden_root: Path,
    answer_root: Path,
    output_root: Path,
    split: str,
) -> list[SamplePaths]:
    splits = ["train", "val"] if split == "all" else [split]
    samples: list[SamplePaths] = []
    for split_name in splits:
        hidden_split_root = hidden_root / split_name
        answer_split_root = answer_root / split_name
        if not hidden_split_root.is_dir():
            raise FileNotFoundError(
                f"without_answer 数据目录不存在: {hidden_split_root}"
            )
        if not answer_split_root.is_dir():
            raise FileNotFoundError(
                f"with_answer 数据目录不存在: {answer_split_root}"
            )
        for hidden_path in sorted(hidden_split_root.rglob("*.json")):
            if not hidden_path.is_file():
                continue
            relative_path = hidden_path.relative_to(hidden_split_root)
            samples.append(
                SamplePaths(
                    split=split_name,
                    relative_path=relative_path,
                    hidden_path=hidden_path,
                    answer_path=answer_split_root / relative_path,
                    output_path=output_root / split_name / relative_path,
                )
            )
    return samples


def has_successful_result(path: Path, run_field: str) -> bool:
    if not path.is_file():
        return False
    try:
        document = load_json_object(path)
    except Exception:  # noqa: BLE001 - 损坏结果需要重新推理。
        return False
    run_info = document.get(run_field)
    return bool(
        isinstance(run_info, dict)
        and run_info.get("success") is True
        and isinstance(document.get("model-output"), dict)
    )


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


def parse_answer_text(
    text: str,
    validate_answer: AnswerValidator,
) -> dict[str, Any]:
    cleaned = strip_markdown_code_fence(text)
    candidates: list[dict[str, Any]] = []
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            candidates.append(parsed)
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
        if isinstance(candidate, dict) and candidate not in candidates:
            candidates.append(candidate)

    validation_errors: list[str] = []
    for candidate in candidates:
        try:
            validate_answer(candidate)
            return candidate
        except ValueError as error:
            validation_errors.append(str(error))
    if validation_errors:
        raise ValueError(
            "找到 JSON 对象但结构不符合任务要求: " + validation_errors[0]
        )
    raise ValueError("模型回答中没有 JSON 对象")


def import_openai() -> Any:
    try:
        from openai import OpenAI
    except ImportError as error:
        raise RuntimeError("缺少 openai 依赖，请执行 pip install openai") from error
    return OpenAI


def invoke_vllm(
    client: Any,
    args: argparse.Namespace,
    spec: TaskInferenceSpec,
    prompt: str,
) -> InferenceResult:
    started_at = time.monotonic()
    total_attempts = args.retries + 1
    last_error: Exception | None = None
    last_stage = "request"
    raw_output = ""
    for attempt in range(1, total_attempts + 1):
        try:
            response = client.chat.completions.create(
                model=args.model,
                messages=[
                    {"role": "system", "content": spec.system_prompt},
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
        except Exception as error:  # noqa: BLE001 - 请求异常需要记录和重试。
            last_error = error
            last_stage = "request"
            if attempt < total_attempts and args.retry_wait_seconds > 0:
                time.sleep(args.retry_wait_seconds)
            continue

        try:
            answer = parse_answer_text(raw_output, spec.validate_answer)
        except Exception as error:  # noqa: BLE001 - 解析异常同样允许重试。
            last_error = error
            last_stage = "model_output_parse"
            if attempt < total_attempts and args.retry_wait_seconds > 0:
                time.sleep(args.retry_wait_seconds)
            continue
        return InferenceResult(
            success=True,
            answer=answer,
            error_stage=None,
            error=None,
            raw_output=raw_output,
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
        error_stage=last_stage,
        error=error_text,
        raw_output=raw_output,
        attempts=total_attempts,
        duration_seconds=time.monotonic() - started_at,
    )


def build_vllm_result_document(
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
    if not result.success and result.raw_output:
        output["vllm-run"]["raw_model_output"] = result.raw_output
    return output


def write_error_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "split",
        "source_file",
        "output_file",
        "error_stage",
        "error",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def run_vllm(args: argparse.Namespace, spec: TaskInferenceSpec) -> dict[str, Any]:
    hidden_root = args.hidden_root.resolve()
    answer_root = args.answer_root.resolve()
    output_root = args.output_root.resolve()
    samples = collect_samples(
        hidden_root,
        answer_root,
        output_root,
        args.split,
    )
    if args.limit is not None:
        samples = samples[: args.limit]
    if not samples:
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
    started_at = time.monotonic()

    for index, sample in enumerate(samples, start=1):
        if args.resume and has_successful_result(sample.output_path, "vllm-run"):
            skipped += 1
        else:
            try:
                hidden_document = load_json_object(sample.hidden_path)
                if "task_answer" in hidden_document:
                    raise ValueError("without_answer 文件不应包含 task_answer")
                answer_document = load_json_object(sample.answer_path)
                result = invoke_vllm(
                    client,
                    args,
                    spec,
                    spec.build_vllm_prompt(hidden_document),
                )
                write_json_atomic(
                    sample.output_path,
                    build_vllm_result_document(answer_document, result, args),
                    args.indent,
                )
                if result.success:
                    succeeded += 1
                else:
                    failed += 1
                    errors.append(
                        {
                            "split": sample.split,
                            "source_file": str(sample.relative_path),
                            "output_file": str(sample.output_path),
                            "error_stage": result.error_stage,
                            "error": result.error,
                        }
                    )
            except Exception as error:  # noqa: BLE001 - 单样本失败不能中断批次。
                failed += 1
                error_text = f"{type(error).__name__}: {error}"
                errors.append(
                    {
                        "split": sample.split,
                        "source_file": str(sample.relative_path),
                        "output_file": str(sample.output_path),
                        "error_stage": "sample_processing",
                        "error": error_text,
                    }
                )
                try:
                    answer_document = load_json_object(sample.answer_path)
                    failed_result = InferenceResult(
                        success=False,
                        answer=None,
                        error_stage="sample_processing",
                        error=error_text,
                        raw_output="",
                        attempts=0,
                        duration_seconds=0.0,
                    )
                    write_json_atomic(
                        sample.output_path,
                        build_vllm_result_document(
                            answer_document,
                            failed_result,
                            args,
                        ),
                        args.indent,
                    )
                except Exception:
                    pass

        print_progress(
            args,
            index,
            len(samples),
            succeeded,
            failed,
            skipped,
            started_at,
        )
        if args.wait_seconds > 0:
            time.sleep(args.wait_seconds)

    summary = build_summary(
        spec,
        args,
        samples,
        succeeded,
        failed,
        skipped,
        started_at,
        backend="vllm",
    )
    write_json_atomic(output_root / "batch_summary.json", summary, args.indent)
    write_error_csv(output_root / "batch_errors.csv", errors)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def decode_json_stream(raw_output: str) -> list[Any]:
    decoder = json.JSONDecoder()
    events: list[Any] = []
    position = 0
    while position < len(raw_output):
        while position < len(raw_output) and raw_output[position].isspace():
            position += 1
        if position >= len(raw_output):
            break
        try:
            event, end = decoder.raw_decode(raw_output, position)
        except json.JSONDecodeError:
            next_line = raw_output.find("\n", position)
            if next_line < 0:
                break
            position = next_line + 1
            continue
        events.append(event)
        position = end
    return events


def extract_opencode_answer(
    stdout: str,
    validate_answer: AnswerValidator,
) -> tuple[dict[str, Any], str | None]:
    events = decode_json_stream(stdout)
    session_id: str | None = None
    text_parts: list[str] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        event_session_id = event.get("sessionID") or event.get("session_id")
        if isinstance(event_session_id, str):
            session_id = event_session_id
        part = event.get("part")
        if isinstance(part, dict) and isinstance(part.get("text"), str):
            text_parts.append(part["text"])
        for field_name in ("output", "content", "text"):
            value = event.get(field_name)
            if isinstance(value, str):
                text_parts.append(value)

    candidates = list(reversed(text_parts))
    if text_parts:
        candidates.extend(("".join(text_parts), "\n".join(text_parts)))
    candidates.append(stdout)
    errors: list[str] = []
    for candidate in candidates:
        try:
            return parse_answer_text(candidate, validate_answer), session_id
        except ValueError as error:
            errors.append(str(error))
    detail = errors[0] if errors else "没有找到 assistant 文本事件"
    raise ValueError(f"无法提取有效的 OpenCode 回答: {detail}")


def build_opencode_command(
    args: argparse.Namespace,
    prompt: str,
) -> list[str]:
    command = [args.opencode_command, "run"]
    if args.attach:
        command.extend(["--attach", args.attach])
    if args.model:
        command.extend(["--model", args.model])
    if args.agent:
        command.extend(["--agent", args.agent])
    command.extend(
        [
            "--dir",
            str(args.opencode_workdir.resolve()),
            "--format",
            "json",
            prompt,
        ]
    )
    return command


def subprocess_output_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def invoke_opencode(
    args: argparse.Namespace,
    spec: TaskInferenceSpec,
    prompt: str,
) -> InferenceResult:
    total_attempts = args.retries + 1
    started_at = time.monotonic()
    last_error = "unknown-opencode-error"
    last_stage = "request"
    last_stdout = ""
    last_stderr = ""
    last_return_code: int | None = None
    last_session_id: str | None = None
    attempts_used = 0
    for attempt in range(1, total_attempts + 1):
        attempts_used = attempt
        last_stage = "request"
        try:
            completed = subprocess.run(
                build_opencode_command(args, prompt),
                cwd=args.opencode_workdir,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=args.timeout_seconds,
                check=False,
            )
            last_stdout = subprocess_output_text(completed.stdout)
            last_stderr = subprocess_output_text(completed.stderr)
            last_return_code = completed.returncode
            if completed.returncode != 0:
                last_error = (
                    f"opencode-exit-{completed.returncode}: "
                    f"{last_stderr.strip() or '没有 stderr'}"
                )
                continue
            try:
                answer, last_session_id = extract_opencode_answer(
                    last_stdout,
                    spec.validate_answer,
                )
            except ValueError as error:
                last_stage = "model_output_parse"
                last_error = f"opencode-answer-parse-error: {error}"
                continue
            return InferenceResult(
                success=True,
                answer=answer,
                error_stage=None,
                error=None,
                raw_output=last_stdout,
                attempts=attempt,
                duration_seconds=time.monotonic() - started_at,
                raw_error_output=last_stderr,
                return_code=completed.returncode,
                session_id=last_session_id,
            )
        except subprocess.TimeoutExpired as error:
            last_stdout = subprocess_output_text(error.stdout)
            last_stderr = subprocess_output_text(error.stderr)
            last_error = (
                f"opencode-timeout-after-{args.timeout_seconds:g}-seconds"
            )
        except FileNotFoundError:
            last_error = f"opencode-command-not-found: {args.opencode_command}"
            break
        except OSError as error:
            last_error = f"opencode-start-error: {error}"
            break

    return InferenceResult(
        success=False,
        answer=None,
        error_stage=last_stage,
        error=last_error,
        raw_output=last_stdout,
        attempts=attempts_used,
        duration_seconds=time.monotonic() - started_at,
        raw_error_output=last_stderr,
        return_code=last_return_code,
        session_id=last_session_id,
    )


def source_site_name(
    hidden_document: dict[str, Any],
    relative_path: Path,
) -> str:
    metadata = hidden_document.get("task_metadata")
    if isinstance(metadata, dict):
        source_file = metadata.get("source_file")
        if isinstance(source_file, str) and source_file.strip():
            return Path(source_file.replace("\\", "/")).name
    return relative_path.name


def write_raw_outputs(
    output_root: Path,
    sample: SamplePaths,
    stdout: str,
    stderr: str,
) -> tuple[str, str]:
    raw_base = output_root / "_raw" / sample.split / sample.relative_path
    stdout_path = raw_base.with_suffix(raw_base.suffix + ".stdout.txt")
    stderr_path = raw_base.with_suffix(raw_base.suffix + ".stderr.txt")
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stdout_path.write_text(stdout, encoding="utf-8")
    stderr_path.write_text(stderr, encoding="utf-8")
    return str(stdout_path), str(stderr_path)


def build_opencode_result_document(
    answer_document: dict[str, Any],
    result: InferenceResult,
    args: argparse.Namespace,
    stdout_path: str,
    stderr_path: str,
) -> dict[str, Any]:
    output = dict(answer_document)
    output["model-output"] = result.answer
    output["opencode-run"] = {
        "success": result.success,
        "error_stage": result.error_stage,
        "error": result.error,
        "model": args.model,
        "agent": args.agent,
        "session_id": result.session_id,
        "return_code": result.return_code,
        "attempts": result.attempts,
        "duration_seconds": round(result.duration_seconds, 6),
        "stdout_file": stdout_path,
        "stderr_file": stderr_path,
    }
    return output


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(row, ensure_ascii=False) + "\n")


def run_opencode(
    args: argparse.Namespace,
    spec: TaskInferenceSpec,
) -> dict[str, Any]:
    hidden_root = args.hidden_root.resolve()
    answer_root = args.answer_root.resolve()
    output_root = args.output_root.resolve()
    samples = collect_samples(
        hidden_root,
        answer_root,
        output_root,
        args.split,
    )
    if args.limit is not None:
        samples = samples[: args.limit]
    if not samples:
        raise FileNotFoundError("没有找到需要推理的 without_answer JSON")

    pending = [
        sample
        for sample in samples
        if not (
            args.resume
            and has_successful_result(sample.output_path, "opencode-run")
        )
    ]
    if not args.dry_run and pending:
        executable = shutil.which(args.opencode_command)
        if executable is None and not Path(args.opencode_command).is_file():
            raise FileNotFoundError(
                f"找不到 OpenCode 命令: {args.opencode_command}"
            )
        args.opencode_workdir.mkdir(parents=True, exist_ok=True)
        output_root.mkdir(parents=True, exist_ok=True)

    error_path = output_root / "batch_errors.jsonl"
    if not args.dry_run and error_path.exists():
        error_path.unlink()
    succeeded = 0
    failed = 0
    skipped = 0
    started_at = time.monotonic()

    for index, sample in enumerate(samples, start=1):
        if args.resume and has_successful_result(
            sample.output_path,
            "opencode-run",
        ):
            skipped += 1
        else:
            try:
                hidden_document = load_json_object(sample.hidden_path)
                if "task_answer" in hidden_document:
                    raise ValueError("without_answer 文件不应包含 task_answer")
                site = source_site_name(hidden_document, sample.relative_path)
                prompt = spec.build_opencode_prompt(site, hidden_document)
                if args.dry_run:
                    print(
                        f"\n===== {sample.split}/{sample.relative_path} =====\n"
                        f"{prompt}\n"
                    )
                else:
                    result = invoke_opencode(args, spec, prompt)
                    answer_document = load_json_object(sample.answer_path)
                    stdout_path, stderr_path = write_raw_outputs(
                        output_root,
                        sample,
                        result.raw_output,
                        result.raw_error_output,
                    )
                    write_json_atomic(
                        sample.output_path,
                        build_opencode_result_document(
                            answer_document,
                            result,
                            args,
                            stdout_path,
                            stderr_path,
                        ),
                        args.indent,
                    )
                    if result.success:
                        succeeded += 1
                    else:
                        failed += 1
                        append_jsonl(
                            error_path,
                            {
                                "split": sample.split,
                                "source_file": str(sample.relative_path),
                                "output_file": str(sample.output_path),
                                "error_stage": result.error_stage,
                                "error": result.error,
                            },
                        )
            except Exception as error:  # noqa: BLE001 - 单样本失败不能中断批次。
                failed += 1
                if not args.dry_run:
                    append_jsonl(
                        error_path,
                        {
                            "split": sample.split,
                            "source_file": str(sample.relative_path),
                            "output_file": str(sample.output_path),
                            "error_stage": "sample_processing",
                            "error": f"{type(error).__name__}: {error}",
                        },
                    )
                print(
                    f"[error] {sample.split}/{sample.relative_path}: {error}",
                    flush=True,
                )

        print_progress(
            args,
            index,
            len(samples),
            succeeded,
            failed,
            skipped,
            started_at,
        )

    summary = build_summary(
        spec,
        args,
        samples,
        succeeded,
        failed,
        skipped,
        started_at,
        backend="opencode",
    )
    summary["dry_run"] = args.dry_run
    if not args.dry_run:
        write_json_atomic(output_root / "batch_summary.json", summary, args.indent)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def print_progress(
    args: argparse.Namespace,
    index: int,
    total: int,
    succeeded: int,
    failed: int,
    skipped: int,
    started_at: float,
) -> None:
    if args.progress_interval <= 0 or (
        index % args.progress_interval != 0 and index != total
    ):
        return
    elapsed = max(time.monotonic() - started_at, 0.001)
    speed = index / elapsed
    eta = (total - index) / speed if speed else 0.0
    print(
        f"进度 {index}/{total}，成功 {succeeded}，失败 {failed}，"
        f"跳过 {skipped}，预计剩余 {eta:.1f} 秒",
        flush=True,
    )


def build_summary(
    spec: TaskInferenceSpec,
    args: argparse.Namespace,
    samples: list[SamplePaths],
    succeeded: int,
    failed: int,
    skipped: int,
    started_at: float,
    *,
    backend: str,
) -> dict[str, Any]:
    return {
        "task": spec.task_name,
        "backend": backend,
        "hidden_root": str(args.hidden_root.resolve()),
        "answer_root": str(args.answer_root.resolve()),
        "output_root": str(args.output_root.resolve()),
        "split": args.split,
        "total_files": len(samples),
        "succeeded": succeeded,
        "failed": failed,
        "skipped": skipped,
        "resume": args.resume,
        "model": args.model,
        "elapsed_seconds": round(time.monotonic() - started_at, 3),
    }


def validate_path_answer(answer: dict[str, Any]) -> None:
    path_length = answer.get("path_length")
    paths = answer.get("paths")
    if isinstance(path_length, bool) or not isinstance(path_length, int):
        raise ValueError("path_length 必须是整数")
    if path_length < 0:
        raise ValueError("path_length 不能小于 0")
    if not isinstance(paths, list) or not paths:
        raise ValueError("paths 必须是非空数组")
    for index, path in enumerate(paths):
        if (
            not isinstance(path, list)
            or not path
            or not all(isinstance(node_id, str) and node_id for node_id in path)
        ):
            raise ValueError(f"paths[{index}] 必须是非空节点 ID 数组")
        if len(path) - 1 != path_length:
            raise ValueError(f"paths[{index}] 与 path_length 不一致")


def validate_link_failure_answer(answer: dict[str, Any]) -> None:
    connected = answer.get("connected")
    path_length = answer.get("path_length")
    paths = answer.get("paths")
    if not isinstance(connected, bool):
        raise ValueError("connected 必须是布尔值")
    if connected:
        validate_path_answer(answer)
        return
    if path_length is not None:
        raise ValueError("connected=false 时 path_length 必须是 null")
    if paths != []:
        raise ValueError("connected=false 时 paths 必须是空数组")


def validate_ap_impact_answer(answer: dict[str, Any]) -> None:
    ap_ids = answer.get("disconnected_ap_ids")
    if not isinstance(ap_ids, list):
        raise ValueError("disconnected_ap_ids 必须是数组")
    if not all(isinstance(ap_id, str) and ap_id for ap_id in ap_ids):
        raise ValueError("disconnected_ap_ids 中的元素必须是非空字符串")


def validate_link_port_answer(answer: dict[str, Any]) -> None:
    left_port = answer.get("LEFTPORT")
    right_port = answer.get("RIGHTPORT")
    if not isinstance(left_port, str) or not left_port.strip():
        raise ValueError("LEFTPORT 必须是非空字符串")
    if not isinstance(right_port, str) or not right_port.strip():
        raise ValueError("RIGHTPORT 必须是非空字符串")
