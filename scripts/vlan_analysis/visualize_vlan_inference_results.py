#!/usr/bin/env python3
"""将 VLAN 约束路径推理结果生成为可交互的静态 HTML。"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import re
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional


DEFAULT_RESULT_PATH = Path("vllm-results/vlan_constrained_shortest_path")
DEFAULT_OUTPUT_ROOT = Path("vlan-inference-visualizations")
DEFAULT_SPLIT = "all"
DEFAULT_MAX_RANGE_SIZE = 4096
DEFAULT_PROGRESS_INTERVAL = 50
RANGE_PATTERN = re.compile(r"^(\d+)\s*-\s*(\d+)$")
INTEGER_PATTERN = re.compile(r"^\d+$")
VlanSupport = Optional[frozenset[int]]  # None 表示 all。


@dataclass(frozen=True)
class PageRecord:
    source_file: str
    split: str
    output_file: str
    model_success: bool
    vlan_id: Optional[int]
    answer_length: Optional[int]
    prediction_length: Optional[int]
    exact_match: bool
    node_count: int
    edge_count: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "result_path",
        nargs="?",
        type=Path,
        default=DEFAULT_RESULT_PATH,
        help="单个推理结果 JSON 或结果根目录，默认: %(default)s",
    )
    parser.add_argument(
        "-o",
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="HTML 输出目录，默认: %(default)s",
    )
    parser.add_argument(
        "--split",
        choices=("train", "val", "all"),
        default=DEFAULT_SPLIT,
        help="目录输入时处理的数据划分，默认: %(default)s",
    )
    parser.add_argument(
        "--max-range-size",
        type=int,
        default=DEFAULT_MAX_RANGE_SIZE,
        help="VLAN 连续范围允许展开的最大数量，默认: %(default)s",
    )
    parser.add_argument(
        "--progress-interval",
        type=int,
        default=DEFAULT_PROGRESS_INTERVAL,
        help="每处理 N 个文件打印进度，0 表示关闭，默认: %(default)s",
    )
    args = parser.parse_args()
    if args.max_range_size <= 0:
        parser.error("--max-range-size 必须大于 0")
    if args.progress_interval < 0:
        parser.error("--progress-interval 不能小于 0")
    return args


def scalar_text(value: Any) -> Optional[str]:
    if value is None or isinstance(value, (dict, list, bool)):
        return None
    text = str(value).strip()
    return text or None


def object_items(value: Any) -> Iterable[tuple[int, dict[str, Any]]]:
    if isinstance(value, dict):
        yield 0, value
    elif isinstance(value, list):
        for index, item in enumerate(value):
            if isinstance(item, dict):
                yield index, item


def node_device(node: dict[str, Any]) -> dict[str, Any]:
    value = node.get("devices")
    if not isinstance(value, dict):
        value = node.get("device")
    return value if isinstance(value, dict) else {}


def collect_interfaces(node: dict[str, Any]) -> list[dict[str, Any]]:
    """保留接口原始配置及其所在位置，便于页面定位配置来源。"""
    records: list[dict[str, Any]] = []
    for field in ("configs", "config"):
        for config_index, config in object_items(node.get(field)):
            for business_index, business in object_items(
                config.get("lsw-interfaces-business")
            ):
                for interface_index, interface in object_items(
                    business.get("lsw-interface")
                ):
                    records.append(
                        {
                            "name": scalar_text(interface.get("interface-name")),
                            "allowThroughVlan": interface.get("allow-through-vlan"),
                            "location": (
                                f"{field}[{config_index}].lsw-interfaces-business"
                                f"[{business_index}].lsw-interface[{interface_index}]"
                            ),
                            "config": interface,
                        }
                    )
    return records


def parse_vlan_value(
    value: Any, max_range_size: int
) -> tuple[VlanSupport, list[str]]:
    vlan_ids: set[int] = set()
    errors: list[str] = []
    contains_all = False

    def visit(item: Any) -> None:
        nonlocal contains_all
        if item is None or isinstance(item, bool):
            errors.append(f"unsupported-value:{item!r}")
            return
        if isinstance(item, int):
            vlan_ids.add(item)
            return
        if isinstance(item, float):
            if item.is_integer():
                vlan_ids.add(int(item))
            else:
                errors.append(f"non-integer-number:{item}")
            return
        if isinstance(item, list):
            if not item:
                errors.append("empty-list")
            for child in item:
                visit(child)
            return
        if not isinstance(item, str):
            errors.append(f"unsupported-type:{type(item).__name__}")
            return
        tokens = [token.strip() for token in re.split(r"[,，]", item) if token.strip()]
        if not tokens:
            errors.append("empty-string")
        for token in tokens:
            if token.lower() == "all":
                contains_all = True
            elif INTEGER_PATTERN.fullmatch(token):
                vlan_ids.add(int(token))
            else:
                match = RANGE_PATTERN.fullmatch(token)
                if match is None:
                    errors.append(f"invalid-token:{token}")
                    continue
                start, end = int(match.group(1)), int(match.group(2))
                if start > end:
                    errors.append(f"descending-range:{token}")
                elif end - start + 1 > max_range_size:
                    errors.append(f"range-too-large:{token}")
                else:
                    vlan_ids.update(range(start, end + 1))

    visit(value)
    return (None if contains_all else frozenset(vlan_ids)), errors


def support_text(support: VlanSupport) -> str:
    if support is None:
        return "all"
    values = sorted(support)
    if len(values) <= 30:
        return ", ".join(str(value) for value in values) or "<empty>"
    return ", ".join(str(value) for value in values[:30]) + f" ...（共 {len(values)} 个）"


def normalize_paths(value: Any) -> list[list[str]]:
    if not isinstance(value, dict) or not isinstance(value.get("paths"), list):
        return []
    paths: list[list[str]] = []
    for path in value["paths"]:
        if not isinstance(path, list) or not path:
            continue
        normalized: list[str] = []
        valid = True
        for node_id in path:
            text = scalar_text(node_id)
            if text is None:
                valid = False
                break
            normalized.append(text)
        if valid:
            paths.append(normalized)
    return paths


def path_edges(paths: list[list[str]]) -> set[tuple[str, str]]:
    return {
        tuple(sorted((left, right)))
        for path in paths
        for left, right in zip(path, path[1:])
    }


def result_exact_match(answer: Any, prediction: Any) -> bool:
    if not isinstance(answer, dict) or not isinstance(prediction, dict):
        return False
    answer_paths = {tuple(path) for path in normalize_paths(answer)}
    prediction_paths = {tuple(path) for path in normalize_paths(prediction)}
    return (
        answer.get("vlan_id") == prediction.get("vlan_id")
        and answer.get("path_length") == prediction.get("path_length")
        and answer_paths == prediction_paths
    )


def initial_positions(
    node_ids: list[str], adjacency: dict[str, set[str]], source_id: Optional[str]
) -> tuple[dict[str, tuple[float, float]], int, int]:
    """以任务源节点为起点分层，无法到达的分量依次放在右侧。"""
    layers: dict[int, list[str]] = defaultdict(list)
    distances: dict[str, int] = {}
    if source_id in adjacency:
        distances[source_id] = 0
        queue = deque([source_id])
        while queue:
            node_id = queue.popleft()
            for neighbor in sorted(adjacency[node_id]):
                if neighbor not in distances:
                    distances[neighbor] = distances[node_id] + 1
                    queue.append(neighbor)
    for node_id in node_ids:
        if node_id in distances:
            layers[distances[node_id]].append(node_id)
    next_layer = max(layers, default=-1) + 1
    remaining = set(node_ids) - set(distances)
    while remaining:
        start = min(remaining)
        component: list[str] = []
        queue = deque([start])
        remaining.remove(start)
        while queue:
            node_id = queue.popleft()
            component.append(node_id)
            for neighbor in sorted(adjacency.get(node_id, set())):
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    queue.append(neighbor)
        layers[next_layer].extend(sorted(component))
        next_layer += 1

    positions: dict[str, tuple[float, float]] = {}
    max_rows = 1
    for layer, values in sorted(layers.items()):
        ordered = sorted(values)
        max_rows = max(max_rows, len(ordered))
        for index, node_id in enumerate(ordered):
            positions[node_id] = (130 + layer * 310, 100 + index * 108)
    width = max(900, (max(layers, default=0) + 1) * 310 + 220)
    height = max(640, max_rows * 108 + 180)
    return positions, width, height


def json_for_script(value: Any) -> str:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        .replace("<", "\\u003c")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def parse_result(
    path: Path, source_label: str, max_range_size: int
) -> tuple[dict[str, Any], PageRecord]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("顶层 JSON 不是对象")
    raw_nodes = document.get("nodes")
    raw_links = document.get("links")
    if not isinstance(raw_nodes, list) or not isinstance(raw_links, list):
        raise ValueError("缺少 nodes 或 links 数组")

    source_id = scalar_text(document.get("task_source_node_id"))
    target_id = scalar_text(document.get("task_target_node_id"))
    vlan_value = document.get("task_vlan_id")
    vlan_id = vlan_value if isinstance(vlan_value, int) and not isinstance(vlan_value, bool) else None
    answer = document.get("task_answer")
    prediction = document.get("model-output")
    answer_paths = normalize_paths(answer)
    prediction_paths = normalize_paths(prediction)
    answer_edges = path_edges(answer_paths)
    prediction_edges = path_edges(prediction_paths)

    nodes_by_id: dict[str, dict[str, Any]] = {}
    duplicate_ids: set[str] = set()
    for raw_node in raw_nodes:
        if not isinstance(raw_node, dict):
            continue
        node_id = scalar_text(raw_node.get("id"))
        if node_id is None:
            continue
        if node_id in nodes_by_id:
            duplicate_ids.add(node_id)
            continue
        device = node_device(raw_node)
        if (scalar_text(device.get("TYPE")) or "").upper() != "LSW":
            continue
        topology = raw_node.get("topologyNode")
        nodes_by_id[node_id] = {
            "id": node_id,
            "name": scalar_text(device.get("NAME")) or "<missing>",
            "manufacturer": scalar_text(device.get("MANUFACTURER")) or "<missing>",
            "model": scalar_text(device.get("MODEL")) or "<missing>",
            "type": scalar_text(device.get("TYPE")) or "<missing>",
            "role": (
                scalar_text(topology.get("DEVICEROLE"))
                if isinstance(topology, dict)
                else None
            ) or "<missing>",
            "interfaces": collect_interfaces(raw_node),
        }

    adjacency = {node_id: set() for node_id in nodes_by_id}
    edges: list[dict[str, Any]] = []
    issues: Counter[str] = Counter()
    if duplicate_ids:
        issues["duplicate-node-id"] = len(duplicate_ids)
    for link_index, raw_link in enumerate(raw_links):
        if not isinstance(raw_link, dict):
            issues["invalid-link"] += 1
            continue
        left_id = scalar_text(raw_link.get("source"))
        right_id = scalar_text(raw_link.get("target"))
        if left_id not in nodes_by_id or right_id not in nodes_by_id:
            continue
        if left_id == right_id:
            issues["self-loop"] += 1
            continue
        detail = raw_link.get("link")
        if not isinstance(detail, dict):
            detail = {}
        left_port = scalar_text(detail.get("LEFTPORT"))
        right_port = scalar_text(detail.get("RIGHTPORT"))
        left_matches = [
            item for item in nodes_by_id[left_id]["interfaces"] if item["name"] == left_port
        ]
        right_matches = [
            item for item in nodes_by_id[right_id]["interfaces"] if item["name"] == right_port
        ]

        def endpoint_info(matches: list[dict[str, Any]], port: Optional[str]) -> dict[str, Any]:
            if port is None:
                return {"status": "missing-port", "matches": [], "support": None, "errors": ["missing-port"]}
            if not matches:
                return {"status": "not-found", "matches": [], "support": None, "errors": ["interface-not-found"]}
            if len(matches) > 1:
                return {"status": "multiple", "matches": matches, "support": None, "errors": ["multiple-interface-matches"]}
            interface = matches[0]
            if "allow-through-vlan" not in interface["config"]:
                return {"status": "missing-vlan", "matches": matches, "support": None, "errors": ["allow-through-vlan-missing"]}
            support, errors = parse_vlan_value(interface["config"]["allow-through-vlan"], max_range_size)
            return {
                "status": "parse-error" if errors else "matched",
                "matches": matches,
                "support": support,
                "errors": errors,
            }

        left = endpoint_info(left_matches, left_port)
        right = endpoint_info(right_matches, right_port)
        pair = tuple(sorted((left_id, right_id)))
        vlan_status = "unknown"
        common_text = "无法确定"
        if left["status"] == right["status"] == "matched":
            left_support, right_support = left["support"], right["support"]
            if left_support is None:
                common = right_support
            elif right_support is None:
                common = left_support
            else:
                common = left_support & right_support
            common_text = support_text(common)
            vlan_status = "pass" if vlan_id is not None and (common is None or vlan_id in common) else "blocked"
        issues.update(error for error in left["errors"] + right["errors"])
        # support 是仅供 Python 计算使用的 frozenset；页面使用原始接口配置展示。
        left_payload = {key: value for key, value in left.items() if key != "support"}
        right_payload = {key: value for key, value in right.items() if key != "support"}
        adjacency[left_id].add(right_id)
        adjacency[right_id].add(left_id)
        edges.append(
            {
                "index": link_index,
                "source": left_id,
                "target": right_id,
                "leftPort": left_port or "<missing>",
                "rightPort": right_port or "<missing>",
                "label": scalar_text(detail.get("LABEL")) or "<missing>",
                "className": scalar_text(detail.get("CLASSNAME")) or "<missing>",
                "sourceEndpoint": left_payload,
                "targetEndpoint": right_payload,
                "commonSupport": common_text,
                "vlanStatus": vlan_status,
                "inAnswer": pair in answer_edges,
                "inPrediction": pair in prediction_edges,
            }
        )

    positions, canvas_width, canvas_height = initial_positions(
        sorted(nodes_by_id), adjacency, source_id
    )
    nodes = []
    for node_id, node in sorted(nodes_by_id.items()):
        node["x"], node["y"] = positions[node_id]
        node["degree"] = len(adjacency[node_id])
        node["isSource"] = node_id == source_id
        node["isTarget"] = node_id == target_id
        nodes.append(node)

    run_info = document.get("vllm-run")
    if not isinstance(run_info, dict):
        run_info = document.get("opencode-run")
    model_success = bool(
        isinstance(prediction, dict)
        and (not isinstance(run_info, dict) or run_info.get("success", True))
    )
    answer_length = answer.get("path_length") if isinstance(answer, dict) else None
    prediction_length = prediction.get("path_length") if isinstance(prediction, dict) else None
    payload = {
        "sourceFile": source_label,
        "task": {
            "source": source_id,
            "target": target_id,
            "vlanId": vlan_id,
            "question": document.get("task_question"),
        },
        "answer": answer,
        "prediction": prediction,
        "answerPaths": answer_paths,
        "predictionPaths": prediction_paths,
        "modelSuccess": model_success,
        "modelError": run_info.get("error") if isinstance(run_info, dict) else None,
        "exactMatch": result_exact_match(answer, prediction),
        "nodes": nodes,
        "edges": edges,
        "issues": dict(sorted(issues.items())),
        "canvas": {"width": canvas_width, "height": canvas_height},
    }
    record = PageRecord(
        source_file=source_label,
        split=source_label.split("/", 1)[0] if "/" in source_label else "single",
        output_file="",
        model_success=model_success,
        vlan_id=vlan_id,
        answer_length=answer_length if isinstance(answer_length, int) else None,
        prediction_length=prediction_length if isinstance(prediction_length, int) else None,
        exact_match=payload["exactMatch"],
        node_count=len(nodes),
        edge_count=len(edges),
    )
    return payload, record


def page_html(payload: dict[str, Any]) -> str:
    title = html.escape(payload["sourceFile"])
    return f'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} - VLAN 路径推理可视化</title>
<style>
:root {{ color-scheme: light; font-family: Inter,"Noto Sans SC",Arial,sans-serif; --border:#d8dee6; --muted:#627080; --bg:#f5f7f9; }}
* {{ box-sizing:border-box; }}
html,body {{ width:100%;height:100%;margin:0;color:#17212b;background:var(--bg); }}
body {{ display:grid;grid-template-rows:auto auto minmax(0,1fr);overflow:hidden; }}
header {{ display:flex;align-items:center;gap:14px;padding:10px 16px;background:#fff;border-bottom:1px solid var(--border); }}
h1 {{ min-width:0;margin:0;font-size:16px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap; }}
.task {{ margin-left:auto;display:flex;gap:12px;font-size:12px;color:var(--muted);white-space:nowrap; }}
.pill {{ padding:3px 7px;border:1px solid var(--border);border-radius:4px;background:#f8fafb; }}
.pill.ok {{ border-color:#86c99a;color:#176b32;background:#effaf2; }} .pill.bad {{ border-color:#e5a1a1;color:#9b2222;background:#fff4f4; }}
.toolbar {{ display:flex;align-items:center;gap:8px;padding:8px 12px;background:#fff;border-bottom:1px solid var(--border);overflow-x:auto; }}
button,input {{ height:32px;border:1px solid #b7c0ca;background:#fff;color:#17212b;font-size:12px; }}
button {{ padding:0 10px;cursor:pointer; }} button:hover,button.active {{ background:#e9eef4;border-color:#7e8d9c; }}
input {{ width:200px;padding:0 9px; }} .spacer {{ flex:1; }}
.app {{ min-height:0;display:grid;grid-template-columns:minmax(0,1fr) 410px; }}
.viewport {{ position:relative;min-width:0;min-height:0;overflow:auto;background:#eef1f4; }}
#graph {{ display:block;transform-origin:0 0;background-image:radial-gradient(#ccd3da 0.7px,transparent 0.7px);background-size:20px 20px; }}
.edge {{ stroke:#9ca7b2;stroke-width:2;cursor:pointer;vector-effect:non-scaling-stroke; }}
.edge:hover,.edge.selected {{ stroke:#151b22!important;stroke-width:5!important; }}
.edge.pass {{ stroke:#6ea87a; }} .edge.blocked {{ stroke:#d06a6a;stroke-dasharray:7 4; }} .edge.unknown {{ stroke:#d39a45;stroke-dasharray:3 4; }}
.edge.answer {{ stroke:#279156;stroke-width:5; }} .edge.prediction {{ stroke:#2775c5;stroke-width:5; }} .edge.both {{ stroke:#008b8b;stroke-width:6; }}
.edge.prediction.invalid {{ stroke:#c0392b;stroke-dasharray:8 4; }}
.edge-label {{ font-size:10px;fill:#344150;pointer-events:none;text-anchor:middle;dominant-baseline:middle; }}
.edge-label-bg {{ fill:#fff;stroke:#c7d0d9;stroke-width:1;rx:3;pointer-events:none;vector-effect:non-scaling-stroke; }}
.node {{ cursor:pointer; }} .node circle {{ fill:#fff;stroke:#697887;stroke-width:2;vector-effect:non-scaling-stroke; }}
.node.source circle {{ fill:#ddf4e4;stroke:#198044;stroke-width:4; }} .node.target circle {{ fill:#fde3e3;stroke:#b83232;stroke-width:4; }}
.node.selected circle,.node:hover circle {{ stroke:#111827;stroke-width:5; }}
.node text {{ font-size:11px;fill:#17212b;text-anchor:middle;pointer-events:none; }}
.node-label-bg {{ fill:#fff;stroke:#c7d0d9;stroke-width:1;rx:3;pointer-events:none;vector-effect:non-scaling-stroke; }}
aside {{ min-height:0;overflow:auto;background:#fff;border-left:1px solid var(--border); }}
.panel {{ padding:13px 15px;border-bottom:1px solid var(--border); }} .panel h2 {{ margin:0 0 9px;font-size:13px; }}
.kv {{ display:grid;grid-template-columns:112px minmax(0,1fr);gap:5px 9px;font-size:12px;line-height:1.55; }} .kv b {{ color:var(--muted);font-weight:600; }}
.status-pass {{ color:#16733a; }} .status-blocked {{ color:#b42323; }} .status-unknown {{ color:#a26000; }}
.path {{ margin:5px 0;padding:7px 8px;background:#f6f8fa;border-left:3px solid #8794a3;font:11px/1.5 ui-monospace,SFMono-Regular,Consolas,monospace;overflow-wrap:anywhere; }}
.path.answer {{ border-color:#279156; }} .path.prediction {{ border-color:#2775c5; }}
details {{ margin-top:7px; }} summary {{ cursor:pointer;font-size:12px;color:#415063; }}
pre {{ margin:6px 0 0;padding:8px;max-height:260px;overflow:auto;background:#f3f5f7;font:11px/1.5 ui-monospace,SFMono-Regular,Consolas,monospace;white-space:pre-wrap;overflow-wrap:anywhere; }}
.interface {{ margin:8px 0;padding:8px;border:1px solid var(--border);border-radius:4px; }} .interface.focus {{ border-color:#d28a22;background:#fff9ec; }}
.legend {{ display:flex;flex-wrap:wrap;gap:8px 13px;font-size:11px;color:var(--muted); }} .legend i {{ display:inline-block;width:22px;border-top:4px solid;margin-right:5px;vertical-align:middle; }}
@media(max-width:900px) {{ .app {{ grid-template-columns:minmax(0,1fr) 330px; }} .task span:nth-child(n+4) {{ display:none; }} }}
</style>
</head>
<body>
<header><h1 title="{title}">{title}</h1><div class="task" id="taskStats"></div></header>
<div class="toolbar">
  <button class="mode active" data-mode="compare">答案 / 模型</button><button class="mode" data-mode="answer">仅答案</button>
  <button class="mode" data-mode="prediction">仅模型</button><button class="mode" data-mode="vlan">VLAN 可通行</button><button class="mode" data-mode="all">全部链路</button>
  <input id="search" type="search" placeholder="搜索节点 ID / NAME"><button id="find">定位</button>
  <span class="spacer"></span><button id="zoomOut" title="缩小">−</button><button id="fit">适应</button><button id="zoomIn" title="放大">+</button>
</div>
<div class="app"><main class="viewport" id="viewport"><svg id="graph" role="img" aria-label="VLAN 约束路径拓扑图"></svg></main><aside id="sidebar"></aside></div>
<script id="payload" type="application/json">{json_for_script(payload)}</script>
<script>
"use strict";
const data=JSON.parse(document.getElementById("payload").textContent),NS="http://www.w3.org/2000/svg";
const svg=document.getElementById("graph"),viewport=document.getElementById("viewport"),sidebar=document.getElementById("sidebar");
const nodes=new Map(data.nodes.map(n=>[n.id,n])); let mode="compare",scale=1,selected=null,focusPort=null;
const esc=v=>{{const d=document.createElement("div");d.textContent=v==null?"":String(v);return d.innerHTML;}};
const pretty=v=>JSON.stringify(v,null,2); const statusText={{pass:"允许",blocked:"阻断",unknown:"未知"}};
document.getElementById("taskStats").innerHTML=`<span class="pill">VLAN ${{esc(data.task.vlanId)}}</span><span class="pill">${{esc(data.task.source)}} → ${{esc(data.task.target)}}</span><span class="pill ${{data.modelSuccess?'ok':'bad'}}">模型${{data.modelSuccess?'成功':'失败'}}</span><span class="pill ${{data.exactMatch?'ok':'bad'}}">${{data.exactMatch?'完全正确':'存在差异'}}</span>`;
function edgeClass(edge){{let cls=`edge ${{edge.vlanStatus}}`;if(edge.inAnswer&&edge.inPrediction)cls+=" both";else if(edge.inAnswer)cls+=" answer";else if(edge.inPrediction)cls+=` prediction ${{edge.vlanStatus==='pass'?'':'invalid'}}`;return cls;}}
function edgeVisible(edge){{if(mode==='answer')return edge.inAnswer;if(mode==='prediction')return edge.inPrediction;if(mode==='vlan')return edge.vlanStatus==='pass';return true;}}
function linePoint(a,b,d){{const dx=b.x-a.x,dy=b.y-a.y,len=Math.max(1,Math.hypot(dx,dy));return {{x:a.x+dx*d/len,y:a.y+dy*d/len}};}}
function make(tag,attrs={{}}){{const element=document.createElementNS(NS,tag);Object.entries(attrs).forEach(([k,v])=>element.setAttribute(k,String(v)));return element;}}
function clipped(value,maxLength){{const text=String(value);return text.length<=maxLength?text:text.slice(0,Math.max(1,maxLength-1))+"…";}}
function textWidth(value,fontSize=10){{let width=0;for(const character of String(value))width+=character.charCodeAt(0)>255?fontSize:fontSize*.61;return Math.ceil(width);}}
function overlaps(left,right,padding=4){{return !(left.x+left.width+padding<right.x||right.x+right.width+padding<left.x||left.y+left.height+padding<right.y||right.y+right.height+padding<left.y);}}
function nodeObstacles(){{const boxes=[];data.nodes.forEach(node=>{{boxes.push({{x:node.x-28,y:node.y-28,width:56,height:56}});const name=clipped(node.name==="<missing>"?node.id:node.name,24),width=textWidth(name,11)+12;boxes.push({{x:node.x-width/2,y:node.y+25,width,height:20}});}});return boxes;}}
function placeEdgeLabel(a,b,label,occupied){{const width=textWidth(label)+12,height=18,dx=b.x-a.x,dy=b.y-a.y,length=Math.max(1,Math.hypot(dx,dy)),nx=-dy/length,ny=dx/length;const candidates=[];[.5,.42,.58,.34,.66].forEach(t=>{{[16,-16,30,-30,44,-44].forEach(offset=>candidates.push({{x:a.x+dx*t+nx*offset,y:a.y+dy*t+ny*offset}}));}});const selected=candidates.find(point=>{{const box={{x:point.x-width/2,y:point.y-height/2,width,height}};return !occupied.some(other=>overlaps(box,other));}})||candidates[0];const box={{x:selected.x-width/2,y:selected.y-height/2,width,height}};occupied.push(box);return {{...selected,...box}};}}
function render(){{
  svg.replaceChildren();svg.setAttribute("width",data.canvas.width);svg.setAttribute("height",data.canvas.height);svg.setAttribute("viewBox",`0 0 ${{data.canvas.width}} ${{data.canvas.height}}`);
  const edgeLayer=make("g"),labelLayer=make("g"),nodeLayer=make("g"),occupied=nodeObstacles();svg.append(edgeLayer,labelLayer,nodeLayer);
  data.edges.forEach(edge=>{{const a=nodes.get(edge.source),b=nodes.get(edge.target);if(!a||!b)return;const visible=edgeVisible(edge),start=linePoint(a,b,24),end=linePoint(b,a,24);const line=make("line",{{x1:start.x,y1:start.y,x2:end.x,y2:end.y,class:edgeClass(edge)+(selected===`e${{edge.index}}`?' selected':''),opacity:visible?1:(mode==='compare'?0.16:0)}});line.dataset.index=edge.index;line.addEventListener("click",()=>showEdge(edge));const tip=make("title");tip.textContent=`${{edge.source}} [${{edge.leftPort}}] ↔ ${{edge.target}} [${{edge.rightPort}}]\nVLAN: ${{statusText[edge.vlanStatus]}}`;line.append(tip);edgeLayer.append(line);
    if(visible){{const fullLabel=`${{edge.leftPort}} | ${{edge.rightPort}}`,label=clipped(fullLabel,31),position=placeEdgeLabel(a,b,label,occupied),group=make("g");group.append(make("rect",{{x:position.x,y:position.y,width:position.width,height:position.height,class:"edge-label-bg"}}));const text=make("text",{{x:position.x+position.width/2,y:position.y+position.height/2,class:"edge-label"}});text.textContent=label;const labelTip=make("title");labelTip.textContent=fullLabel;text.append(labelTip);group.append(text);labelLayer.append(group);}}
  }});
  data.nodes.forEach(node=>{{const g=make("g",{{class:`node${{node.isSource?' source':''}}${{node.isTarget?' target':''}}${{selected===`n${{node.id}}`?' selected':''}}`,transform:`translate(${{node.x}} ${{node.y}})`}});g.addEventListener("click",()=>showNode(node));g.append(make("circle",{{r:20}}));const fullName=node.name==="<missing>"?node.id:node.name,name=clipped(fullName,24),nameWidth=textWidth(name,11)+12;g.append(make("rect",{{x:-nameWidth/2,y:25,width:nameWidth,height:20,class:"node-label-bg"}}));const label=make("text",{{y:39}});label.textContent=name;g.append(label);const id=make("text",{{y:4}});id.textContent=clipped(node.id,13);g.append(id);const tip=make("title");tip.textContent=`${{node.id}}\n${{node.name}}\n${{node.role}}`;g.append(tip);nodeLayer.append(g);}});
  applyScale();
}}
function applyScale(){{svg.style.transform=`scale(${{scale}})`;svg.style.marginRight=`${{data.canvas.width*(scale-1)}}px`;svg.style.marginBottom=`${{data.canvas.height*(scale-1)}}px`;}}
function interfaceHtml(item,index){{const focused=focusPort&&item.name===focusPort;return `<div class="interface${{focused?' focus':''}}"><div class="kv"><b>interface-name</b><span>${{esc(item.name||'<missing>')}}</span><b>allow-through-vlan</b><span>${{esc(pretty(item.allowThroughVlan))}}</span><b>配置路径</b><span>${{esc(item.location)}}</span></div><details ${{focused?'open':''}}><summary>完整接口配置 #${{index+1}}</summary><pre>${{esc(pretty(item.config))}}</pre></details></div>`;}}
function showNode(node){{selected=`n${{node.id}}`;focusPort=null;render();sidebar.innerHTML=`<section class="panel"><h2>节点详情</h2><div class="kv"><b>ID</b><span>${{esc(node.id)}}</span><b>设备名称</b><span>${{esc(node.name)}}</span><b>型号</b><span>${{esc(node.model)}}</span><b>厂商</b><span>${{esc(node.manufacturer)}}</span><b>TYPE / ROLE</b><span>${{esc(node.type)}} / ${{esc(node.role)}}</span><b>LSW 邻居数</b><span>${{node.degree}}</span></div></section><section class="panel"><h2>交换机接口（${{node.interfaces.length}}）</h2>${{node.interfaces.map(interfaceHtml).join('')||'无 lsw-interface 配置'}}</section>`;}}
function endpointHtml(nodeId,port,endpoint){{const node=nodes.get(nodeId),items=endpoint.matches||[];return `<section class="panel"><h2>${{esc(nodeId)}} · ${{esc(port)}}</h2><div class="kv"><b>匹配状态</b><span>${{esc(endpoint.status)}}</span><b>设备名称</b><span>${{esc(node?.name||'<missing>')}}</span><b>错误</b><span>${{esc((endpoint.errors||[]).join(', ')||'无')}}</span></div>${{items.map(interfaceHtml).join('')||'<p>没有匹配到接口配置。</p>'}}</section>`;}}
function showEdge(edge){{selected=`e${{edge.index}}`;render();focusPort=edge.leftPort;const left=endpointHtml(edge.source,edge.leftPort,edge.sourceEndpoint);focusPort=edge.rightPort;const right=endpointHtml(edge.target,edge.rightPort,edge.targetEndpoint);focusPort=null;sidebar.innerHTML=`<section class="panel"><h2>链路 #${{edge.index}}</h2><div class="kv"><b>source / LEFTPORT</b><span>${{esc(edge.source)}} / ${{esc(edge.leftPort)}}</span><b>target / RIGHTPORT</b><span>${{esc(edge.target)}} / ${{esc(edge.rightPort)}}</span><b>目标 VLAN</b><span class="status-${{edge.vlanStatus}}">${{statusText[edge.vlanStatus]}}</span><b>双端共同 VLAN</b><span>${{esc(edge.commonSupport)}}</span><b>LABEL</b><span>${{esc(edge.label)}}</span><b>CLASSNAME</b><span>${{esc(edge.className)}}</span><b>路径归属</b><span>${{edge.inAnswer?'标准答案 ':''}}${{edge.inPrediction?'模型输出':''}}${{!edge.inAnswer&&!edge.inPrediction?'非答案链路':''}}</span></div></section>${{left}}${{right}}`;}}
function pathHtml(paths,kind){{return paths.map((path,i)=>`<div class="path ${{kind}}">#${{i+1}} ${{esc(path.join(' → '))}}</div>`).join('')||'<div class="path">无有效路径</div>';}}
function showSummary(){{selected=null;render();const issueRows=Object.entries(data.issues).map(([k,v])=>`<b>${{esc(k)}}</b><span>${{v}}</span>`).join('');sidebar.innerHTML=`<section class="panel"><h2>任务与推理</h2><div class="kv"><b>源节点</b><span>${{esc(data.task.source)}}</span><b>目标节点</b><span>${{esc(data.task.target)}}</span><b>VLAN</b><span>${{esc(data.task.vlanId)}}</span><b>标准跳数</b><span>${{esc(data.answer?.path_length)}}</span><b>预测跳数</b><span>${{esc(data.prediction?.path_length)}}</span><b>模型状态</b><span>${{data.modelSuccess?'成功':'失败'}}</span><b>错误原因</b><span>${{esc(data.modelError||'无')}}</span></div><details><summary>task_question</summary><pre>${{esc(data.task.question||'')}}</pre></details></section><section class="panel"><h2>标准答案路径</h2>${{pathHtml(data.answerPaths,'answer')}}</section><section class="panel"><h2>模型输出路径</h2>${{pathHtml(data.predictionPaths,'prediction')}}</section><section class="panel"><h2>图数据问题</h2><div class="kv">${{issueRows||'<span>未发现</span>'}}</div></section><section class="panel"><div class="legend"><span><i style="border-color:#279156"></i>答案</span><span><i style="border-color:#2775c5"></i>模型</span><span><i style="border-color:#008b8b"></i>重合</span><span><i style="border-color:#d06a6a"></i>VLAN 阻断</span><span><i style="border-color:#d39a45"></i>状态未知</span></div></section>`;}}
document.querySelectorAll(".mode").forEach(button=>button.addEventListener("click",()=>{{mode=button.dataset.mode;document.querySelectorAll(".mode").forEach(item=>item.classList.toggle("active",item===button));render();}}));
function locate(){{const query=document.getElementById("search").value.trim().toLowerCase();if(!query)return;const node=data.nodes.find(item=>item.id.toLowerCase().includes(query)||item.name.toLowerCase().includes(query));if(!node)return;showNode(node);scale=Math.max(scale,1);applyScale();viewport.scrollTo({{left:Math.max(0,node.x*scale-viewport.clientWidth/2),top:Math.max(0,node.y*scale-viewport.clientHeight/2),behavior:"smooth"}});}}
document.getElementById("find").addEventListener("click",locate);document.getElementById("search").addEventListener("keydown",e=>{{if(e.key==='Enter')locate();}});
document.getElementById("zoomIn").addEventListener("click",()=>{{scale=Math.min(3,scale*1.2);applyScale();}});document.getElementById("zoomOut").addEventListener("click",()=>{{scale=Math.max(.25,scale/1.2);applyScale();}});document.getElementById("fit").addEventListener("click",()=>{{scale=Math.min(1,(viewport.clientWidth-20)/data.canvas.width,(viewport.clientHeight-20)/data.canvas.height);viewport.scrollTo(0,0);applyScale();}});
render();showSummary();setTimeout(()=>document.getElementById("fit").click(),0);
</script>
</body></html>'''


def index_html(records: list[PageRecord]) -> str:
    rows = []
    for record in records:
        status = "成功" if record.model_success else "失败"
        exact = "是" if record.exact_match else "否"
        rows.append(
            f'<tr data-text="{html.escape(record.source_file.lower())}" data-status="{status}">'
            f'<td><a href="{html.escape(record.output_file)}">{html.escape(record.source_file)}</a></td>'
            f"<td>{html.escape(record.split)}</td><td>{status}</td><td>{record.vlan_id}</td>"
            f"<td>{record.answer_length}</td><td>{record.prediction_length}</td><td>{exact}</td>"
            f"<td>{record.node_count}</td><td>{record.edge_count}</td></tr>"
        )
    success = sum(record.model_success for record in records)
    exact = sum(record.exact_match for record in records)
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>VLAN 推理可视化索引</title><style>
*{{box-sizing:border-box}}body{{margin:0;font-family:Inter,"Noto Sans SC",Arial,sans-serif;color:#17212b;background:#f5f7f9}}header{{padding:22px 5%;background:#fff;border-bottom:1px solid #d8dee6}}h1{{margin:0 0 8px;font-size:22px}}.stats{{font-size:13px;color:#627080}}main{{padding:18px 5%}}.filters{{display:flex;gap:8px;margin-bottom:12px}}input,select{{height:34px;border:1px solid #b7c0ca;background:#fff;padding:0 9px}}input{{width:min(440px,70vw)}}.table{{overflow:auto;border:1px solid #d8dee6;background:#fff}}table{{width:100%;border-collapse:collapse;font-size:12px}}th,td{{padding:9px 10px;border-bottom:1px solid #e3e7eb;text-align:left;white-space:nowrap}}th{{position:sticky;top:0;background:#edf1f4}}a{{color:#1769aa;text-decoration:none}}a:hover{{text-decoration:underline}}
</style></head><body><header><h1>VLAN 约束路径推理可视化</h1><div class="stats">页面 {len(records)} · 模型成功 {success} · 完全正确 {exact}</div></header><main><div class="filters"><input id="query" type="search" placeholder="按文件名筛选"><select id="status"><option value="">全部状态</option><option>成功</option><option>失败</option></select></div><div class="table"><table><thead><tr><th>文件</th><th>划分</th><th>模型状态</th><th>VLAN</th><th>答案跳数</th><th>预测跳数</th><th>完全正确</th><th>LSW 节点</th><th>LSW 链路</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div></main><script>
const q=document.getElementById('query'),s=document.getElementById('status'),rows=[...document.querySelectorAll('tbody tr')];function filter(){{const text=q.value.trim().toLowerCase();rows.forEach(row=>row.hidden=!(row.dataset.text.includes(text)&&(!s.value||row.dataset.status===s.value)));}}q.addEventListener('input',filter);s.addEventListener('change',filter);
</script></body></html>'''


def collect_files(result_path: Path, split: str) -> list[tuple[Path, str]]:
    if result_path.is_file():
        return [(result_path, result_path.name)]
    if not result_path.is_dir():
        raise FileNotFoundError(f"输入不存在: {result_path}")
    split_dirs = [name for name in ("train", "val") if (result_path / name).is_dir()]
    selected = ("train", "val") if split == "all" else (split,)
    files: list[tuple[Path, str]] = []
    if split_dirs:
        for name in selected:
            root = result_path / name
            if root.is_dir():
                files.extend((path, path.relative_to(result_path).as_posix()) for path in sorted(root.rglob("*.json")))
    else:
        files = [(path, path.relative_to(result_path).as_posix()) for path in sorted(result_path.rglob("*.json"))]
    return files


def main() -> None:
    args = parse_args()
    files = collect_files(args.result_path, args.split)
    args.output_root.mkdir(parents=True, exist_ok=True)
    records: list[PageRecord] = []
    errors: list[dict[str, str]] = []
    skipped_non_samples = 0
    for index, (path, label) in enumerate(files, 1):
        try:
            payload, record = parse_result(path, label, args.max_range_size)
        except (json.JSONDecodeError, OSError, ValueError) as error:
            message = f"{type(error).__name__}: {error}"
            if "缺少 nodes 或 links" in message:
                skipped_non_samples += 1
            else:
                errors.append({"file": label, "error": message})
            continue
        relative_html = Path(label).with_suffix(".html")
        output_path = args.output_root / relative_html
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(page_html(payload), encoding="utf-8")
        records.append(
            PageRecord(
                **{
                    **record.__dict__,
                    "output_file": relative_html.as_posix(),
                }
            )
        )
        if args.progress_interval and (index % args.progress_interval == 0 or index == len(files)):
            print(f"进度: {index}/{len(files)}，已生成 {len(records)}，错误 {len(errors)}")

    (args.output_root / "index.html").write_text(index_html(records), encoding="utf-8")
    summary = {
        "input": str(args.result_path),
        "split": args.split,
        "scanned_json_files": len(files),
        "generated_pages": len(records),
        "model_success_pages": sum(record.model_success for record in records),
        "exact_match_pages": sum(record.exact_match for record in records),
        "skipped_non_sample_files": skipped_non_samples,
        "error_files": len(errors),
        "errors": errors,
    }
    (args.output_root / "visualization_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"索引页面: {(args.output_root / 'index.html').resolve()}")


if __name__ == "__main__":
    main()
