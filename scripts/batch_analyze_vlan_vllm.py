#!/usr/bin/env python3
"""使用 OpenAI-compatible vLLM 服务逐文件分析原始拓扑中的 VLAN 情况。"""

from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path
from typing import Any


DEFAULT_DATASET_ROOT = Path("datasets")
DEFAULT_OUTPUT_ROOT = Path("vlan-llm-analysis")
DEFAULT_BASE_URL = "http://localhost:8000/v1"
DEFAULT_API_KEY = "empty"
DEFAULT_MODEL = "qwen3-8b"
DEFAULT_SPLIT = "all"
DEFAULT_TEMPERATURE = 0.2
DEFAULT_REQUEST_TIMEOUT = 600.0
DEFAULT_RETRIES = 1
DEFAULT_RETRY_WAIT_SECONDS = 5.0
DEFAULT_WAIT_SECONDS = 0.0
DEFAULT_PROGRESS_INTERVAL = 1

SUMMARY_FILE = "vlan_llm_analysis_summary.json"
FAILURE_FILE = "vlan_llm_analysis_failures.csv"

SYSTEM_PROMPT = """你是一名网络拓扑与网络配置分析专家。请严格依据用户提供的完整网络拓扑，使用中文说明你对其中 VLAN 情况的理解，不得补充输入中不存在的设备、VLAN、接口或连接关系。不要输出思考过程。"""

USER_PROMPT_TEMPLATE = """请分析下面完整网络拓扑 JSON 中的 VLAN 情况。

请直接回复你对这个网络拓扑中 VLAN 的理解，不需要返回 JSON 或其他固定数据结构。重点说明拓扑中有哪些 VLAN 相关配置、这些配置涉及哪些节点或设备组、可能表达什么网络关系，以及有哪些值得注意或无法确定的地方。

请使用简洁的中文标题和分点描述组织回复，使结果便于人工阅读。不要输出输入中没有依据的结论，也不要仅凭相同 VLAN ID 推断业务一定连通。

【完整网络拓扑 JSON】
{topology_json}
"""


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
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="逐文件分析结果根目录，默认: %(default)s",
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
        "--temperature",
        type=float,
        default=DEFAULT_TEMPERATURE,
        help="模型采样温度，默认: %(default)s",
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
        help="请求重试前等待秒数，默认: %(default)s",
    )
    parser.add_argument(
        "--wait-seconds",
        type=float,
        default=DEFAULT_WAIT_SECONDS,
        help="每个样本请求完成后等待秒数，默认: %(default)s",
    )
    parser.add_argument(
        "--progress-interval",
        type=int,
        default=DEFAULT_PROGRESS_INTERVAL,
        help="每处理 N 个文件打印进度，0 表示关闭，默认: %(default)s",
    )
    parser.add_argument(
        "--enable-thinking",
        action="store_true",
        help="开启模型思考模式；默认通过 chat_template_kwargs 关闭",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="结果文件已存在时跳过；默认固定覆盖",
    )
    args = parser.parse_args()

    if args.temperature < 0:
        parser.error("--temperature 不能小于 0")
    if args.request_timeout <= 0:
        parser.error("--request-timeout 必须大于 0")
    if args.retries < 0:
        parser.error("--retries 不能小于 0")
    if args.retry_wait_seconds < 0:
        parser.error("--retry-wait-seconds 不能小于 0")
    if args.wait_seconds < 0:
        parser.error("--wait-seconds 不能小于 0")
    if args.progress_interval < 0:
        parser.error("--progress-interval 不能小于 0")
    return args


def import_openai() -> Any:
    try:
        from openai import OpenAI
    except ImportError as error:
        raise RuntimeError(
            "缺少 openai 依赖，请先执行: pip install openai"
        ) from error
    return OpenAI


def iter_json_files(dataset_root: Path, split: str) -> list[Path]:
    split_dir = dataset_root / split
    if not split_dir.is_dir():
        raise FileNotFoundError(f"数据划分目录不存在: {split_dir}")
    return sorted(path for path in split_dir.rglob("*.json") if path.is_file())


def format_model_output(content: str) -> list[str]:
    """按非空行保存自然语言回复，避免 JSON 字符串中出现大量转义换行。"""

    return [line.rstrip() for line in content.strip().splitlines() if line.strip()]


def build_user_prompt(graph: dict[str, Any]) -> str:
    # 紧凑序列化只去掉无意义空白，不删除或截断任何拓扑字段。
    topology_json = json.dumps(
        graph,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return USER_PROMPT_TEMPLATE.format(topology_json=topology_json)


def request_analysis(
    client: Any,
    args: argparse.Namespace,
    user_prompt: str,
) -> tuple[str, int]:
    last_error: Exception | None = None
    total_attempts = args.retries + 1
    for attempt in range(1, total_attempts + 1):
        try:
            response = client.chat.completions.create(
                model=args.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
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
            return content, attempt
        except Exception as error:  # noqa: BLE001 - API 异常需要重试并落盘。
            last_error = error
            if attempt < total_attempts and args.retry_wait_seconds > 0:
                time.sleep(args.retry_wait_seconds)

    assert last_error is not None
    raise RuntimeError(
        f"请求在 {total_attempts} 次尝试后仍失败: "
        f"{type(last_error).__name__}: {last_error}"
    ) from last_error


def write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)


def make_error_result(
    split: str,
    source_file: str,
    model: str,
    stage: str,
    error: Exception,
    elapsed_seconds: float,
    raw_model_output: str | None = None,
    request_attempts: int = 0,
) -> dict[str, Any]:
    return {
        "source_file": source_file,
        "split": split,
        "status": False,
        "model": model,
        "request_attempts": request_attempts,
        "elapsed_seconds": round(elapsed_seconds, 3),
        "model-output": (
            format_model_output(raw_model_output)
            if raw_model_output is not None
            else None
        ),
        "error_stage": stage,
        "error": f"{type(error).__name__}: {error}",
    }


def process_file(
    client: Any,
    args: argparse.Namespace,
    dataset_root: Path,
    output_root: Path,
    split: str,
    source_path: Path,
) -> dict[str, Any]:
    source_file = str(source_path.relative_to(dataset_root / split))
    output_path = output_root / split / source_file
    started_at = time.time()

    if args.skip_existing and output_path.is_file():
        return {
            "source_file": source_file,
            "split": split,
            "status": None,
            "skipped": True,
            "output_path": str(output_path),
        }

    try:
        graph = json.loads(source_path.read_text(encoding="utf-8"))
        if not isinstance(graph, dict):
            raise ValueError(
                f"输入顶层类型为 {type(graph).__name__}，预期为 object"
            )
        user_prompt = build_user_prompt(graph)
    except Exception as error:  # noqa: BLE001 - 单个坏文件不能中断批处理。
        result = make_error_result(
            split,
            source_file,
            args.model,
            "input",
            error,
            time.time() - started_at,
        )
        write_json_atomic(output_path, result)
        return {**result, "output_path": str(output_path)}

    try:
        raw_output, attempts = request_analysis(client, args, user_prompt)
    except Exception as error:  # noqa: BLE001 - API 失败必须写入对应结果。
        result = make_error_result(
            split,
            source_file,
            args.model,
            "request",
            error,
            time.time() - started_at,
            request_attempts=args.retries + 1,
        )
        write_json_atomic(output_path, result)
        return {**result, "output_path": str(output_path)}

    result = {
        "source_file": source_file,
        "split": split,
        "status": True,
        "model": args.model,
        "request_attempts": attempts,
        "elapsed_seconds": round(time.time() - started_at, 3),
        "model-output": format_model_output(raw_output),
        "error_stage": None,
        "error": None,
    }
    write_json_atomic(output_path, result)
    return {**result, "output_path": str(output_path)}


def write_failures(path: Path, failures: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        fieldnames = ["split", "source_file", "error_stage", "error", "output_path"]
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for failure in failures:
            writer.writerow({key: failure.get(key) for key in fieldnames})


def run(args: argparse.Namespace) -> None:
    dataset_root = args.dataset_root.resolve()
    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    splits = ["train", "val"] if args.split == "all" else [args.split]
    split_files = {split: iter_json_files(dataset_root, split) for split in splits}
    total_files = sum(len(files) for files in split_files.values())
    if total_files == 0:
        raise FileNotFoundError(f"未找到输入 JSON: {dataset_root}")

    OpenAI = import_openai()
    client = OpenAI(
        base_url=args.base_url,
        api_key=args.api_key,
        timeout=args.request_timeout,
    )

    completed = 0
    succeeded = 0
    failed = 0
    skipped = 0
    failures: list[dict[str, Any]] = []
    by_split: dict[str, dict[str, int]] = {}
    started_at = time.time()

    for split in splits:
        files = split_files[split]
        split_success = 0
        split_failed = 0
        split_skipped = 0
        print(f"[{split}] 开始分析：{len(files)} 个文件", flush=True)
        for source_path in files:
            result = process_file(
                client,
                args,
                dataset_root,
                output_root,
                split,
                source_path,
            )
            completed += 1
            if result.get("skipped"):
                skipped += 1
                split_skipped += 1
            elif result["status"]:
                succeeded += 1
                split_success += 1
            else:
                failed += 1
                split_failed += 1
                failures.append(result)

            if args.progress_interval > 0 and (
                completed % args.progress_interval == 0 or completed == total_files
            ):
                elapsed = max(time.time() - started_at, 0.001)
                speed = completed / elapsed
                eta = (total_files - completed) / speed if speed else 0.0
                print(
                    f"[总进度] {completed}/{total_files}，成功 {succeeded}，"
                    f"失败 {failed}，跳过 {skipped}，预计剩余 {eta:.1f} 秒",
                    flush=True,
                )

            if args.wait_seconds > 0:
                time.sleep(args.wait_seconds)

        by_split[split] = {
            "input_files": len(files),
            "succeeded_files": split_success,
            "failed_files": split_failed,
            "skipped_files": split_skipped,
        }

    elapsed_seconds = time.time() - started_at
    summary = {
        "dataset_root": str(dataset_root),
        "output_root": str(output_root),
        "base_url": args.base_url,
        "model": args.model,
        "splits": splits,
        "context_mode": "full_json_without_truncation",
        "response_format": "Chinese natural-language lines",
        "thinking_enabled": args.enable_thinking,
        "input_files": total_files,
        "succeeded_files": succeeded,
        "failed_files": failed,
        "skipped_files": skipped,
        "elapsed_seconds": round(elapsed_seconds, 3),
        "average_seconds_per_processed_file": round(
            elapsed_seconds / max(1, succeeded + failed),
            3,
        ),
        "by_split": by_split,
    }
    write_json_atomic(output_root / SUMMARY_FILE, summary)
    write_failures(output_root / FAILURE_FILE, failures)

    print(
        f"完成：成功 {succeeded}，失败 {failed}，跳过 {skipped}；"
        f"结果目录：{output_root}",
        flush=True,
    )


if __name__ == "__main__":
    run(parse_args())
