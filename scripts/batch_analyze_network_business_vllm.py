#!/usr/bin/env python3
"""调用 OpenAI-compatible vLLM 服务批量生成通信网络业务分析与 HTML 报告。"""

from __future__ import annotations

import argparse
import csv
import html
import json
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from topology_visualizer.generate_topology_visualizations import (  # noqa: E402
    graph_page,
    parse_graph,
)


DEFAULT_DATASET_ROOT = Path("datasets")
DEFAULT_OUTPUT_ROOT = Path("network-business-analysis")
DEFAULT_BASE_URL = "http://localhost:8000/v1"
DEFAULT_API_KEY = "empty"
DEFAULT_MODEL = "qwen3-8b"
DEFAULT_SPLIT = "all"
DEFAULT_TEMPERATURE = 0.2
DEFAULT_REQUEST_TIMEOUT = 1200.0
DEFAULT_RETRIES = 1
DEFAULT_RETRY_WAIT_SECONDS = 5.0
DEFAULT_WAIT_SECONDS = 0.0
DEFAULT_PROGRESS_INTERVAL = 1
DEFAULT_MAX_CONFIG_INTERPRETATIONS = 20
REPORT_VERSION = 2

SUMMARY_FILE = "analysis_summary.json"
FAILURE_FILE = "analysis_failures.csv"
INDEX_FILE = "index.html"

SYSTEM_PROMPT = """你是一名通信网络架构与运维专家，负责帮助不熟悉通信网络业务的用户理解站点拓扑。

分析必须严格基于输入 JSON，不得虚构不存在的设备、链路、配置、协议、VLAN、业务或故障。

要求：
1. 对重要结论提供证据，证据应包含节点 ID、设备名称、设备角色或配置顶层 Key。
2. 明确区分明确事实、合理推断和信息不足。合理推断不能表述为已确认事实。
3. 使用通俗中文解释通信网络术语。
4. 不输出思考过程、Markdown 代码块或 JSON 之外的文本。
5. 严格返回用户指定结构的一个合法 JSON 对象。"""

USER_PROMPT_TEMPLATE = """请分析下面的完整站点网络拓扑，帮助用户理解其网络结构、业务作用和潜在风险。

重点分析：
1. 站点规模、设备类型和设备角色分布；
2. 接入层、汇聚层、核心层、出口和安全边界；
3. 典型 AP 到上游设备的物理路径；
4. 网络冗余、潜在单点故障及其影响范围；
5. VLAN 和关键配置在节点或设备组中的分布；
6. 当前数据无法确定的信息。

请严格返回以下 JSON 结构。没有内容的数组也必须保留：
{{
  "site_summary": "站点整体概况的中文说明",
  "topology_layers": [
    {{
      "layer": "接入层/汇聚层/核心层/出口与安全边界/其他",
      "description": "该层级的作用和当前拓扑情况",
      "evidence_node_ids": ["节点ID"]
    }}
  ],
  "typical_paths": [
    {{
      "description": "路径的业务含义",
      "node_ids": ["按顺序排列的节点ID"]
    }}
  ],
  "business_observations": [
    {{
      "level": "fact或inference",
      "title": "结论标题",
      "description": "事实或合理推断",
      "evidence": ["节点ID、设备名称、角色或配置Key"]
    }}
  ],
  "risks": [
    {{
      "severity": "high或medium或low",
      "title": "风险标题",
      "description": "风险及可能影响",
      "affected_node_ids": ["可能受影响的节点ID"],
      "evidence": ["支持该判断的节点或链路证据"]
    }}
  ],
  "vlan_and_config": [
    {{
      "title": "配置发现标题",
      "description": "配置分布和可以确认的含义",
      "evidence": ["节点ID或设备组及配置Key"]
    }}
  ],
  "config_interpretations": [
    {{
      "config_ref": "必须来自配置索引的引用",
      "title": "配置的通俗名称",
      "interpretation": "严格基于配置字段的业务理解",
      "business_impact": "该配置可能影响的网络行为",
      "certainty": "fact或inference",
      "unknowns": ["仅凭当前配置无法确认的信息"]
    }}
  ],
  "unknowns": ["当前 JSON 无法确认的信息"],
  "plain_language_conclusion": "面向非网络专业人员的简明总结"
}}

不要仅凭设备名称推断链路，不要仅凭相同 VLAN ID 断定业务连通，也不要把配置 Key 的字面含义当作已经验证的业务事实。

请从下面的配置索引中选择最多 {max_config_interpretations} 段具有代表性或业务意义的配置进行逐段解读。
config_ref 必须逐字使用索引中已有的值。配置索引只提供位置，具体字段和值请在完整拓扑 JSON 中查找。

【配置索引】
{config_catalog_json}

【完整站点网络拓扑 JSON】
{topology_json}
"""

LIST_SECTIONS = (
    "topology_layers",
    "typical_paths",
    "business_observations",
    "risks",
    "vlan_and_config",
    "config_interpretations",
    "unknowns",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "dataset_root",
        nargs="?",
        type=Path,
        default=DEFAULT_DATASET_ROOT,
        help="原始数据集根目录，目录下应包含 train/val",
    )
    parser.add_argument(
        "-o",
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="JSON、HTML 和汇总文件的输出根目录",
    )
    parser.add_argument(
        "--split",
        choices=["train", "val", "all"],
        default=DEFAULT_SPLIT,
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--api-key", default=DEFAULT_API_KEY)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--temperature", type=float, default=DEFAULT_TEMPERATURE)
    parser.add_argument(
        "--request-timeout",
        type=float,
        default=DEFAULT_REQUEST_TIMEOUT,
        help="单次请求超时秒数，默认: %(default)s",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=DEFAULT_RETRIES,
        help="请求或输出解析失败后的重试次数，默认: %(default)s",
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
        help="每个样本处理完成后的等待秒数",
    )
    parser.add_argument(
        "--progress-interval",
        type=int,
        default=DEFAULT_PROGRESS_INTERVAL,
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="只处理排序后的前 N 个文件，用于小规模测试",
    )
    parser.add_argument(
        "--max-config-interpretations",
        type=int,
        default=DEFAULT_MAX_CONFIG_INTERPRETATIONS,
        help="每个站点最多要求模型解读的代表性配置数，默认: %(default)s",
    )
    parser.add_argument(
        "--enable-thinking",
        action="store_true",
        help="开启模型思考模式；默认关闭",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="跳过已经成功生成结构化分析结果的文件",
    )
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
    if args.max_config_interpretations < 0:
        parser.error("--max-config-interpretations 不能小于 0")
    return args


def import_openai() -> Any:
    try:
        from openai import OpenAI
    except ImportError as error:
        raise RuntimeError("缺少 openai 依赖，请执行: pip install openai") from error
    return OpenAI


def collect_files(dataset_root: Path, split: str) -> list[tuple[str, Path]]:
    splits = ["train", "val"] if split == "all" else [split]
    items: list[tuple[str, Path]] = []
    for split_name in splits:
        split_root = dataset_root / split_name
        if not split_root.is_dir():
            raise FileNotFoundError(f"数据划分目录不存在: {split_root}")
        items.extend(
            (split_name, path)
            for path in sorted(split_root.rglob("*.json"))
            if path.is_file()
        )
    return items


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def config_objects(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [value]
    return []


def device_name(node: dict[str, Any]) -> str:
    device = node.get("devices")
    if not isinstance(device, dict):
        device = node.get("device")
    name = device.get("NAME") if isinstance(device, dict) else None
    return str(name) if name is not None and str(name).strip() else ""


def extract_config_entries(graph: dict[str, Any]) -> list[dict[str, Any]]:
    """按配置顶层 Key 提取真实配置，并生成稳定的 JSON 路径引用。"""

    entries: list[dict[str, Any]] = []
    nodes = graph.get("nodes")
    if isinstance(nodes, list):
        for node_index, node in enumerate(nodes):
            if not isinstance(node, dict):
                continue
            node_id = str(node.get("id", f"index-{node_index}"))
            name = device_name(node)
            for field_name in ("configs", "config"):
                raw_configs = config_objects(node.get(field_name))
                for config_index, config in enumerate(raw_configs):
                    for top_key, value in config.items():
                        config_ref = (
                            f"nodes[{node_index}].{field_name}[{config_index}].{top_key}"
                        )
                        entries.append(
                            {
                                "config_ref": config_ref,
                                "scope": "node",
                                "owner_id": node_id,
                                "owner_name": name,
                                "top_level_key": str(top_key),
                                "configuration": {str(top_key): value},
                            }
                        )

    groups = graph.get("deviceGroups")
    if isinstance(groups, list):
        for group_index, group in enumerate(groups):
            if not isinstance(group, dict):
                continue
            group_data = group.get("deviceGroup")
            if not isinstance(group_data, dict):
                group_data = {}
            group_name = str(group_data.get("NAME", f"index-{group_index}"))
            raw_configs = config_objects(group.get("configs"))
            for config_index, config in enumerate(raw_configs):
                for top_key, value in config.items():
                    config_ref = (
                        f"deviceGroups[{group_index}].configs[{config_index}].{top_key}"
                    )
                    entries.append(
                        {
                            "config_ref": config_ref,
                            "scope": "deviceGroup",
                            "owner_id": group_name,
                            "owner_name": group_name,
                            "top_level_key": str(top_key),
                            "configuration": {str(top_key): value},
                        }
                    )
    return entries


def config_catalog(entries: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [
        {
            "config_ref": str(entry["config_ref"]),
            "scope": str(entry["scope"]),
            "owner_id": str(entry["owner_id"]),
            "owner_name": str(entry["owner_name"]),
            "top_level_key": str(entry["top_level_key"]),
        }
        for entry in entries
    ]


def build_user_prompt(
    graph: dict[str, Any],
    entries: list[dict[str, Any]],
    max_config_interpretations: int,
) -> str:
    return USER_PROMPT_TEMPLATE.format(
        topology_json=compact_json(graph),
        config_catalog_json=compact_json(config_catalog(entries)),
        max_config_interpretations=max_config_interpretations,
    )


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


def parse_json_object(text: str) -> dict[str, Any]:
    cleaned = strip_code_fence(text)
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        if start < 0:
            raise ValueError("模型回复中没有 JSON 对象") from None
        try:
            value, _ = json.JSONDecoder().raw_decode(cleaned, start)
        except json.JSONDecodeError as error:
            raise ValueError(f"模型 JSON 解析失败: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"模型回复顶层必须是对象，实际为 {type(value).__name__}")
    return value


def require_string(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} 必须是非空字符串")
    return value.strip()


def require_string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{field} 必须是字符串数组")
    return value


def require_object_list(data: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = data.get(key)
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"{key} 必须是对象数组")
    return value


def validate_analysis(
    data: dict[str, Any],
    available_config_refs: set[str],
    max_config_interpretations: int,
) -> dict[str, Any]:
    require_string(data, "site_summary")
    require_string(data, "plain_language_conclusion")
    for key in LIST_SECTIONS:
        if not isinstance(data.get(key), list):
            raise ValueError(f"{key} 必须是数组")

    for index, item in enumerate(require_object_list(data, "topology_layers")):
        require_string(item, "layer")
        require_string(item, "description")
        require_string_list(item.get("evidence_node_ids"), f"topology_layers[{index}].evidence_node_ids")
    for index, item in enumerate(require_object_list(data, "typical_paths")):
        require_string(item, "description")
        require_string_list(item.get("node_ids"), f"typical_paths[{index}].node_ids")
    for index, item in enumerate(require_object_list(data, "business_observations")):
        if require_string(item, "level") not in {"fact", "inference"}:
            raise ValueError(f"business_observations[{index}].level 非法")
        require_string(item, "title")
        require_string(item, "description")
        require_string_list(item.get("evidence"), f"business_observations[{index}].evidence")
    for index, item in enumerate(require_object_list(data, "risks")):
        if require_string(item, "severity") not in {"high", "medium", "low"}:
            raise ValueError(f"risks[{index}].severity 非法")
        require_string(item, "title")
        require_string(item, "description")
        require_string_list(item.get("affected_node_ids"), f"risks[{index}].affected_node_ids")
        require_string_list(item.get("evidence"), f"risks[{index}].evidence")
    for index, item in enumerate(require_object_list(data, "vlan_and_config")):
        require_string(item, "title")
        require_string(item, "description")
        require_string_list(item.get("evidence"), f"vlan_and_config[{index}].evidence")
    interpretations = require_object_list(data, "config_interpretations")
    if len(interpretations) > max_config_interpretations:
        raise ValueError(
            "config_interpretations 数量超过限制："
            f"{len(interpretations)} > {max_config_interpretations}"
        )
    seen_refs: set[str] = set()
    for index, item in enumerate(interpretations):
        config_ref = require_string(item, "config_ref")
        if config_ref not in available_config_refs:
            raise ValueError(
                f"config_interpretations[{index}].config_ref 不存在: {config_ref}"
            )
        if config_ref in seen_refs:
            raise ValueError(f"config_ref 重复: {config_ref}")
        seen_refs.add(config_ref)
        require_string(item, "title")
        require_string(item, "interpretation")
        require_string(item, "business_impact")
        if require_string(item, "certainty") not in {"fact", "inference"}:
            raise ValueError(f"config_interpretations[{index}].certainty 非法")
        require_string_list(
            item.get("unknowns"),
            f"config_interpretations[{index}].unknowns",
        )
    require_string_list(data.get("unknowns"), "unknowns")
    return data


def request_analysis(
    client: Any,
    args: argparse.Namespace,
    user_prompt: str,
    available_config_refs: set[str],
) -> tuple[dict[str, Any], str, int]:
    total_attempts = args.retries + 1
    last_error: Exception | None = None
    last_output = ""
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
            last_output = content
            analysis = validate_analysis(
                parse_json_object(content),
                available_config_refs,
                args.max_config_interpretations,
            )
            return analysis, content, attempt
        except Exception as error:  # noqa: BLE001 - 请求和格式错误均允许重试。
            last_error = error
            if attempt < total_attempts and args.retry_wait_seconds:
                time.sleep(args.retry_wait_seconds)
    assert last_error is not None
    failure = RuntimeError(
        f"{total_attempts} 次尝试后仍失败: {type(last_error).__name__}: {last_error}"
    )
    setattr(failure, "raw_model_output", last_output)
    raise failure from last_error


def graph_statistics(graph: dict[str, Any]) -> dict[str, int]:
    return {
        "node_count": len(graph.get("nodes")) if isinstance(graph.get("nodes"), list) else 0,
        "link_count": len(graph.get("links")) if isinstance(graph.get("links"), list) else 0,
        "device_group_count": len(graph.get("deviceGroups")) if isinstance(graph.get("deviceGroups"), list) else 0,
        "input_characters": len(compact_json(graph)),
    }


def resolve_config_explanations(
    entries: list[dict[str, Any]],
    analysis: dict[str, Any],
) -> list[dict[str, Any]]:
    entry_by_ref = {str(entry["config_ref"]): entry for entry in entries}
    resolved: list[dict[str, Any]] = []
    for interpretation in analysis.get("config_interpretations", []):
        config_ref = interpretation["config_ref"]
        entry = entry_by_ref[config_ref]
        resolved.append(
            {
                **entry,
                "title": interpretation["title"],
                "interpretation": interpretation["interpretation"],
                "business_impact": interpretation["business_impact"],
                "certainty": interpretation["certainty"],
                "unknowns": interpretation["unknowns"],
            }
        )
    return resolved


def write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def evidence(values: Any) -> str:
    if not isinstance(values, list) or not values:
        return '<span class="empty-evidence">未提供证据</span>'
    return '<div class="evidence">' + "".join(
        f"<code>{esc(value)}</code>" for value in values
    ) + "</div>"


def report_items(items: Any, kind: str) -> str:
    if not isinstance(items, list) or not items:
        return '<p class="empty">未发现可展示内容</p>'
    parts: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        title = item.get("title") or item.get("layer") or "分析项"
        description = item.get("description", "")
        badge = ""
        if kind == "observation":
            level = item.get("level", "fact")
            label = "明确事实" if level == "fact" else "合理推断"
            badge = f'<span class="badge {esc(level)}">{label}</span>'
        elif kind == "risk":
            severity = item.get("severity", "low")
            labels = {"high": "高风险", "medium": "中风险", "low": "低风险"}
            badge = f'<span class="badge {esc(severity)}">{labels.get(severity, severity)}</span>'
        values = item.get("evidence_node_ids")
        if values is None:
            values = item.get("evidence")
        if kind == "risk" and item.get("affected_node_ids"):
            values = list(values or []) + [
                f"受影响: {node_id}" for node_id in item["affected_node_ids"]
            ]
        parts.append(
            '<article class="item">'
            f'<div class="item-title">{badge}<strong>{esc(title)}</strong></div>'
            f'<p>{esc(description)}</p>{evidence(values)}</article>'
        )
    return "".join(parts) or '<p class="empty">未发现可展示内容</p>'


def paths_html(paths: Any) -> str:
    if not isinstance(paths, list) or not paths:
        return '<p class="empty">未发现可以可靠描述的典型路径</p>'
    parts: list[str] = []
    for item in paths:
        if not isinstance(item, dict):
            continue
        nodes = item.get("node_ids") if isinstance(item.get("node_ids"), list) else []
        chain = '<span class="arrow"> → </span>'.join(
            f"<code>{esc(node)}</code>" for node in nodes
        )
        parts.append(
            f'<article class="item"><strong>{esc(item.get("description", "典型路径"))}</strong>'
            f'<div class="path-chain">{chain}</div></article>'
        )
    return "".join(parts)


def config_explanations_html(items: Any) -> str:
    if not isinstance(items, list) or not items:
        return '<p class="empty">当前站点没有模型选中的代表性配置</p>'
    parts: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        certainty = item.get("certainty", "fact")
        certainty_label = "明确事实" if certainty == "fact" else "合理推断"
        owner = item.get("owner_name") or item.get("owner_id") or "未知对象"
        scope_label = "节点配置" if item.get("scope") == "node" else "设备组配置"
        raw_config = json.dumps(
            item.get("configuration"),
            ensure_ascii=False,
            indent=2,
        )
        unknowns = item.get("unknowns")
        unknown_html = (
            "".join(f"<li>{esc(value)}</li>" for value in unknowns)
            if isinstance(unknowns, list) and unknowns
            else "<li>模型未列出信息缺口</li>"
        )
        parts.append(
            f"""<article class="config-item">
<div class="config-header">
  <div><strong>{esc(item.get('title', item.get('top_level_key', '配置')))}</strong>
  <span>{esc(scope_label)} · {esc(owner)}</span></div>
  <span class="badge {esc(certainty)}">{certainty_label}</span>
</div>
<div class="config-ref"><code>{esc(item.get('config_ref', ''))}</code></div>
<div class="config-columns">
  <div class="config-source"><h3>原始配置</h3><pre>{esc(raw_config)}</pre></div>
  <div class="config-understanding">
    <h3>LLM 业务理解</h3>
    <p>{esc(item.get('interpretation', ''))}</p>
    <h4>可能影响</h4><p>{esc(item.get('business_impact', ''))}</p>
    <h4>信息边界</h4><ul>{unknown_html}</ul>
  </div>
</div></article>"""
        )
    return "".join(parts)


def report_html(result: dict[str, Any], source_path: Path) -> str:
    analysis = result.get("model-output")
    topology = result.get("topology-visualization")
    topology_html = ""
    if isinstance(topology, dict) and topology.get("status") is True:
        topology_file = Path(str(topology["html_file"])).name
        topology_html = f"""<section class="topology-section">
<div class="section-heading"><h2>交互式拓扑图</h2>
<a href="{quote(topology_file)}" target="_blank" rel="noopener">独立打开</a></div>
<iframe src="{quote(topology_file)}" title="交互式网络拓扑图" loading="lazy"></iframe>
</section>"""
    else:
        topology_error = (
            topology.get("error")
            if isinstance(topology, dict)
            else "未生成拓扑可视化"
        )
        topology_html = f"""<section class="topology-section">
<h2>交互式拓扑图</h2><p class="error-text">{esc(topology_error)}</p></section>"""

    if not isinstance(analysis, dict):
        error = result.get("error") or "没有可用分析结果"
        body = (
            topology_html
            + f'<section class="error-panel"><h2>LLM 分析失败</h2>'
            f'<pre>{esc(error)}</pre></section>'
        )
    else:
        unknowns = analysis.get("unknowns")
        unknown_html = (
            "".join(f"<li>{esc(item)}</li>" for item in unknowns)
            if isinstance(unknowns, list) and unknowns
            else "<li>模型未列出信息缺口</li>"
        )
        body = f"""
<section class="summary"><h2>站点概况</h2><p>{esc(analysis['site_summary'])}</p></section>
{topology_html}
<section><h2>网络层级</h2>{report_items(analysis['topology_layers'], 'layer')}</section>
<section><h2>典型上行路径</h2>{paths_html(analysis['typical_paths'])}</section>
<section><h2>业务理解</h2>{report_items(analysis['business_observations'], 'observation')}</section>
<section class="config-section"><h2>配置逐段解读</h2>{config_explanations_html(result.get('config-explanations'))}</section>
<section><h2>可靠性与影响风险</h2>{report_items(analysis['risks'], 'risk')}</section>
<section><h2>VLAN 与关键配置</h2>{report_items(analysis['vlan_and_config'], 'config')}</section>
<section><h2>信息不足</h2><ul>{unknown_html}</ul></section>
<section class="conclusion"><h2>通俗总结</h2><p>{esc(analysis['plain_language_conclusion'])}</p></section>
"""

    stats = result.get("graph_statistics") or {}
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>网络业务分析 · {esc(source_path.name)}</title>
<style>
:root{{--bg:#f4f6f8;--surface:#fff;--line:#d6dde4;--text:#17212b;--muted:#667482;--blue:#1769aa;--green:#247a45;--amber:#a45c00;--red:#b42318;--violet:#68439a}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:14px/1.65 system-ui,-apple-system,"Segoe UI",sans-serif}}
header{{padding:22px 26px;background:#17212b;color:#fff;border-bottom:3px solid #e0a100}}h1{{margin:0;font-size:22px;letter-spacing:0}}header p{{margin:5px 0 0;color:#c9d2dc;overflow-wrap:anywhere}}
.metrics{{display:grid;grid-template-columns:repeat(7,1fr);background:var(--line);gap:1px;border-bottom:1px solid var(--line)}}.metric{{padding:12px 16px;background:#fff}}.metric span{{display:block;color:var(--muted);font-size:12px}}.metric strong{{font-size:18px}}
main{{max-width:1280px;margin:auto;padding:20px;display:grid;grid-template-columns:1fr 1fr;gap:16px}}section{{background:var(--surface);border:1px solid var(--line);border-radius:6px;padding:17px}}section.summary,section.conclusion,section.error-panel,.topology-section,.config-section{{grid-column:1/-1}}h2{{margin:0 0 12px;font-size:17px}}h3{{margin:0 0 9px;font-size:14px}}h4{{margin:14px 0 4px;font-size:13px}}p{{margin:7px 0}}.item{{padding:11px 0;border-top:1px solid #e5e9ed}}.item:first-of-type{{border-top:0;padding-top:0}}.item-title{{display:flex;gap:8px;align-items:center}}.badge{{padding:1px 7px;border-radius:3px;font-size:12px;white-space:nowrap}}.fact{{background:#e1eff9;color:var(--blue)}}.inference{{background:#efe8f8;color:var(--violet)}}.high{{background:#fee4e2;color:var(--red)}}.medium{{background:#fff0d5;color:var(--amber)}}.low{{background:#e2f2e7;color:var(--green)}}
.evidence{{display:flex;flex-wrap:wrap;gap:5px;margin-top:8px}}code{{padding:2px 6px;background:#edf1f4;border:1px solid #d8dee5;border-radius:3px;font:12px ui-monospace,SFMono-Regular,Consolas,monospace;overflow-wrap:anywhere}}.path-chain{{margin-top:9px;line-height:2.2}}.arrow{{color:var(--muted)}}.empty,.empty-evidence{{color:var(--muted)}}ul{{padding-left:20px}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#111820;color:#e6edf3;padding:14px;border-radius:4px}}
.section-heading{{display:flex;align-items:center;justify-content:space-between;gap:12px}}.section-heading a{{color:var(--blue);font-weight:650;text-decoration:none}}iframe{{display:block;width:100%;height:720px;border:1px solid var(--line);background:#f7f8fa}}.error-text{{color:var(--red)}}
.config-item{{padding:16px 0;border-top:1px solid #dfe5ea}}.config-item:first-of-type{{border-top:0;padding-top:0}}.config-header{{display:flex;justify-content:space-between;gap:12px;align-items:start}}.config-header div>span{{display:block;color:var(--muted);font-size:12px;margin-top:2px}}.config-ref{{margin:8px 0}}.config-columns{{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:14px}}.config-source,.config-understanding{{min-width:0;padding:13px;background:#f7f9fa;border:1px solid #dfe5ea;border-radius:4px}}.config-source pre{{max-height:420px;overflow:auto}}
@media(max-width:800px){{.metrics{{grid-template-columns:repeat(2,1fr)}}main{{grid-template-columns:1fr}}section,section.summary,section.conclusion,.topology-section,.config-section{{grid-column:1}}.config-columns{{grid-template-columns:1fr}}iframe{{height:560px}}}}
</style></head><body>
<header><h1>通信网络业务分析</h1><p>{esc(source_path)}</p></header>
<div class="metrics">
<div class="metric"><span>LLM 分析</span><strong>{'成功' if result.get('status') else '失败'}</strong></div>
<div class="metric"><span>拓扑图</span><strong>{'成功' if isinstance(topology, dict) and topology.get('status') else '失败'}</strong></div>
<div class="metric"><span>节点数</span><strong>{esc(stats.get('node_count', 0))}</strong></div>
<div class="metric"><span>链路数</span><strong>{esc(stats.get('link_count', 0))}</strong></div>
<div class="metric"><span>配置段</span><strong>{esc(result.get('config_count', 0))}</strong></div>
<div class="metric"><span>已解读配置</span><strong>{len(result.get('config-explanations', []))}</strong></div>
<div class="metric"><span>模型</span><strong>{esc(result.get('model', ''))}</strong></div>
</div><main>{body}</main></body></html>"""


def html_output_path(output_root: Path, split: str, relative_path: Path) -> Path:
    return output_root / split / relative_path.with_suffix(".html")


def topology_output_path(
    output_root: Path,
    split: str,
    relative_path: Path,
) -> Path:
    return output_root / split / relative_path.with_name(
        f"{relative_path.stem}.topology.html"
    )


def generate_topology_page(
    dataset_root: Path,
    output_root: Path,
    split: str,
    source_path: Path,
    relative_path: Path,
) -> dict[str, Any]:
    output_path = topology_output_path(output_root, split, relative_path)
    try:
        graph = parse_graph(dataset_root, split, source_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(graph_page(graph), encoding="utf-8")
        return {
            "status": True,
            "html_file": str(output_path.relative_to(output_root)),
            "node_count": len(graph.nodes),
            "edge_count": len(graph.edges),
            "component_count": graph.component_count,
            "isolated_count": graph.isolated_count,
            "error": None,
        }
    except Exception as error:  # noqa: BLE001 - 可视化失败不阻断 LLM 分析。
        return {
            "status": False,
            "html_file": str(output_path.relative_to(output_root)),
            "node_count": 0,
            "edge_count": 0,
            "component_count": 0,
            "isolated_count": 0,
            "error": f"{type(error).__name__}: {error}",
        }


def successful_result(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return bool(
        isinstance(data, dict)
        and data.get("report_version") == REPORT_VERSION
        and data.get("status") is True
        and isinstance(data.get("model-output"), dict)
    )


def process_file(
    client: Any,
    args: argparse.Namespace,
    dataset_root: Path,
    output_root: Path,
    split: str,
    source_path: Path,
) -> dict[str, Any]:
    relative_path = source_path.relative_to(dataset_root / split)
    result_path = output_root / split / relative_path
    html_path = html_output_path(output_root, split, relative_path)
    if args.resume and successful_result(result_path):
        result = json.loads(result_path.read_text(encoding="utf-8"))
        topology_path = topology_output_path(output_root, split, relative_path)
        if not topology_path.is_file():
            result["topology-visualization"] = generate_topology_page(
                dataset_root,
                output_root,
                split,
                source_path,
                relative_path,
            )
            write_json_atomic(result_path, result)
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.write_text(report_html(result, source_path), encoding="utf-8")
        return {"status": None, "skipped": True, "result": result}

    started = time.monotonic()
    topology = generate_topology_page(
        dataset_root,
        output_root,
        split,
        source_path,
        relative_path,
    )
    graph: dict[str, Any] | None = None
    entries: list[dict[str, Any]] = []
    raw_output = ""
    attempts = 0
    try:
        loaded = json.loads(source_path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError(f"输入顶层必须是对象，实际为 {type(loaded).__name__}")
        graph = loaded
        entries = extract_config_entries(graph)
        analysis, raw_output, attempts = request_analysis(
            client,
            args,
            build_user_prompt(
                graph,
                entries,
                args.max_config_interpretations,
            ),
            {str(entry["config_ref"]) for entry in entries},
        )
        result: dict[str, Any] = {
            "report_version": REPORT_VERSION,
            "source_file": str(relative_path),
            "split": split,
            "status": True,
            "model": args.model,
            "request_attempts": attempts,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "graph_statistics": graph_statistics(graph),
            "topology-visualization": topology,
            "config_count": len(entries),
            "config-explanations": resolve_config_explanations(entries, analysis),
            "model-output": analysis,
            "error_stage": None,
            "error": None,
        }
    except Exception as error:  # noqa: BLE001 - 单样本失败必须落盘并继续。
        raw_output = raw_output or str(getattr(error, "raw_model_output", ""))
        stage = "input" if graph is None else "request_or_model_output"
        result = {
            "report_version": REPORT_VERSION,
            "source_file": str(relative_path),
            "split": split,
            "status": False,
            "model": args.model,
            "request_attempts": attempts or args.retries + 1,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "graph_statistics": graph_statistics(graph) if graph is not None else {},
            "topology-visualization": topology,
            "config_count": len(entries),
            "config-explanations": [],
            "model-output": None,
            "raw_model_output": raw_output or None,
            "error_stage": stage,
            "error": f"{type(error).__name__}: {error}",
        }

    write_json_atomic(result_path, result)
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(report_html(result, source_path), encoding="utf-8")
    return {"status": result["status"], "skipped": False, "result": result}


def write_failures(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["split", "source_file", "component", "error_stage", "error"]
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows({key: row.get(key) for key in fields} for row in rows)


def index_html(output_root: Path, records: list[dict[str, Any]]) -> str:
    rows: list[str] = []
    for record in records:
        result = record["result"]
        relative_json = Path(result["split"]) / result["source_file"]
        relative_html = relative_json.with_suffix(".html")
        analysis = result.get("model-output") or {}
        risk_count = len(analysis.get("risks", [])) if isinstance(analysis, dict) else 0
        topology = result.get("topology-visualization") or {}
        interpreted_count = len(result.get("config-explanations", []))
        rows.append(f"""<tr data-search="{esc(str(relative_json).lower())}">
<td>{esc(relative_json)}</td><td>{'成功' if result.get('status') else '失败'}</td>
<td>{'成功' if topology.get('status') else '失败'}</td>
<td>{esc(result.get('graph_statistics', {}).get('node_count', 0))}</td>
<td>{esc(result.get('graph_statistics', {}).get('link_count', 0))}</td>
<td>{esc(result.get('config_count', 0))}</td><td>{interpreted_count}</td>
<td>{risk_count}</td><td>{esc(result.get('elapsed_seconds', 0))}</td>
<td><a href="{quote(str(relative_html))}">查看报告</a></td></tr>""")
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>通信网络业务分析总览</title>
<style>*{{box-sizing:border-box}}body{{margin:0;background:#f4f6f8;color:#17212b;font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}}header{{padding:22px 26px;background:#17212b;color:#fff;border-bottom:3px solid #e0a100}}h1{{margin:0;font-size:22px}}header p{{margin:5px 0 0;color:#c9d2dc}}main{{padding:18px}}input{{width:min(520px,100%);padding:9px 11px;margin-bottom:12px;border:1px solid #aeb8c3;border-radius:4px}}.table{{overflow:auto;border:1px solid #d6dde4;background:#fff}}table{{width:100%;border-collapse:collapse}}th,td{{padding:10px 12px;border-bottom:1px solid #e3e7eb;text-align:left}}th{{background:#edf1f4;color:#45515f}}tr:hover{{background:#f1f7fb}}a{{color:#1769aa;font-weight:650;text-decoration:none}}</style></head>
<body><header><h1>通信网络业务分析总览</h1><p>{esc(output_root)}</p></header><main>
<input id="search" type="search" placeholder="搜索划分或文件名"><div class="table"><table><thead><tr>
<th>文件</th><th>LLM 分析</th><th>拓扑图</th><th>节点</th><th>链路</th>
<th>配置段</th><th>已解读</th><th>风险项</th><th>耗时（秒）</th><th>报告</th>
</tr></thead><tbody>{''.join(rows)}</tbody></table></div></main>
<script>const q=document.getElementById('search'),rows=[...document.querySelectorAll('tbody tr')];q.addEventListener('input',()=>{{const v=q.value.trim().toLowerCase();rows.forEach(r=>r.hidden=v&&!r.dataset.search.includes(v))}});</script>
</body></html>"""


def run(args: argparse.Namespace) -> None:
    dataset_root = args.dataset_root.resolve()
    output_root = args.output_root.resolve()
    items = collect_files(dataset_root, args.split)
    if args.limit is not None:
        items = items[: args.limit]
    if not items:
        raise FileNotFoundError(f"没有找到待分析 JSON: {dataset_root}")

    OpenAI = import_openai()
    client = OpenAI(
        base_url=args.base_url,
        api_key=args.api_key,
        timeout=args.request_timeout,
    )
    records: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    succeeded = failed = skipped = 0
    topology_succeeded = topology_failed = 0
    total_configs = interpreted_configs = 0
    started = time.monotonic()

    for index, (split, source_path) in enumerate(items, start=1):
        record = process_file(
            client,
            args,
            dataset_root,
            output_root,
            split,
            source_path,
        )
        records.append(record)
        result = record["result"]
        if record["skipped"]:
            skipped += 1
        elif record["status"]:
            succeeded += 1
        else:
            failed += 1
            failures.append(
                {
                    **result,
                    "component": "llm-analysis",
                }
            )

        topology = result.get("topology-visualization")
        if isinstance(topology, dict) and topology.get("status") is True:
            topology_succeeded += 1
        else:
            topology_failed += 1
            failures.append(
                {
                    "split": result.get("split"),
                    "source_file": result.get("source_file"),
                    "component": "topology-visualization",
                    "error_stage": "topology-render",
                    "error": (
                        topology.get("error")
                        if isinstance(topology, dict)
                        else "missing topology result"
                    ),
                }
            )
        total_configs += int(result.get("config_count", 0))
        interpreted_configs += len(result.get("config-explanations", []))

        if args.progress_interval and (
            index % args.progress_interval == 0 or index == len(items)
        ):
            elapsed = max(time.monotonic() - started, 0.001)
            speed = index / elapsed
            eta = (len(items) - index) / speed if speed else 0.0
            print(
                f"进度 {index}/{len(items)}，成功 {succeeded}，失败 {failed}，"
                f"跳过 {skipped}，预计剩余 {eta:.1f} 秒",
                flush=True,
            )
        if args.wait_seconds:
            time.sleep(args.wait_seconds)

    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / INDEX_FILE).write_text(
        index_html(output_root, records),
        encoding="utf-8",
    )
    write_failures(output_root / FAILURE_FILE, failures)
    elapsed = time.monotonic() - started
    summary = {
        "dataset_root": str(dataset_root),
        "output_root": str(output_root),
        "base_url": args.base_url,
        "model": args.model,
        "split": args.split,
        "context_mode": "complete_original_json_without_truncation",
        "thinking_enabled": args.enable_thinking,
        "max_config_interpretations": args.max_config_interpretations,
        "input_files": len(items),
        "succeeded_files": succeeded,
        "failed_files": failed,
        "skipped_files": skipped,
        "topology_succeeded_files": topology_succeeded,
        "topology_failed_files": topology_failed,
        "total_config_segments": total_configs,
        "interpreted_config_segments": interpreted_configs,
        "elapsed_seconds": round(elapsed, 3),
    }
    write_json_atomic(output_root / SUMMARY_FILE, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"HTML 总览: {output_root / INDEX_FILE}")


if __name__ == "__main__":
    run(parse_args())
