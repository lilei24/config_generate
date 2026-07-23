#!/usr/bin/env python3
"""从站点列表批量调用 OpenCode，完成两节点全部最短路径任务。

站点列表是 UTF-8 文本文件，每行一个站点名称。空行和以 ``#`` 开头的行会被
忽略。站点名称可以写成以下任一形式：

- site_a
- site_a.json
- 子目录/site_a
- 子目录/site_a.json

脚本从 shortest_path_dataset/without_answer/{split} 中找到对应任务样本，提取
源节点 ID 和目标节点 ID 并构造提示词。OpenCode 的回答不会写回标准答案目录，
而是复制对应的 with_answer 样本，再在输出文件中增加 ``model-output`` 和
``opencode-run`` 字段，方便后续与 ``task_answer`` 对照评估。

OpenCode 使用 ``--format json`` 时返回的是 JSON 事件流。脚本会保留原始事件，
提取最后一个可解析的 assistant JSON，并校验最短路径回答的基本结构。
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_SITE_FILE = Path("sites.txt")
DEFAULT_HIDDEN_ROOT = Path("shortest_path_dataset/without_answer")
DEFAULT_ANSWER_ROOT = Path("shortest_path_dataset/with_answer")
DEFAULT_OUTPUT_ROOT = Path("opencode-results/shortest_path")
DEFAULT_WORKDIR = Path("opencode-harness-workspace")
DEFAULT_SPLIT = "val"
DEFAULT_TIMEOUT_SECONDS = 600.0
DEFAULT_RETRIES = 1
DEFAULT_PROGRESS_INTERVAL = 1


@dataclass(frozen=True)
class SamplePaths:
    relative_path: Path
    hidden_path: Path
    answer_path: Path
    output_path: Path


@dataclass
class OpenCodeResult:
    success: bool
    answer: dict[str, Any] | None
    error: str | None
    return_code: int | None
    duration_seconds: float
    attempts: int
    session_id: str | None
    stdout: str
    stderr: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--site-file",
        type=Path,
        default=DEFAULT_SITE_FILE,
        help=f"站点名称文本文件，默认: {DEFAULT_SITE_FILE}",
    )
    parser.add_argument(
        "--hidden-root",
        type=Path,
        default=DEFAULT_HIDDEN_ROOT,
        help=f"隐藏答案数据集根目录，默认: {DEFAULT_HIDDEN_ROOT}",
    )
    parser.add_argument(
        "--answer-root",
        type=Path,
        default=DEFAULT_ANSWER_ROOT,
        help=f"标准答案数据集根目录，默认: {DEFAULT_ANSWER_ROOT}",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help=f"推理结果根目录，默认: {DEFAULT_OUTPUT_ROOT}",
    )
    parser.add_argument(
        "--split",
        default=DEFAULT_SPLIT,
        help=f"数据划分，默认: {DEFAULT_SPLIT}",
    )
    parser.add_argument(
        "--opencode-command",
        default="opencode",
        help="OpenCode 可执行文件名称或路径，默认: opencode",
    )
    parser.add_argument(
        "--attach",
        default=None,
        help="可选的 OpenCode serve 地址，例如 http://localhost:4096",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="可选模型，格式为 provider/model；省略时使用 OpenCode 默认模型",
    )
    parser.add_argument(
        "--agent",
        default=None,
        help="可选的 OpenCode Agent 名称；省略时使用 OpenCode 当前默认 Agent",
    )
    parser.add_argument(
        "--opencode-workdir",
        type=Path,
        default=DEFAULT_WORKDIR,
        help=f"隔离的 OpenCode 工作目录，默认: {DEFAULT_WORKDIR}",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"每次调用超时时间，默认: {DEFAULT_TIMEOUT_SECONDS:g} 秒",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=DEFAULT_RETRIES,
        help=f"失败后的重试次数，默认: {DEFAULT_RETRIES}",
    )
    parser.add_argument(
        "--progress-interval",
        type=int,
        default=DEFAULT_PROGRESS_INTERVAL,
        help=f"每处理多少个站点打印进度，默认: {DEFAULT_PROGRESS_INTERVAL}",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="只处理前 N 个站点，适合小规模联调",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只检查站点匹配并打印提示词，不调用 OpenCode、不写结果",
    )
    parser.add_argument(
        "--indent",
        type=int,
        default=2,
        help="输出 JSON 缩进，默认: 2",
    )
    return parser.parse_args()


def load_json_object(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"JSON 顶层必须是对象，实际为 {type(data).__name__}")
    return data


def write_json(path: Path, data: dict[str, Any], indent: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=indent) + "\n",
        encoding="utf-8",
    )


def read_site_names(path: Path) -> list[str]:
    if not path.is_file():
        raise FileNotFoundError(f"站点列表文件不存在: {path}")

    sites: list[str] = []
    seen: set[str] = set()
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        site = raw_line.strip()
        if not site or site.startswith("#"):
            continue
        if site in seen:
            print(f"[warning] 第 {line_number} 行站点重复，已忽略: {site}")
            continue
        seen.add(site)
        sites.append(site)
    return sites


def site_aliases(relative_path: Path) -> set[str]:
    """为一个样本建立文件名、stem 和相对路径形式的查询别名。"""

    relative_posix = relative_path.as_posix()
    without_suffix = relative_path.with_suffix("").as_posix()
    return {
        relative_posix,
        without_suffix,
        relative_path.name,
        relative_path.stem,
    }


def build_site_index(split_root: Path) -> tuple[dict[str, Path], set[str]]:
    """建立站点别名索引；有歧义的短名称不会被自动匹配。"""

    candidates: dict[str, list[Path]] = {}
    for json_path in sorted(split_root.rglob("*.json")):
        if not json_path.is_file():
            continue
        relative_path = json_path.relative_to(split_root)
        for alias in site_aliases(relative_path):
            candidates.setdefault(alias, []).append(relative_path)

    index: dict[str, Path] = {}
    ambiguous: set[str] = set()
    for alias, paths in candidates.items():
        unique_paths = sorted(set(paths))
        if len(unique_paths) == 1:
            index[alias] = unique_paths[0]
        else:
            ambiguous.add(alias)
    return index, ambiguous


def resolve_sample_paths(
    site: str,
    index: dict[str, Path],
    ambiguous: set[str],
    hidden_split_root: Path,
    answer_split_root: Path,
    output_split_root: Path,
) -> SamplePaths:
    normalized_site = Path(site).as_posix()
    if normalized_site in ambiguous:
        raise ValueError(
            f"站点名称存在多个同名文件，请在 txt 中填写相对路径: {site}"
        )
    relative_path = index.get(normalized_site)
    if relative_path is None:
        raise FileNotFoundError(f"隐藏答案数据集中找不到站点: {site}")

    answer_path = answer_split_root / relative_path
    if not answer_path.is_file():
        raise FileNotFoundError(f"找不到对应标准答案文件: {answer_path}")
    return SamplePaths(
        relative_path=relative_path,
        hidden_path=hidden_split_root / relative_path,
        answer_path=answer_path,
        output_path=output_split_root / relative_path,
    )


def build_prompt(site: str, sample: dict[str, Any]) -> str:
    source_node = sample.get("task_source_node_id")
    target_node = sample.get("task_target_node_id")
    if not isinstance(source_node, str) or not source_node:
        raise ValueError("样本缺少有效的 task_source_node_id")
    if not isinstance(target_node, str) or not target_node:
        raise ValueError("样本缺少有效的 task_target_node_id")

    return f"""你是网络物理拓扑分析 Agent。

你必须根据站点名称调用拓扑数据 Provider 获取拓扑，并使用
topograph_understand 提供的路径计算能力完成任务。不得根据节点 ID 或设备名称猜测答案。

站点名称：{site}
任务：查找节点 ID {source_node} 到节点 ID {target_node} 的全部最短物理路径。

要求：
1. paths 使用节点 ID，且必须与工具返回结果完全一致。
2. path_length 表示链路跳数，即路径节点数减一。
3. 如果存在多条等长最短路径，必须全部输出。
4. paths 中每条路径按照从源节点到目标节点的顺序排列。
5. path_role_sequences 与 paths 一一对应，填写每个节点的 topologyNode.DEVICEROLE。
6. path_device_names 与 paths 一一对应，填写每个节点的 devices.NAME 或 device.NAME。
7. 最终只输出一个 JSON 对象，不输出解释、Markdown 代码块或思考过程。

输出格式示例：
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
}}"""


def decode_json_stream(raw_output: str) -> list[Any]:
    """解析由多个 JSON 值组成的 OpenCode stdout，兼容单行和格式化事件。"""

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
            # 某些版本可能在 stdout 中混入普通日志。跳到下一行继续尝试解析。
            next_line = raw_output.find("\n", position)
            if next_line < 0:
                break
            position = next_line + 1
            continue
        events.append(event)
        position = end
    return events


def strip_markdown_code_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def parse_json_object_from_text(text: str) -> dict[str, Any]:
    cleaned = strip_markdown_code_fence(text)
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        object_start = cleaned.find("{")
        if object_start < 0:
            raise ValueError("模型回答中没有 JSON 对象") from None
        try:
            value, _ = json.JSONDecoder().raw_decode(cleaned, object_start)
        except json.JSONDecodeError as exc:
            raise ValueError(f"模型回答 JSON 解析失败: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"模型回答必须是 JSON 对象，实际为 {type(value).__name__}")
    return value


def validate_shortest_path_answer(answer: dict[str, Any]) -> None:
    path_length = answer.get("path_length")
    paths = answer.get("paths")
    role_sequences = answer.get("path_role_sequences")
    device_name_sequences = answer.get("path_device_names")
    if isinstance(path_length, bool) or not isinstance(path_length, int):
        raise ValueError("model answer.path_length 必须是整数")
    if path_length < 0:
        raise ValueError("model answer.path_length 不能小于 0")
    if not isinstance(paths, list) or not paths:
        raise ValueError("model answer.paths 必须是非空数组")
    for path_index, path in enumerate(paths):
        if not isinstance(path, list) or not path:
            raise ValueError(f"model answer.paths[{path_index}] 必须是非空数组")
        if not all(isinstance(node_name, str) and node_name for node_name in path):
            raise ValueError(
                f"model answer.paths[{path_index}] 中的节点名称必须是非空字符串"
            )
        if len(path) - 1 != path_length:
            raise ValueError(
                f"model answer.paths[{path_index}] 的节点数与 path_length 不一致"
            )
    validate_path_metadata_sequences(
        "path_role_sequences",
        role_sequences,
        paths,
    )
    validate_path_metadata_sequences(
        "path_device_names",
        device_name_sequences,
        paths,
    )


def validate_path_metadata_sequences(
    field_name: str,
    sequences: Any,
    paths: list[Any],
) -> None:
    if not isinstance(sequences, list) or len(sequences) != len(paths):
        raise ValueError(f"model answer.{field_name} 必须与 paths 一一对应")
    for path_index, (sequence, path) in enumerate(zip(sequences, paths)):
        if not isinstance(sequence, list) or len(sequence) != len(path):
            raise ValueError(
                f"model answer.{field_name}[{path_index}] 必须与对应路径等长"
            )
        if not all(isinstance(value, str) for value in sequence):
            raise ValueError(
                f"model answer.{field_name}[{path_index}] 的元素必须是字符串"
            )


def extract_answer_and_session(stdout: str) -> tuple[dict[str, Any], str | None]:
    events = decode_json_stream(stdout)
    session_id: str | None = None
    text_candidates: list[str] = []

    for event in events:
        if not isinstance(event, dict):
            continue
        event_session_id = event.get("sessionID") or event.get("session_id")
        if isinstance(event_session_id, str):
            session_id = event_session_id

        if event.get("type") == "text":
            part = event.get("part")
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                text_candidates.append(part["text"])
        # 兼容返回单个包装对象而不是事件流的 OpenCode 版本。
        for field_name in ("output", "content", "text"):
            field_value = event.get(field_name)
            if isinstance(field_value, str):
                text_candidates.append(field_value)

    # 优先解析最后一个文本事件，因为它通常是工具调用完成后的最终回答。
    parse_errors: list[str] = []
    for candidate in reversed(text_candidates):
        try:
            answer = parse_json_object_from_text(candidate)
            validate_shortest_path_answer(answer)
            return answer, session_id
        except ValueError as exc:
            parse_errors.append(str(exc))

    # 如果 stdout 本身就是模型 JSON，也允许直接解析。
    try:
        answer = parse_json_object_from_text(stdout)
        validate_shortest_path_answer(answer)
        return answer, session_id
    except ValueError as exc:
        parse_errors.append(str(exc))

    detail = parse_errors[0] if parse_errors else "没有找到 assistant 文本事件"
    raise ValueError(f"无法提取有效的 OpenCode 回答: {detail}")


def build_opencode_command(args: argparse.Namespace, prompt: str) -> list[str]:
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


def invoke_opencode(args: argparse.Namespace, prompt: str) -> OpenCodeResult:
    total_attempts = max(1, args.retries + 1)
    started_at = time.monotonic()
    last_error: str | None = None
    last_stdout = ""
    last_stderr = ""
    last_return_code: int | None = None
    last_session_id: str | None = None
    attempts_used = 0

    for attempt in range(1, total_attempts + 1):
        attempts_used = attempt
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
            last_stdout = completed.stdout
            last_stderr = completed.stderr
            last_return_code = completed.returncode
            if completed.returncode != 0:
                last_error = (
                    f"opencode-exit-{completed.returncode}: "
                    f"{completed.stderr.strip() or '没有 stderr'}"
                )
                continue

            try:
                answer, last_session_id = extract_answer_and_session(completed.stdout)
            except ValueError as exc:
                last_error = f"opencode-answer-parse-error: {exc}"
                continue

            return OpenCodeResult(
                success=True,
                answer=answer,
                error=None,
                return_code=completed.returncode,
                duration_seconds=time.monotonic() - started_at,
                attempts=attempt,
                session_id=last_session_id,
                stdout=last_stdout,
                stderr=last_stderr,
            )
        except subprocess.TimeoutExpired as exc:
            last_stdout = exc.stdout or ""
            last_stderr = exc.stderr or ""
            last_error = f"opencode-timeout-after-{args.timeout_seconds:g}-seconds"
        except FileNotFoundError:
            last_error = f"opencode-command-not-found: {args.opencode_command}"
            break
        except OSError as exc:
            last_error = f"opencode-start-error: {exc}"
            break

    return OpenCodeResult(
        success=False,
        answer=None,
        error=last_error or "unknown-opencode-error",
        return_code=last_return_code,
        duration_seconds=time.monotonic() - started_at,
        attempts=attempts_used,
        session_id=last_session_id,
        stdout=last_stdout,
        stderr=last_stderr,
    )


def write_raw_outputs(
    output_root: Path,
    split: str,
    relative_path: Path,
    result: OpenCodeResult,
) -> tuple[str, str]:
    raw_base = output_root / "_raw" / split / relative_path
    stdout_path = raw_base.with_suffix(raw_base.suffix + ".stdout.txt")
    stderr_path = raw_base.with_suffix(raw_base.suffix + ".stderr.txt")
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stdout_path.write_text(result.stdout, encoding="utf-8")
    stderr_path.write_text(result.stderr, encoding="utf-8")
    return str(stdout_path), str(stderr_path)


def append_error(error_path: Path, row: dict[str, Any]) -> None:
    error_path.parent.mkdir(parents=True, exist_ok=True)
    with error_path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(row, ensure_ascii=False) + "\n")


def build_result_document(
    answer_document: dict[str, Any],
    result: OpenCodeResult,
    args: argparse.Namespace,
    stdout_path: str,
    stderr_path: str,
) -> dict[str, Any]:
    output = dict(answer_document)
    output["model-output"] = result.answer
    output["opencode-run"] = {
        "success": result.success,
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


def main() -> None:
    args = parse_args()
    if args.timeout_seconds <= 0:
        raise ValueError("--timeout-seconds 必须大于 0")
    if args.retries < 0:
        raise ValueError("--retries 不能小于 0")
    if args.limit is not None and args.limit < 0:
        raise ValueError("--limit 不能小于 0")

    sites = read_site_names(args.site_file)
    if args.limit is not None:
        sites = sites[: args.limit]

    hidden_split_root = args.hidden_root / args.split
    answer_split_root = args.answer_root / args.split
    output_split_root = args.output_root / args.split
    if not hidden_split_root.is_dir():
        raise FileNotFoundError(f"隐藏答案数据目录不存在: {hidden_split_root}")
    if not answer_split_root.is_dir():
        raise FileNotFoundError(f"标准答案数据目录不存在: {answer_split_root}")

    index, ambiguous = build_site_index(hidden_split_root)
    print(
        f"[{args.split}] sites={len(sites)}, samples={len(set(index.values()))}, "
        f"ambiguous_aliases={len(ambiguous)}"
    )

    if not args.dry_run:
        executable = shutil.which(args.opencode_command)
        if executable is None and not Path(args.opencode_command).is_file():
            raise FileNotFoundError(
                f"找不到 OpenCode 命令: {args.opencode_command}；"
                "请安装 OpenCode 或通过 --opencode-command 指定路径"
            )
        args.opencode_workdir.mkdir(parents=True, exist_ok=True)
        args.output_root.mkdir(parents=True, exist_ok=True)
        error_path = args.output_root / "batch_errors.jsonl"
        if error_path.exists():
            error_path.unlink()
    else:
        error_path = args.output_root / "batch_errors.jsonl"

    succeeded = 0
    failed = 0
    for index_number, site in enumerate(sites, start=1):
        try:
            paths = resolve_sample_paths(
                site=site,
                index=index,
                ambiguous=ambiguous,
                hidden_split_root=hidden_split_root,
                answer_split_root=answer_split_root,
                output_split_root=output_split_root,
            )
            hidden_sample = load_json_object(paths.hidden_path)
            prompt = build_prompt(site, hidden_sample)

            if args.dry_run:
                print(f"\n===== {site} -> {paths.relative_path} =====\n{prompt}\n")
                continue

            result = invoke_opencode(args, prompt)
            answer_document = load_json_object(paths.answer_path)
            stdout_path, stderr_path = write_raw_outputs(
                args.output_root,
                args.split,
                paths.relative_path,
                result,
            )
            output_document = build_result_document(
                answer_document,
                result,
                args,
                stdout_path,
                stderr_path,
            )
            write_json(paths.output_path, output_document, args.indent)

            if result.success:
                succeeded += 1
            else:
                failed += 1
                append_error(
                    error_path,
                    {
                        "site": site,
                        "file": str(paths.hidden_path),
                        "output_file": str(paths.output_path),
                        "error": result.error,
                    },
                )
        except Exception as exc:  # noqa: BLE001 - 单个坏样本不能中断整个批次。
            failed += 1
            if not args.dry_run:
                append_error(
                    error_path,
                    {
                        "site": site,
                        "error": f"sample-processing-error: {exc}",
                    },
                )
            print(f"[error] site={site}: {exc}")

        if (
            args.progress_interval > 0
            and index_number % args.progress_interval == 0
        ):
            print(
                f"[{args.split}] processed={index_number}/{len(sites)}, "
                f"succeeded={succeeded}, failed={failed}"
            )

    summary = {
        "split": args.split,
        "site_file": str(args.site_file),
        "requested_sites": len(sites),
        "succeeded": succeeded,
        "failed": failed,
        "dry_run": args.dry_run,
        "output_root": str(args.output_root),
    }
    if not args.dry_run:
        write_json(args.output_root / "batch_summary.json", summary, args.indent)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
