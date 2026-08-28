#!/usr/bin/env python3
"""vLLM 批量推理的文件扫描、请求、解析和结果落盘公共逻辑。"""

from __future__ import annotations

import csv
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from task_specs import TaskSpec


SYSTEM_PROMPT = (
    "你是网络物理拓扑分析助手。请严格依据输入拓扑和 task_question 完成任务，"
    "不得猜测不存在的节点、链路或配置。只输出合法 JSON，不要输出解释、"
    "Markdown、代码块或思考过程。"
)


@dataclass(frozen=True)
class SamplePaths:
    split: str
    relative_path: Path
    hidden_path: Path
    answer_path: Path
    output_path: Path


def load_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON 顶层必须是对象: {path}")
    return value


def write_json_atomic(path: Path, value: dict[str, Any], indent: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=indent) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def collect_samples(
    hidden_root: Path,
    answer_root: Path,
    output_root: Path,
    split: str,
) -> list[SamplePaths]:
    selected_splits = ("train", "val") if split == "all" else (split,)
    samples: list[SamplePaths] = []
    for split_name in selected_splits:
        hidden_split = hidden_root / split_name
        answer_split = answer_root / split_name
        if not hidden_split.is_dir():
            raise FileNotFoundError(f"without_answer 目录不存在: {hidden_split}")
        if not answer_split.is_dir():
            raise FileNotFoundError(f"with_answer 目录不存在: {answer_split}")
        for hidden_path in sorted(hidden_split.rglob("*.json")):
            if not hidden_path.is_file():
                continue
            relative_path = hidden_path.relative_to(hidden_split)
            answer_path = answer_split / relative_path
            samples.append(
                SamplePaths(
                    split=split_name,
                    relative_path=relative_path,
                    hidden_path=hidden_path,
                    answer_path=answer_path,
                    output_path=output_root / split_name / relative_path,
                )
            )
    return samples


def build_prompt(sample: dict[str, Any]) -> str:
    question = sample.get("task_question")
    if not isinstance(question, str) or not question.strip():
        raise ValueError("样本缺少有效的 task_question")
    task_json = json.dumps(sample, ensure_ascii=False, separators=(",", ":"))
    return f"""请完成以下任务：

{question}

【完整任务拓扑 JSON】
{task_json}
"""


def _validate_path_list(value: Any, path_length: int) -> None:
    if not isinstance(value, list) or not value:
        raise ValueError("paths 必须是非空数组")
    for index, path in enumerate(value):
        if not isinstance(path, list) or not path:
            raise ValueError(f"paths[{index}] 必须是非空数组")
        if len(path) != path_length + 1:
            raise ValueError(f"paths[{index}] 与 path_length 不一致")
        if any(not isinstance(node_id, str) or not node_id for node_id in path):
            raise ValueError(f"paths[{index}] 包含非法节点 ID")


def validate_answer(answer: dict[str, Any], spec: TaskSpec) -> None:
    if spec.answer_kind in {"path", "extended_path"}:
        path_length = answer.get("path_length")
        if isinstance(path_length, bool) or not isinstance(path_length, int):
            raise ValueError("path_length 必须是整数")
        if path_length < 0:
            raise ValueError("path_length 不能小于 0")
        _validate_path_list(answer.get("paths"), path_length)
        if spec.answer_kind == "extended_path":
            paths = answer["paths"]
            for field_name in ("path_role_sequences", "path_device_names"):
                sequences = answer.get(field_name)
                if not isinstance(sequences, list) or len(sequences) != len(paths):
                    raise ValueError(f"{field_name} 必须与 paths 一一对应")
                for index, sequence in enumerate(sequences):
                    if (
                        not isinstance(sequence, list)
                        or len(sequence) != len(paths[index])
                        or any(not isinstance(item, str) for item in sequence)
                    ):
                        raise ValueError(f"{field_name}[{index}] 结构不合法")
        return

    if spec.answer_kind == "node_set" and spec.answer_field:
        values = answer.get(spec.answer_field)
        if not isinstance(values, list):
            raise ValueError(f"{spec.answer_field} 必须是数组")
        if any(not isinstance(item, str) or not item for item in values):
            raise ValueError(f"{spec.answer_field} 包含非法节点 ID")
        if len(values) != len(set(values)):
            raise ValueError(f"{spec.answer_field} 不能包含重复节点 ID")
        return

    raise ValueError(f"未知答案类型: {spec.answer_kind}")


def strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()[1:]
    if lines and lines[-1].strip() == "```":
        lines.pop()
    return "\n".join(lines).strip()


def parse_model_output(text: str, spec: TaskSpec) -> dict[str, Any]:
    cleaned = strip_code_fence(text)
    candidates: list[dict[str, Any]] = []
    try:
        value = json.loads(cleaned)
        if isinstance(value, dict):
            candidates.append(value)
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    for position, character in enumerate(cleaned):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(cleaned, position)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and value not in candidates:
            candidates.append(value)
    errors: list[str] = []
    for candidate in candidates:
        try:
            validate_answer(candidate, spec)
            return candidate
        except ValueError as error:
            errors.append(str(error))
    if errors:
        raise ValueError(f"模型 JSON 结构不符合任务要求: {errors[0]}")
    raise ValueError("模型回答中没有可解析的 JSON 对象")


def successful_result(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        document = load_json_object(path)
    except Exception:
        return False
    metadata = document.get("inference_metadata")
    return bool(
        isinstance(metadata, dict)
        and metadata.get("success") is True
        and isinstance(document.get("model-output"), dict)
    )


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = ("split", "source_file", "output_file", "error_stage", "error")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def elapsed_text(started_at: float) -> str:
    seconds = max(0, int(time.monotonic() - started_at))
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"

