"""Prompt construction and output parsing for config QA samples."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional


DEFAULT_SYSTEM_PROMPT = (
    "你是网络配置生成助手。你必须只输出一个合法 JSON 对象，"
    "不要输出 Markdown，不要解释，不要添加与目标配置无关的字段。"
)


def load_qa_sample(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        sample = json.load(fh)
    if not isinstance(sample, dict):
        raise ValueError("QA sample must be a JSON object: %s" % path)
    return sample


def json_text(value: Any, indent: Optional[int] = 2) -> str:
    if indent is None:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return json.dumps(value, ensure_ascii=False, indent=indent)


def build_messages(
    sample: Dict[str, Any],
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    input_json_indent: Optional[int] = 2,
) -> List[Dict[str, str]]:
    prompt = str(sample.get("prompt", "")).strip()
    input_payload = sample.get("input", {})
    user_content = (
        "%s\n\n"
        "下面是已经遮挡目标配置后的网络图上下文 input，请根据上下文生成目标配置。\n"
        "输入 JSON:\n%s\n\n"
        "输出要求：只输出目标配置对象本身，必须是合法 JSON。"
    ) % (prompt, json_text(input_payload, input_json_indent))
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]


def strip_markdown_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if len(lines) >= 2 and lines[0].startswith("```") and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return stripped


def extract_json_value(text: str) -> Any:
    """Parse model text as JSON, with a fallback for fenced or prefixed output."""

    stripped = strip_markdown_fence(text)
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    starts = [idx for idx, char in enumerate(stripped) if char in "[{"]
    for start in starts:
        try:
            value, _ = decoder.raw_decode(stripped[start:])
            return value
        except json.JSONDecodeError:
            continue
    raise ValueError("model output does not contain valid JSON")
