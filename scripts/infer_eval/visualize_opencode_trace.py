#!/usr/bin/env python3
"""将 OpenCode stdout JSON 事件流转换为离线 HTML 轨迹查看器。"""

from __future__ import annotations

import argparse
import html
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote


DEFAULT_INPUT_PATH = Path("opencode-results/_raw")
DEFAULT_OUTPUT_PATH = Path("opencode-traces")
DEFAULT_MAX_DETAIL_CHARS = 200_000

CATEGORY_LABELS = {
    "text": "文本",
    "tool": "工具调用",
    "result": "工具结果",
    "status": "状态",
    "error": "错误",
    "log": "普通日志",
    "unknown": "未知事件",
}


@dataclass
class TraceEvent:
    index: int
    category: str
    event_type: str
    title: str
    summary: str
    timestamp: str
    raw_text: str


@dataclass
class TraceSummary:
    source_path: Path
    output_path: Path
    session_id: str
    event_count: int
    tool_call_count: int
    tool_result_count: int
    error_count: int
    log_count: int
    final_answer: dict[str, Any] | None
    final_answer_error: str
    reference_answer: Any
    reference_answer_error: str
    result_path: Path | None
    stderr_text: str

    @property
    def status(self) -> str:
        if self.final_answer is not None:
            return "answer_extracted"
        if self.error_count or self.stderr_text.strip():
            return "error"
        return "answer_not_found"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "input_path",
        nargs="?",
        type=Path,
        default=DEFAULT_INPUT_PATH,
        help="单个 *.stdout.txt 文件或包含这些文件的目录",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="单文件模式可指定 HTML 文件；批量模式指定输出目录",
    )
    parser.add_argument(
        "--result-root",
        type=Path,
        default=None,
        help=(
            "包含推理结果 train/val 目录的根目录；默认根据 `_raw` "
            "所在位置自动推断"
        ),
    )
    parser.add_argument(
        "--title",
        default="OpenCode Agent 轨迹",
        help="页面标题，默认: %(default)s",
    )
    parser.add_argument(
        "--max-detail-chars",
        type=int,
        default=DEFAULT_MAX_DETAIL_CHARS,
        help="单个事件在 HTML 中最多保留的字符数，0 表示不限制",
    )
    args = parser.parse_args()
    if args.max_detail_chars < 0:
        parser.error("--max-detail-chars 不能小于 0")
    return args


def compact_text(value: str, limit: int = 180) -> str:
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def stringify(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, indent=2)


def nested_value(data: dict[str, Any], *paths: tuple[str, ...]) -> Any:
    for path in paths:
        value: Any = data
        for key in path:
            if not isinstance(value, dict) or key not in value:
                break
            value = value[key]
        else:
            return value
    return None


def event_part(event: dict[str, Any]) -> dict[str, Any]:
    part = event.get("part")
    return part if isinstance(part, dict) else {}


def event_type_name(event: dict[str, Any]) -> str:
    part = event_part(event)
    values = (
        event.get("type"),
        part.get("type"),
        event.get("event"),
        event.get("kind"),
    )
    return "/".join(str(value) for value in values if value is not None) or "unknown"


def event_timestamp(event: dict[str, Any]) -> str:
    value = nested_value(
        event,
        ("timestamp",),
        ("time",),
        ("createdAt",),
        ("created_at",),
        ("part", "time", "start"),
        ("part", "timestamp"),
    )
    return str(value) if value is not None else ""


def event_text(event: dict[str, Any]) -> str:
    part = event_part(event)
    candidates = (
        part.get("text"),
        event.get("output"),
        event.get("content"),
        event.get("text"),
        event.get("message"),
    )
    for value in candidates:
        if isinstance(value, str) and value.strip():
            return value
    return ""


def tool_name(event: dict[str, Any]) -> str:
    value = nested_value(
        event,
        ("tool",),
        ("toolName",),
        ("tool_name",),
        ("name",),
        ("part", "tool"),
        ("part", "toolName"),
        ("part", "name"),
    )
    return str(value) if isinstance(value, (str, int)) else ""


def tool_state(event: dict[str, Any]) -> str:
    value = nested_value(
        event,
        ("state", "status"),
        ("part", "state", "status"),
        ("status",),
        ("part", "status"),
    )
    return str(value).lower() if value is not None else ""


def tool_arguments(event: dict[str, Any]) -> Any:
    return nested_value(
        event,
        ("arguments",),
        ("args",),
        ("input",),
        ("part", "arguments"),
        ("part", "args"),
        ("part", "input"),
        ("part", "state", "input"),
    )


def tool_output(event: dict[str, Any]) -> Any:
    return nested_value(
        event,
        ("result",),
        ("output",),
        ("part", "result"),
        ("part", "output"),
        ("part", "state", "output"),
        ("part", "state", "result"),
    )


def classify_event(event: dict[str, Any]) -> tuple[str, str, str]:
    type_name = event_type_name(event)
    lowered = type_name.lower()
    state = tool_state(event)
    name = tool_name(event)
    text = event_text(event)

    if (
        "error" in lowered
        or state in {"error", "failed", "failure"}
        or event.get("error") is not None
    ):
        message = text or stringify(event.get("error") or state)
        return "error", "执行错误", compact_text(message)

    has_tool_marker = "tool" in lowered or bool(name)
    output = tool_output(event)
    if has_tool_marker and (
        output is not None
        or state in {"completed", "complete", "success", "done"}
        or "result" in lowered
    ):
        title = f"工具结果 · {name}" if name else "工具结果"
        return "result", title, compact_text(stringify(output or state))
    if has_tool_marker:
        arguments = tool_arguments(event)
        title = f"工具调用 · {name}" if name else "工具调用"
        return "tool", title, compact_text(stringify(arguments or state))
    if text:
        return "text", "Agent 文本", compact_text(text)
    if any(token in lowered for token in ("step", "start", "finish", "status")):
        return "status", type_name, compact_text(state or type_name)
    return "unknown", type_name, compact_text(stringify(event))


def parse_json_stream(raw_text: str) -> list[dict[str, Any] | str]:
    """解析连续 JSON，并将无法解析的非空行作为普通日志保留。"""

    decoder = json.JSONDecoder()
    values: list[dict[str, Any] | str] = []
    position = 0
    length = len(raw_text)
    while position < length:
        while position < length and raw_text[position].isspace():
            position += 1
        if position >= length:
            break
        try:
            value, end = decoder.raw_decode(raw_text, position)
        except json.JSONDecodeError:
            line_end = raw_text.find("\n", position)
            if line_end < 0:
                line_end = length
            line = raw_text[position:line_end].strip()
            if line:
                values.append(line)
            position = line_end + 1
            continue
        if isinstance(value, dict):
            values.append(value)
        else:
            values.append(
                {
                    "type": "json_value",
                    "value": value,
                }
            )
        position = end
    return values


def truncate_detail(raw_text: str, max_chars: int) -> str:
    if max_chars == 0 or len(raw_text) <= max_chars:
        return raw_text
    omitted = len(raw_text) - max_chars
    return f"{raw_text[:max_chars]}\n\n… 已省略 {omitted} 个字符 …"


def build_events(
    raw_values: list[dict[str, Any] | str],
    max_detail_chars: int,
) -> list[TraceEvent]:
    events: list[TraceEvent] = []
    for index, value in enumerate(raw_values, start=1):
        if isinstance(value, str):
            category = "log"
            event_type = "plain_log"
            title = "普通日志"
            summary = compact_text(value)
            raw_text = value
            timestamp = ""
        else:
            category, title, summary = classify_event(value)
            event_type = event_type_name(value)
            timestamp = event_timestamp(value)
            raw_text = json.dumps(value, ensure_ascii=False, indent=2)
        events.append(
            TraceEvent(
                index=index,
                category=category,
                event_type=event_type,
                title=title,
                summary=summary,
                timestamp=timestamp,
                raw_text=truncate_detail(raw_text, max_detail_chars),
            )
        )
    return events


def strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def parse_json_object_from_text(text: str) -> dict[str, Any] | None:
    cleaned = strip_code_fence(text)
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        if start < 0:
            return None
        try:
            value, _ = json.JSONDecoder().raw_decode(cleaned, start)
        except json.JSONDecodeError:
            return None
    return value if isinstance(value, dict) else None


def extract_final_answer(
    raw_values: list[dict[str, Any] | str],
) -> tuple[dict[str, Any] | None, str]:
    text_candidates: list[str] = []
    for value in raw_values:
        if isinstance(value, str):
            text_candidates.append(value)
            continue
        text = event_text(value)
        if text:
            text_candidates.append(text)

    for candidate in reversed(text_candidates):
        answer = parse_json_object_from_text(candidate)
        if answer is not None:
            return answer, ""
    if not text_candidates:
        return None, "事件流中没有文本内容"
    return None, "文本事件中没有找到可解析的 JSON 对象"


def extract_session_id(raw_values: list[dict[str, Any] | str]) -> str:
    session_id = ""
    for value in raw_values:
        if not isinstance(value, dict):
            continue
        candidate = value.get("sessionID") or value.get("session_id")
        if isinstance(candidate, str) and candidate:
            session_id = candidate
    return session_id


def companion_stderr_path(stdout_path: Path) -> Path:
    suffix = ".stdout.txt"
    if stdout_path.name.endswith(suffix):
        return stdout_path.with_name(stdout_path.name[: -len(suffix)] + ".stderr.txt")
    return stdout_path.with_suffix(stdout_path.suffix + ".stderr.txt")


def result_json_name(stdout_path: Path) -> str:
    suffix = ".stdout.txt"
    if stdout_path.name.endswith(suffix):
        return stdout_path.name[: -len(suffix)]
    return stdout_path.name


def infer_result_path(
    stdout_path: Path,
    result_root: Path | None,
    raw_input_root: Path,
) -> Path | None:
    """定位与 raw stdout 对应的、同时包含标准答案的推理结果 JSON。"""

    if result_root is not None:
        if raw_input_root.is_dir():
            relative_path = stdout_path.relative_to(raw_input_root)
        else:
            raw_parent = next(
                (parent for parent in stdout_path.parents if parent.name == "_raw"),
                None,
            )
            relative_path = (
                stdout_path.relative_to(raw_parent)
                if raw_parent is not None
                else Path(stdout_path.name)
            )
        return result_root / relative_path.with_name(result_json_name(stdout_path))

    for parent in stdout_path.parents:
        if parent.name != "_raw":
            continue
        relative_path = stdout_path.relative_to(parent)
        return parent.parent / relative_path.with_name(result_json_name(stdout_path))
    return None


def load_reference_answer(
    result_path: Path | None,
) -> tuple[Any, str]:
    if result_path is None:
        return None, "无法自动定位结果 JSON；请使用 --result-root 指定结果目录"
    if not result_path.is_file():
        return None, f"未找到对应结果 JSON：{result_path}"
    try:
        document = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return None, f"结果 JSON 读取失败：{type(error).__name__}: {error}"
    if not isinstance(document, dict):
        return None, "结果 JSON 顶层不是对象"
    if "task_answer" not in document:
        return None, "结果 JSON 中不存在 task_answer"
    return document["task_answer"], ""


def escaped(value: Any) -> str:
    return html.escape(str(value), quote=True)


def metric(label: str, value: Any, tone: str = "") -> str:
    return (
        f'<div class="metric {escaped(tone)}">'
        f'<span class="metric-label">{escaped(label)}</span>'
        f'<strong>{escaped(value)}</strong></div>'
    )


def event_card(event: TraceEvent) -> str:
    search_text = " ".join(
        (event.category, event.event_type, event.title, event.summary)
    ).lower()
    timestamp = (
        f'<span class="event-time">{escaped(event.timestamp)}</span>'
        if event.timestamp
        else ""
    )
    return f"""
<button class="event-row" type="button"
        data-category="{escaped(event.category)}"
        data-search="{escaped(search_text)}"
        data-template="event-detail-{event.index}">
  <span class="event-index">{event.index}</span>
  <span class="event-marker marker-{escaped(event.category)}"></span>
  <span class="event-main">
    <span class="event-title">{escaped(event.title)}</span>
    <span class="event-summary">{escaped(event.summary)}</span>
  </span>
  {timestamp}
</button>
<template id="event-detail-{event.index}">
  <div class="detail-heading">
    <span class="badge badge-{escaped(event.category)}">
      {escaped(CATEGORY_LABELS[event.category])}
    </span>
    <strong>#{event.index} · {escaped(event.title)}</strong>
  </div>
  <dl class="detail-meta">
    <dt>事件类型</dt><dd>{escaped(event.event_type)}</dd>
    <dt>时间</dt><dd>{escaped(event.timestamp or "未提供")}</dd>
  </dl>
  <pre>{escaped(event.raw_text)}</pre>
</template>
"""


def detail_page_html(
    title: str,
    source_path: Path,
    events: list[TraceEvent],
    summary: TraceSummary,
) -> str:
    category_counts = {
        category: sum(event.category == category for event in events)
        for category in CATEGORY_LABELS
    }
    filters = "\n".join(
        f"""<label class="filter-option">
  <input type="checkbox" value="{escaped(category)}" checked>
  <span>{escaped(label)}</span><small>{category_counts[category]}</small>
</label>"""
        for category, label in CATEGORY_LABELS.items()
        if category_counts[category]
    )
    model_answer_html = (
        escaped(json.dumps(summary.final_answer, ensure_ascii=False, indent=2))
        if summary.final_answer is not None
        else escaped(summary.final_answer_error)
    )
    model_answer_class = "success" if summary.final_answer is not None else "warning"
    reference_answer_html = (
        escaped(json.dumps(summary.reference_answer, ensure_ascii=False, indent=2))
        if not summary.reference_answer_error
        else escaped(summary.reference_answer_error)
    )
    reference_answer_class = (
        "success" if not summary.reference_answer_error else "warning"
    )
    stderr_section = ""
    if summary.stderr_text.strip():
        stderr_section = f"""
<section class="stderr-section">
  <h2>标准错误输出</h2>
  <pre>{escaped(summary.stderr_text)}</pre>
</section>"""

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escaped(title)} · {escaped(source_path.name)}</title>
<style>
:root {{
  --bg: #f4f6f8;
  --surface: #ffffff;
  --line: #d8dee5;
  --text: #18212b;
  --muted: #657180;
  --blue: #1769aa;
  --green: #2d7d46;
  --amber: #a65d00;
  --red: #b42318;
  --cyan: #087e8b;
  --violet: #6d4c9f;
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font: 14px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
}}
header {{
  padding: 20px 24px;
  background: #17212b;
  color: white;
  border-bottom: 3px solid #e0a100;
}}
header h1 {{ margin: 0; font-size: 22px; letter-spacing: 0; }}
header p {{ margin: 5px 0 0; color: #c9d2dc; overflow-wrap: anywhere; }}
.metrics {{
  display: grid;
  grid-template-columns: repeat(6, minmax(110px, 1fr));
  gap: 1px;
  background: var(--line);
  border-bottom: 1px solid var(--line);
}}
.metric {{
  min-height: 72px;
  padding: 12px 16px;
  background: var(--surface);
}}
.metric-label {{ display: block; color: var(--muted); font-size: 12px; }}
.metric strong {{ display: block; margin-top: 4px; font-size: 19px; }}
.metric.success strong {{ color: var(--green); }}
.metric.warning strong {{ color: var(--amber); }}
.metric.error strong {{ color: var(--red); }}
.toolbar {{
  display: flex;
  gap: 16px;
  align-items: center;
  padding: 12px 18px;
  background: var(--surface);
  border-bottom: 1px solid var(--line);
  position: sticky;
  top: 0;
  z-index: 5;
}}
.search {{
  width: min(420px, 40vw);
  padding: 8px 10px;
  border: 1px solid #aeb8c3;
  border-radius: 4px;
  font: inherit;
}}
.filters {{ display: flex; flex-wrap: wrap; gap: 6px 12px; }}
.filter-option {{ display: flex; align-items: center; gap: 5px; color: #344050; }}
.filter-option small {{
  padding: 0 5px;
  border-radius: 8px;
  background: #e7ebef;
  color: var(--muted);
}}
.layout {{
  display: grid;
  grid-template-columns: minmax(420px, 46%) 1fr;
  min-height: 640px;
}}
.timeline {{
  border-right: 1px solid var(--line);
  background: var(--surface);
  overflow: auto;
  max-height: calc(100vh - 188px);
}}
.empty {{ padding: 40px; color: var(--muted); text-align: center; }}
.event-row {{
  width: 100%;
  display: grid;
  grid-template-columns: 42px 12px minmax(0, 1fr) auto;
  gap: 9px;
  align-items: start;
  padding: 10px 14px;
  border: 0;
  border-bottom: 1px solid #e5e9ed;
  background: white;
  color: inherit;
  text-align: left;
  cursor: pointer;
}}
.event-row:hover, .event-row.active {{ background: #eef5fa; }}
.event-index {{ color: var(--muted); text-align: right; font-variant-numeric: tabular-nums; }}
.event-marker {{ width: 9px; height: 9px; margin-top: 5px; border-radius: 50%; background: #7b8794; }}
.marker-text {{ background: var(--blue); }}
.marker-tool {{ background: var(--violet); }}
.marker-result {{ background: var(--green); }}
.marker-status {{ background: var(--cyan); }}
.marker-error {{ background: var(--red); }}
.marker-log {{ background: var(--amber); }}
.event-main {{ min-width: 0; display: block; }}
.event-title {{ display: block; font-weight: 650; }}
.event-summary {{
  display: block;
  margin-top: 2px;
  color: var(--muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}}
.event-time {{ color: var(--muted); font-size: 12px; }}
.detail {{
  padding: 20px;
  overflow: auto;
  max-height: calc(100vh - 188px);
}}
.detail-heading {{ display: flex; align-items: center; gap: 9px; margin-bottom: 14px; }}
.badge {{
  padding: 2px 7px;
  border-radius: 3px;
  background: #e7ebef;
  color: #344050;
  font-size: 12px;
}}
.badge-error {{ background: #fee4e2; color: var(--red); }}
.badge-tool {{ background: #efe8f8; color: var(--violet); }}
.badge-result {{ background: #e2f2e7; color: var(--green); }}
.badge-text {{ background: #e1eff9; color: var(--blue); }}
.detail-meta {{
  display: grid;
  grid-template-columns: 90px 1fr;
  margin: 0 0 14px;
}}
.detail-meta dt {{ color: var(--muted); }}
.detail-meta dd {{ margin: 0; overflow-wrap: anywhere; }}
pre {{
  margin: 0;
  padding: 14px;
  border: 1px solid #303a44;
  border-radius: 4px;
  background: #111820;
  color: #e6edf3;
  font: 12px/1.55 ui-monospace, SFMono-Regular, Consolas, monospace;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}}
.bottom-grid {{
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  padding: 18px;
}}
.bottom-grid section, .stderr-section {{
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 16px;
}}
.trace-note {{ grid-column: 1 / -1; }}
h2 {{ margin: 0 0 12px; font-size: 16px; }}
.answer.success h2 {{ color: var(--green); }}
.answer.warning h2 {{ color: var(--amber); }}
.stderr-section {{ margin: 0 18px 18px; }}
@media (max-width: 900px) {{
  .metrics {{ grid-template-columns: repeat(2, 1fr); }}
  .toolbar {{ position: static; align-items: stretch; flex-direction: column; }}
  .search {{ width: 100%; }}
  .layout {{ grid-template-columns: 1fr; }}
  .timeline, .detail {{ max-height: none; }}
  .timeline {{ border-right: 0; border-bottom: 1px solid var(--line); }}
  .bottom-grid {{ grid-template-columns: 1fr; }}
}}
</style>
</head>
<body>
<header>
  <h1>{escaped(title)}</h1>
  <p>{escaped(source_path)}</p>
</header>
<section class="metrics">
  {metric("状态", summary.status, "success" if summary.final_answer else "warning")}
  {metric("事件", summary.event_count)}
  {metric("工具调用", summary.tool_call_count)}
  {metric("工具结果", summary.tool_result_count)}
  {metric("错误", summary.error_count, "error" if summary.error_count else "")}
  {metric("Session", summary.session_id or "未提供")}
</section>
<div class="toolbar">
  <input id="search" class="search" type="search" placeholder="搜索节点、工具、错误或事件类型">
  <div class="filters">{filters}</div>
</div>
<main class="layout">
  <section id="timeline" class="timeline">
    {"".join(event_card(event) for event in events)}
    <div id="empty" class="empty" hidden>没有符合条件的事件</div>
  </section>
  <section id="detail" class="detail">
    <div class="empty">选择左侧事件查看原始详情</div>
  </section>
</main>
<div class="bottom-grid">
  <section class="answer {reference_answer_class}">
    <h2>输出</h2>
    <pre>{reference_answer_html}</pre>
  </section>
  <section class="answer {model_answer_class}">
    <h2>模型答案</h2>
    <pre>{model_answer_html}</pre>
  </section>
  <section class="trace-note">
    <h2>轨迹说明</h2>
    <p>本页面展示 OpenCode <code>--format json</code> 写入 stdout 的事件流。
    它包含 Agent 文本、工具调用、工具结果和状态事件，但不代表模型未公开的内部思维过程。</p>
    <p>“输出”读取对应推理结果 JSON 的 <code>task_answer</code>；
    “模型答案”来自 stdout 事件流中提取的最终 JSON。未知事件和普通日志会保留。</p>
  </section>
</div>
{stderr_section}
<script>
const rows = [...document.querySelectorAll(".event-row")];
const search = document.getElementById("search");
const checks = [...document.querySelectorAll('.filters input[type="checkbox"]')];
const detail = document.getElementById("detail");
const empty = document.getElementById("empty");

rows.forEach(row => {{
  const template = document.getElementById(row.dataset.template);
  row.fullSearch = `${{row.dataset.search}} ${{template.content.textContent}}`.toLowerCase();
}});

function applyFilters() {{
  const query = search.value.trim().toLowerCase();
  const enabled = new Set(checks.filter(item => item.checked).map(item => item.value));
  let visible = 0;
  rows.forEach(row => {{
    const show = enabled.has(row.dataset.category) &&
      (!query || row.fullSearch.includes(query));
    row.hidden = !show;
    if (show) visible += 1;
  }});
  empty.hidden = visible !== 0;
}}

rows.forEach(row => row.addEventListener("click", () => {{
  rows.forEach(item => item.classList.remove("active"));
  row.classList.add("active");
  const template = document.getElementById(row.dataset.template);
  detail.replaceChildren(template.content.cloneNode(true));
}}));
search.addEventListener("input", applyFilters);
checks.forEach(item => item.addEventListener("change", applyFilters));
if (rows.length) rows[0].click();
</script>
</body>
</html>
"""


def analyze_trace(
    stdout_path: Path,
    output_path: Path,
    title: str,
    max_detail_chars: int,
    result_root: Path | None,
    raw_input_root: Path,
) -> TraceSummary:
    raw_text = stdout_path.read_text(encoding="utf-8", errors="replace")
    raw_values = parse_json_stream(raw_text)
    events = build_events(raw_values, max_detail_chars)
    final_answer, final_answer_error = extract_final_answer(raw_values)
    result_path = infer_result_path(stdout_path, result_root, raw_input_root)
    reference_answer, reference_answer_error = load_reference_answer(result_path)
    stderr_path = companion_stderr_path(stdout_path)
    stderr_text = (
        stderr_path.read_text(encoding="utf-8", errors="replace")
        if stderr_path.is_file()
        else ""
    )
    summary = TraceSummary(
        source_path=stdout_path,
        output_path=output_path,
        session_id=extract_session_id(raw_values),
        event_count=len(events),
        tool_call_count=sum(event.category == "tool" for event in events),
        tool_result_count=sum(event.category == "result" for event in events),
        error_count=sum(event.category == "error" for event in events),
        log_count=sum(event.category == "log" for event in events),
        final_answer=final_answer,
        final_answer_error=final_answer_error,
        reference_answer=reference_answer,
        reference_answer_error=reference_answer_error,
        result_path=result_path,
        stderr_text=stderr_text,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        detail_page_html(title, stdout_path, events, summary),
        encoding="utf-8",
    )
    return summary


def output_relative_path(relative_source: Path) -> Path:
    name = relative_source.name
    if name.endswith(".stdout.txt"):
        name = name[: -len(".stdout.txt")] + ".html"
    else:
        name += ".html"
    return relative_source.with_name(name)


def status_label(status: str) -> str:
    return {
        "answer_extracted": "已提取答案",
        "error": "存在错误",
        "answer_not_found": "未找到答案",
    }.get(status, status)


def index_html(
    title: str,
    input_root: Path,
    summaries: list[TraceSummary],
) -> str:
    rows: list[str] = []
    for summary in summaries:
        rows.append(
            f"""<tr data-search="{escaped(str(summary.source_path).lower())}">
  <td>{escaped(summary.source_path.relative_to(input_root))}</td>
  <td><span class="status status-{escaped(summary.status)}">
    {escaped(status_label(summary.status))}
  </span></td>
  <td>{summary.event_count}</td>
  <td>{summary.tool_call_count}</td>
  <td>{summary.tool_result_count}</td>
  <td>{summary.error_count}</td>
  <td class="session">{escaped(summary.session_id or "—")}</td>
  <td><a href="{quote(str(summary.output_path))}">查看轨迹</a></td>
</tr>"""
        )

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escaped(title)} · 总览</title>
<style>
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  background: #f4f6f8;
  color: #18212b;
  font: 14px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
}}
header {{ padding: 22px 26px; background: #17212b; color: white; border-bottom: 3px solid #e0a100; }}
h1 {{ margin: 0; font-size: 22px; letter-spacing: 0; }}
header p {{ margin: 5px 0 0; color: #c9d2dc; overflow-wrap: anywhere; }}
main {{ padding: 18px; }}
.summary {{
  display: grid;
  grid-template-columns: repeat(4, minmax(120px, 1fr));
  margin-bottom: 16px;
  border: 1px solid #d8dee5;
  background: white;
}}
.metric {{ padding: 13px 16px; border-right: 1px solid #d8dee5; }}
.metric:last-child {{ border-right: 0; }}
.metric span {{ display: block; color: #657180; font-size: 12px; }}
.metric strong {{ display: block; margin-top: 3px; font-size: 20px; }}
.search {{
  width: min(520px, 100%);
  margin-bottom: 12px;
  padding: 9px 11px;
  border: 1px solid #aeb8c3;
  border-radius: 4px;
  font: inherit;
}}
.table-wrap {{ overflow-x: auto; border: 1px solid #d8dee5; background: white; }}
table {{ width: 100%; border-collapse: collapse; }}
th, td {{ padding: 10px 12px; border-bottom: 1px solid #e3e7eb; text-align: left; }}
th {{ position: sticky; top: 0; background: #edf1f4; color: #45515f; font-size: 12px; }}
tbody tr:hover {{ background: #f1f7fb; }}
.status {{ display: inline-block; padding: 2px 7px; border-radius: 3px; white-space: nowrap; }}
.status-answer_extracted {{ background: #e2f2e7; color: #2d7d46; }}
.status-error {{ background: #fee4e2; color: #b42318; }}
.status-answer_not_found {{ background: #fff0d5; color: #9a5700; }}
.session {{ max-width: 220px; overflow-wrap: anywhere; color: #657180; }}
a {{ color: #1769aa; font-weight: 650; text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
@media (max-width: 720px) {{
  .summary {{ grid-template-columns: repeat(2, 1fr); }}
}}
</style>
</head>
<body>
<header>
  <h1>{escaped(title)} · 总览</h1>
  <p>{escaped(input_root)}</p>
</header>
<main>
  <section class="summary">
    {metric("轨迹文件", len(summaries))}
    {metric("已提取答案", sum(item.final_answer is not None for item in summaries), "success")}
    {metric("存在错误", sum(item.status == "error" for item in summaries), "error")}
    {metric("工具调用", sum(item.tool_call_count for item in summaries))}
  </section>
  <input id="search" class="search" type="search" placeholder="搜索文件名或路径">
  <div class="table-wrap">
    <table>
      <thead><tr>
        <th>文件</th><th>状态</th><th>事件</th><th>工具调用</th>
        <th>工具结果</th><th>错误</th><th>Session</th><th>详情</th>
      </tr></thead>
      <tbody>{"".join(rows)}</tbody>
    </table>
  </div>
</main>
<script>
const search = document.getElementById("search");
const rows = [...document.querySelectorAll("tbody tr")];
search.addEventListener("input", () => {{
  const query = search.value.trim().toLowerCase();
  rows.forEach(row => row.hidden = query && !row.dataset.search.includes(query));
}});
</script>
</body>
</html>
"""


def collect_stdout_files(input_path: Path) -> list[Path]:
    if input_path.is_file():
        return [input_path]
    if not input_path.is_dir():
        raise FileNotFoundError(f"输入文件或目录不存在: {input_path}")
    return sorted(
        path
        for path in input_path.rglob("*.stdout.txt")
        if path.is_file()
    )


def main() -> None:
    args = parse_args()
    input_path = args.input_path.resolve()
    output = args.output.resolve()
    result_root = args.result_root.resolve() if args.result_root is not None else None
    stdout_files = collect_stdout_files(input_path)
    if not stdout_files:
        raise FileNotFoundError(f"没有找到 *.stdout.txt: {input_path}")

    if input_path.is_file():
        output_path = output if output.suffix.lower() == ".html" else output / (
            output_relative_path(Path(input_path.name))
        )
        summary = analyze_trace(
            input_path,
            output_path,
            args.title,
            args.max_detail_chars,
            result_root,
            input_path,
        )
        print(f"已生成: {summary.output_path}")
        return

    output.mkdir(parents=True, exist_ok=True)
    summaries: list[TraceSummary] = []
    for index, stdout_path in enumerate(stdout_files, start=1):
        relative_source = stdout_path.relative_to(input_path)
        relative_output = output_relative_path(relative_source)
        summary = analyze_trace(
            stdout_path,
            output / relative_output,
            args.title,
            args.max_detail_chars,
            result_root,
            input_path,
        )
        # index.html 中链接必须使用相对于输出目录的路径。
        summary.output_path = relative_output
        summaries.append(summary)
        if index % 100 == 0 or index == len(stdout_files):
            print(f"生成进度 {index}/{len(stdout_files)}", flush=True)

    (output / "index.html").write_text(
        index_html(args.title, input_path, summaries),
        encoding="utf-8",
    )
    print(f"总览页面: {output / 'index.html'}")


if __name__ == "__main__":
    main()
