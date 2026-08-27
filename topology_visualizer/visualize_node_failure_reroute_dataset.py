#!/usr/bin/env python3
"""将节点故障绕行任务的 with_answer 数据集生成为交互式 HTML。"""

from __future__ import annotations

import argparse
import html
import json
from collections import Counter, defaultdict, deque
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional


DEFAULT_DATASET_ROOT = Path("node_failure_reroute_dataset_from_raw/with_answer")
DEFAULT_OUTPUT_ROOT = Path("/tmp/node_failure_reroute_visualizations")
DEFAULT_SPLIT = "all"
DEFAULT_PROGRESS_INTERVAL = 20


@dataclass(frozen=True)
class PageRecord:
    source_file: str
    split: str
    output_file: str
    source_id: str
    target_id: str
    failed_node_id: str
    path_length: int
    path_count: int
    node_count: int
    edge_count: int
    removed_edge_count: int
    validation_issue_count: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "dataset_root",
        nargs="?",
        type=Path,
        default=DEFAULT_DATASET_ROOT,
        help="with_answer 根目录、split 目录或单个 JSON，默认: %(default)s",
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
        "--max-files",
        type=int,
        default=None,
        help="最多处理的 JSON 数量，默认不限制",
    )
    parser.add_argument(
        "--progress-interval",
        type=int,
        default=DEFAULT_PROGRESS_INTERVAL,
        help="每处理 N 个文件打印进度，0 表示关闭，默认: %(default)s",
    )
    args = parser.parse_args()
    if args.max_files is not None and args.max_files <= 0:
        parser.error("--max-files 必须大于 0")
    if args.progress_interval < 0:
        parser.error("--progress-interval 不能小于 0")
    return args


def scalar_text(value: Any) -> Optional[str]:
    if value is None or isinstance(value, (dict, list, bool)):
        return None
    value = str(value).strip()
    return value or None


def node_device(node: dict[str, Any]) -> dict[str, Any]:
    value = node.get("devices")
    if not isinstance(value, dict):
        value = node.get("device")
    return value if isinstance(value, dict) else {}


def normalize_paths(answer: Any) -> list[list[str]]:
    if not isinstance(answer, dict) or not isinstance(answer.get("paths"), list):
        return []
    result: list[list[str]] = []
    for path in answer["paths"]:
        if not isinstance(path, list) or not path:
            continue
        values = [scalar_text(value) for value in path]
        if all(value is not None for value in values):
            result.append([value for value in values if value is not None])
    return result


def undirected_edge(left: str, right: str) -> tuple[str, str]:
    return tuple(sorted((left, right)))


def path_edges(paths: list[list[str]]) -> set[tuple[str, str]]:
    return {
        undirected_edge(left, right)
        for path in paths
        for left, right in zip(path, path[1:])
    }


def initial_positions(
    node_ids: list[str],
    adjacency: dict[str, set[str]],
    source_id: str,
    answer_nodes: set[str],
) -> tuple[dict[str, tuple[float, float]], int, int]:
    """按源节点距离分层，并把答案节点排到层内前部。"""
    distances: dict[str, int] = {}
    if source_id in adjacency:
        distances[source_id] = 0
        queue = deque([source_id])
        while queue:
            current = queue.popleft()
            for neighbor in sorted(adjacency[current]):
                if neighbor not in distances:
                    distances[neighbor] = distances[current] + 1
                    queue.append(neighbor)

    layers: dict[int, list[str]] = defaultdict(list)
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
            current = queue.popleft()
            component.append(current)
            for neighbor in sorted(adjacency.get(current, set())):
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    queue.append(neighbor)
        layers[next_layer].extend(component)
        next_layer += 1

    positions: dict[str, tuple[float, float]] = {}
    max_rows = 1
    for layer, values in sorted(layers.items()):
        ordered = sorted(values, key=lambda value: (value not in answer_nodes, value))
        max_rows = max(max_rows, len(ordered))
        for index, node_id in enumerate(ordered):
            positions[node_id] = (140 + layer * 280, 100 + index * 92)
    width = max(980, (max(layers, default=0) + 1) * 280 + 250)
    height = max(680, max_rows * 92 + 180)
    return positions, width, height


def json_for_script(value: Any) -> str:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        .replace("<", "\\u003c")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )

GRAPH_PAN_ZOOM_SCRIPT = r"""
<script>
(() => {
  const graphViewport = document.getElementById("viewport");
  const graphSvg = document.getElementById("graph");
  if (!graphViewport || !graphSvg || typeof applyScale !== "function") return;

  let panState = null;
  graphViewport.style.cursor = "grab";
  graphViewport.style.overscrollBehavior = "contain";

  graphViewport.addEventListener("mousedown", event => {
    const interactive = event.target instanceof Element
      && event.target.closest(".node, .edge");
    if (event.button !== 0 || interactive) return;
    event.preventDefault();
    panState = {
      clientX: event.clientX,
      clientY: event.clientY,
      scrollLeft: graphViewport.scrollLeft,
      scrollTop: graphViewport.scrollTop,
    };
    graphViewport.style.cursor = "grabbing";
    graphViewport.style.userSelect = "none";
  });

  window.addEventListener("mousemove", event => {
    if (!panState) return;
    event.preventDefault();
    graphViewport.scrollLeft =
      panState.scrollLeft - (event.clientX - panState.clientX);
    graphViewport.scrollTop =
      panState.scrollTop - (event.clientY - panState.clientY);
  });

  window.addEventListener("mouseup", () => {
    if (!panState) return;
    panState = null;
    graphViewport.style.cursor = "grab";
    graphViewport.style.userSelect = "";
  });

  graphViewport.addEventListener("wheel", event => {
    event.preventDefault();
    const rect = graphViewport.getBoundingClientRect();
    const pointerX = event.clientX - rect.left;
    const pointerY = event.clientY - rect.top;
    const graphX = (graphViewport.scrollLeft + pointerX) / scale;
    const graphY = (graphViewport.scrollTop + pointerY) / scale;
    const zoomFactor = Math.exp(-event.deltaY * 0.0015);
    const nextScale = Math.max(0.2, Math.min(3, scale * zoomFactor));
    if (nextScale === scale) return;

    scale = nextScale;
    applyScale();
    graphViewport.scrollLeft = graphX * scale - pointerX;
    graphViewport.scrollTop = graphY * scale - pointerY;
  }, { passive: false });
})();
</script>
"""


def inject_graph_pan_zoom(page: str) -> str:
    return page.replace("</body>", GRAPH_PAN_ZOOM_SCRIPT + "</body>", 1)


def parse_sample(path: Path, source_label: str) -> tuple[dict[str, Any], PageRecord]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("顶层 JSON 不是对象")
    raw_nodes = document.get("nodes")
    raw_links = document.get("links")
    if not isinstance(raw_nodes, list) or not isinstance(raw_links, list):
        raise ValueError("缺少 nodes 或 links 数组")

    source_id = scalar_text(document.get("task_source_node_id"))
    target_id = scalar_text(document.get("task_target_node_id"))
    failed_node_id = scalar_text(document.get("task_failed_node_id"))
    if source_id is None or target_id is None or failed_node_id is None:
        raise ValueError("缺少 task_source_node_id、task_target_node_id 或 task_failed_node_id")
    answer = document.get("task_answer")
    answer_paths = normalize_paths(answer)
    if not answer_paths:
        raise ValueError("task_answer.paths 不包含有效路径")
    answer_length = answer.get("path_length") if isinstance(answer, dict) else None
    if not isinstance(answer_length, int) or isinstance(answer_length, bool):
        raise ValueError("task_answer.path_length 不是整数")

    issues: Counter[str] = Counter()
    nodes_by_id: dict[str, dict[str, Any]] = {}
    for raw_node in raw_nodes:
        if not isinstance(raw_node, dict):
            issues["invalid-node"] += 1
            continue
        node_id = scalar_text(raw_node.get("id"))
        if node_id is None:
            issues["missing-node-id"] += 1
            continue
        if node_id in nodes_by_id:
            issues["duplicate-node-id"] += 1
            continue
        device = node_device(raw_node)
        topology = raw_node.get("topologyNode")
        nodes_by_id[node_id] = {
            "id": node_id,
            "name": scalar_text(device.get("NAME")) or "<missing>",
            "type": scalar_text(device.get("TYPE")) or "<missing>",
            "model": scalar_text(device.get("MODEL")) or "<missing>",
            "role": (
                scalar_text(topology.get("DEVICEROLE"))
                if isinstance(topology, dict)
                else None
            ) or "<missing>",
        }
    for task_node_id, issue_name in (
        (source_id, "source-node-not-found"),
        (target_id, "target-node-not-found"),
        (failed_node_id, "failed-node-not-found"),
    ):
        if task_node_id not in nodes_by_id:
            issues[issue_name] += 1

    answer_edge_pairs = path_edges(answer_paths)
    answer_node_ids = {node_id for path_value in answer_paths for node_id in path_value}
    adjacency = {node_id: set() for node_id in nodes_by_id}
    edges: list[dict[str, Any]] = []
    existing_pairs: set[tuple[str, str]] = set()
    for link_index, raw_link in enumerate(raw_links):
        if not isinstance(raw_link, dict):
            issues["invalid-link"] += 1
            continue
        left_id = scalar_text(raw_link.get("source"))
        right_id = scalar_text(raw_link.get("target"))
        if left_id not in nodes_by_id or right_id not in nodes_by_id:
            issues["link-endpoint-not-found"] += 1
            continue
        if left_id == right_id:
            issues["self-loop"] += 1
            continue
        detail = raw_link.get("link")
        if not isinstance(detail, dict):
            detail = {}
        pair = undirected_edge(left_id, right_id)
        existing_pairs.add(pair)
        adjacency[left_id].add(right_id)
        adjacency[right_id].add(left_id)
        is_removed = failed_node_id in pair
        edges.append(
            {
                "index": link_index,
                "source": left_id,
                "target": right_id,
                "leftPort": scalar_text(detail.get("LEFTPORT")) or "<missing>",
                "rightPort": scalar_text(detail.get("RIGHTPORT")) or "<missing>",
                "label": scalar_text(detail.get("LABEL")) or "<missing>",
                "className": scalar_text(detail.get("CLASSNAME")) or "<missing>",
                "isRemoved": is_removed,
                "inAnswer": pair in answer_edge_pairs,
                "answerPathIndexes": [
                    index + 1
                    for index, answer_path in enumerate(answer_paths)
                    if pair in path_edges([answer_path])
                ],
            }
        )

    for path_value in answer_paths:
        if path_value[0] != source_id or path_value[-1] != target_id:
            issues["answer-endpoint-mismatch"] += 1
        if failed_node_id in path_value:
            issues["answer-contains-failed-node"] += 1
        if len(path_value) - 1 != answer_length:
            issues["answer-length-mismatch"] += 1
        for left_id, right_id in zip(path_value, path_value[1:]):
            if undirected_edge(left_id, right_id) not in existing_pairs:
                issues["answer-edge-not-found"] += 1

    positions, width, height = initial_positions(
        sorted(nodes_by_id), adjacency, source_id, answer_node_ids
    )
    nodes: list[dict[str, Any]] = []
    for node_id, node in sorted(nodes_by_id.items()):
        node["x"], node["y"] = positions[node_id]
        node["degree"] = len(adjacency[node_id])
        node["isSource"] = node_id == source_id
        node["isTarget"] = node_id == target_id
        node["isFailed"] = node_id == failed_node_id
        node["inAnswer"] = node_id in answer_node_ids
        nodes.append(node)

    metadata = document.get("task_metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    payload = {
        "sourceFile": source_label,
        "task": {
            "source": source_id,
            "target": target_id,
            "failedNode": failed_node_id,
            "question": document.get("task_question"),
        },
        "answer": answer,
        "answerPaths": answer_paths,
        "metadata": metadata,
        "nodes": nodes,
        "edges": edges,
        "issues": dict(sorted(issues.items())),
        "canvas": {"width": width, "height": height},
    }
    split = source_label.split("/", 1)[0] if "/" in source_label else "single"
    record = PageRecord(
        source_file=source_label,
        split=split,
        output_file="",
        source_id=source_id,
        target_id=target_id,
        failed_node_id=failed_node_id,
        path_length=answer_length,
        path_count=len(answer_paths),
        node_count=len(nodes),
        edge_count=len(edges),
        removed_edge_count=sum(edge["isRemoved"] for edge in edges),
        validation_issue_count=sum(issues.values()),
    )
    return payload, record


def page_html(payload: dict[str, Any]) -> str:
    title = html.escape(payload["sourceFile"])
    return inject_graph_pan_zoom(f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} - 节点故障绕行可视化</title>
<style>
:root{{--border:#d7dde3;--muted:#62707d;--bg:#eef2f4;--green:#168451;--red:#c93636;--blue:#176fa6;--violet:#7149a5;color-scheme:light;font-family:Inter,"Noto Sans SC",Arial,sans-serif}}
*{{box-sizing:border-box}}html,body{{width:100%;height:100%;margin:0;color:#17212b;background:var(--bg)}}body{{display:grid;grid-template-rows:auto auto minmax(0,1fr);overflow:hidden}}
header{{display:flex;align-items:center;gap:12px;padding:10px 14px;background:#fff;border-bottom:1px solid var(--border)}}h1{{min-width:0;margin:0;font-size:16px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}.stats{{margin-left:auto;display:flex;gap:7px;white-space:nowrap}}.pill{{padding:3px 7px;border:1px solid var(--border);border-radius:4px;background:#f8fafb;font-size:12px}}
.toolbar{{display:flex;align-items:center;gap:8px;padding:8px 12px;background:#fff;border-bottom:1px solid var(--border);overflow-x:auto}}button,input,select{{height:32px;border:1px solid #aeb9c3;background:#fff;color:#17212b;font-size:12px}}button{{padding:0 10px;cursor:pointer;white-space:nowrap}}button:hover,button.active{{border-color:#5f7180;background:#e9eef1}}input{{width:210px;padding:0 9px}}label.toggle{{display:flex;align-items:center;gap:5px;font-size:12px;white-space:nowrap}}label.toggle input{{width:auto;height:auto}}.spacer{{flex:1}}
.app{{min-height:0;display:grid;grid-template-columns:minmax(0,1fr) 390px}}.viewport{{position:relative;min-width:0;min-height:0;overflow:auto;background-color:#f2f5f6;background-image:radial-gradient(#c9d0d5 .7px,transparent .7px);background-size:20px 20px}}#graph{{display:block;transform-origin:0 0}}
.edge{{stroke:#a6b0b8;stroke-width:1.5;vector-effect:non-scaling-stroke;cursor:pointer}}.edge:hover,.edge.selected{{stroke:#202a32!important;stroke-width:5!important}}.edge.answer{{stroke:var(--green);stroke-width:6}}.edge.removed{{stroke:var(--red);stroke-width:4;stroke-dasharray:9 6;opacity:.92}}.edge.dim{{opacity:.12}}.remove-x{{stroke:var(--red);stroke-width:3;vector-effect:non-scaling-stroke;pointer-events:none}}
.node{{cursor:grab}}.node:active{{cursor:grabbing}}.node circle{{fill:#fff;stroke:#687886;stroke-width:2;vector-effect:non-scaling-stroke}}.node.answer circle{{fill:#e6f6ed;stroke:var(--green);stroke-width:3}}.node.source circle{{fill:#dff2fa;stroke:var(--blue);stroke-width:5}}.node.target circle{{fill:#eee7f7;stroke:var(--violet);stroke-width:5}}.node.failed circle{{fill:#ffe2e2;stroke:var(--red);stroke-width:5;stroke-dasharray:5 3}}.node:hover circle,.node.selected circle{{stroke:#111!important;stroke-width:6!important}}
.node .short-id{{font-size:9px;font-weight:700;text-anchor:middle;dominant-baseline:middle;pointer-events:none}}.node .short-role{{font-size:8px;fill:#4d5d69;text-anchor:middle;dominant-baseline:middle;pointer-events:none}}.node-label text{{font-size:11px;text-anchor:middle;dominant-baseline:middle;pointer-events:none}}.node-label rect{{fill:#fff;stroke:#bdc7cf;stroke-width:1;rx:3;vector-effect:non-scaling-stroke}}.node-label line{{stroke:#87949f;stroke-width:1;vector-effect:non-scaling-stroke}}.badge{{font-size:9px;font-weight:700;fill:#a51616;text-anchor:middle;pointer-events:none}}
aside{{min-height:0;overflow:auto;background:#fff;border-left:1px solid var(--border)}}.panel{{padding:13px 15px;border-bottom:1px solid var(--border)}}.panel h2{{margin:0 0 9px;font-size:13px}}.kv{{display:grid;grid-template-columns:105px minmax(0,1fr);gap:5px 9px;font-size:12px;line-height:1.55}}.kv b{{color:var(--muted);font-weight:600}}.path{{margin:6px 0;padding:8px;border-left:4px solid var(--green);background:#f2f9f5;font:11px/1.55 ui-monospace,SFMono-Regular,Consolas,monospace;overflow-wrap:anywhere;cursor:pointer}}.path:hover,.path.active{{background:#dff2e7}}.legend{{display:grid;grid-template-columns:1fr 1fr;gap:8px;font-size:11px;color:var(--muted)}}.legend i{{display:inline-block;width:24px;margin-right:5px;border-top:4px solid;vertical-align:middle}}pre{{margin:7px 0 0;white-space:pre-wrap;overflow-wrap:anywhere;font:11px/1.5 ui-monospace,SFMono-Regular,Consolas,monospace}}details{{margin-top:10px;font-size:12px}}.warning{{color:#a05b00}}
@media(max-width:850px){{.app{{grid-template-columns:minmax(0,1fr) 310px}}.stats .optional{{display:none}}}}@media(max-width:620px){{body{{overflow:auto;display:block}}header,.toolbar{{position:sticky;top:0;z-index:3}}.app{{display:block}}.viewport{{height:62vh}}aside{{height:auto;border-left:0;border-top:1px solid var(--border)}}}}
</style></head><body>
<header><h1 title="{title}">{title}</h1><div class="stats" id="stats"></div></header>
<div class="toolbar"><button id="showAll" class="active">完整拓扑</button><button id="showTask">任务相关</button><label class="toggle"><input id="labels" type="checkbox">显示完整标签</label><input id="search" type="search" placeholder="搜索节点 ID / NAME"><button id="find">定位</button><span class="spacer"></span><button id="zoomOut" title="缩小">−</button><button id="fit">适配</button><button id="zoomIn" title="放大">+</button></div>
<div class="app"><main class="viewport" id="viewport"><svg id="graph" role="img" aria-label="节点故障绕行任务拓扑图"></svg></main><aside id="sidebar"></aside></div>
<script id="payload" type="application/json">{json_for_script(payload)}</script>
<script>
"use strict";
const data=JSON.parse(document.getElementById("payload").textContent),NS="http://www.w3.org/2000/svg";
const svg=document.getElementById("graph"),viewport=document.getElementById("viewport"),sidebar=document.getElementById("sidebar"),nodes=new Map(data.nodes.map(n=>[n.id,n]));
let scale=1,taskOnly=false,allLabels=false,selected=null,selectedPath=0,currentDetail="",dragNode=null,dragMoved=false,dragStart=null;
const esc=v=>{{const e=document.createElement("div");e.textContent=v==null?"":String(v);return e.innerHTML;}};
const make=(tag,attrs={{}})=>{{const e=document.createElementNS(NS,tag);Object.entries(attrs).forEach(([k,v])=>e.setAttribute(k,String(v)));return e;}};
const clip=(value,n=20)=>String(value).length<=n?String(value):String(value).slice(0,n-1)+"…";
const textWidth=(value,size=11)=>Math.ceil([...String(value)].reduce((sum,c)=>sum+(c.charCodeAt(0)>255?size:size*.62),0));
const overlap=(a,b,p=5)=>!(a.x+a.w+p<b.x||b.x+b.w+p<a.x||a.y+a.h+p<b.y||b.y+b.h+p<a.y);
const linePoint=(a,b,d)=>{{const dx=b.x-a.x,dy=b.y-a.y,len=Math.max(1,Math.hypot(dx,dy));return {{x:a.x+dx*d/len,y:a.y+dy*d/len}};}};
document.getElementById("stats").innerHTML=`<span class="pill">${{esc(data.task.source)}} → ${{esc(data.task.target)}}</span><span class="pill">故障 ${{esc(data.task.failedNode)}}</span><span class="pill optional">${{data.answer.path_length}} 跳 · ${{data.answerPaths.length}} 条最短路径</span>`;
function isPathEdge(edge){{return edge.inAnswer&&(!selectedPath||edge.answerPathIndexes.includes(selectedPath));}}
function edgeVisible(edge){{return !taskOnly||edge.isRemoved||isPathEdge(edge);}}
function labelPosition(node,text,occupied){{const w=textWidth(text)+12,h=20,candidates=[[0,39],[0,-41],[42,0],[-42,0],[40,31],[-40,31],[40,-31],[-40,-31]];for(const [dx,dy] of candidates){{const box={{x:node.x+dx-w/2,y:node.y+dy-h/2,w,h,dx,dy}};if(!occupied.some(other=>overlap(box,other))){{occupied.push(box);return box;}}}}const [dx,dy]=[0,49];const box={{x:node.x+dx-w/2,y:node.y+dy-h/2,w,h,dx,dy}};occupied.push(box);return box;}}
function render(){{
 svg.replaceChildren();svg.setAttribute("width",data.canvas.width);svg.setAttribute("height",data.canvas.height);svg.setAttribute("viewBox",`0 0 ${{data.canvas.width}} ${{data.canvas.height}}`);
 const edgesLayer=make("g"),marksLayer=make("g"),nodesLayer=make("g"),labelsLayer=make("g");svg.append(edgesLayer,marksLayer,nodesLayer,labelsLayer);
 data.edges.forEach(edge=>{{const a=nodes.get(edge.source),b=nodes.get(edge.target);if(!a||!b)return;const visible=edgeVisible(edge),start=linePoint(a,b,28),end=linePoint(b,a,28),answer=isPathEdge(edge);let cls="edge"+(answer?" answer":"")+(edge.isRemoved?" removed":"")+(selected===`e${{edge.index}}`?" selected":"")+(!visible?" dim":"");const line=make("line",{{x1:start.x,y1:start.y,x2:end.x,y2:end.y,class:cls}});line.addEventListener("click",()=>showEdge(edge));const tip=make("title");tip.textContent=`${{edge.source}} [${{edge.leftPort}}] ↔ ${{edge.target}} [${{edge.rightPort}}]${{edge.isRemoved?'\\n节点故障后移除':''}}${{edge.inAnswer?'\\n属于标准答案路径':''}}`;line.append(tip);edgesLayer.append(line);if(edge.isRemoved&&visible){{const x=(a.x+b.x)/2,y=(a.y+b.y)/2,s=7;marksLayer.append(make("line",{{x1:x-s,y1:y-s,x2:x+s,y2:y+s,class:"remove-x"}}),make("line",{{x1:x-s,y1:y+s,x2:x+s,y2:y-s,class:"remove-x"}}));}}}});
 const occupied=[];data.nodes.forEach(node=>occupied.push({{x:node.x-31,y:node.y-31,w:62,h:62}}));
 data.nodes.forEach(node=>{{const relevant=node.isSource||node.isTarget||node.isFailed||node.inAnswer;if(taskOnly&&!relevant)return;let cls="node"+(node.inAnswer?" answer":"")+(node.isSource?" source":"")+(node.isTarget?" target":"")+(node.isFailed?" failed":"")+(selected===`n${{node.id}}`?" selected":"");const group=make("g",{{class:cls,transform:`translate(${{node.x}} ${{node.y}})`}});group.addEventListener("mousedown",event=>startDrag(event,node));group.addEventListener("click",()=>{{if(!dragMoved)showNode(node);}});group.append(make("circle",{{r:25}}));const short=make("text",{{class:"short-id",y:-5}});short.textContent=clip(node.id,10);group.append(short);const role=make("text",{{class:"short-role",y:8}});role.textContent=clip(node.role,11);group.append(role);if(node.isFailed){{const badge=make("text",{{class:"badge",y:-34}});badge.textContent="故障";group.append(badge);}}const tip=make("title");tip.textContent=`${{node.id}}\nNAME: ${{node.name}}\nTYPE: ${{node.type}}\nROLE: ${{node.role}}`;group.append(tip);nodesLayer.append(group);
   if(allLabels||relevant){{const full=`${{node.id}} · ${{node.role}}`,text=clip(full,30),box=labelPosition(node,text,occupied),label=make("g",{{class:"node-label"}});if(Math.abs(box.dx)>1||Math.abs(box.dy-39)>1)label.append(make("line",{{x1:node.x,y1:node.y,x2:box.x+box.w/2,y2:box.y+box.h/2}}));label.append(make("rect",{{x:box.x,y:box.y,width:box.w,height:box.h}}));const value=make("text",{{x:box.x+box.w/2,y:box.y+box.h/2+1}});value.textContent=text;label.append(value);labelsLayer.append(label);}}
 }});applyScale();
}}
function applyScale(){{svg.style.transform=`scale(${{scale}})`;svg.style.marginRight=`${{data.canvas.width*(scale-1)}}px`;svg.style.marginBottom=`${{data.canvas.height*(scale-1)}}px`;}}
function pathHtml(){{return data.answerPaths.map((path,index)=>`<div class="path ${{selectedPath===index+1?'active':''}}" data-path="${{index+1}}">#${{index+1}} · ${{path.length-1}} 跳<br>${{esc(path.join(' → '))}}</div>`).join('');}}
function bindPaths(){{sidebar.querySelectorAll("[data-path]").forEach(item=>item.addEventListener("click",()=>{{const value=Number(item.dataset.path);selectedPath=selectedPath===value?0:value;render();updateSidebar();}}));}}
function updateSidebar(){{sidebar.innerHTML=`${{currentDetail}}<section class="panel"><h2>Question</h2><pre>${{esc(data.task.question||'')}}</pre></section><section class="panel"><h2>Answer</h2><pre>${{esc(JSON.stringify(data.answer,null,2))}}</pre></section><section class="panel"><h2>答案路径交互</h2><p style="font-size:11px;color:var(--muted);margin:0 0 7px">点击路径可单独高亮；再次点击恢复全部。</p>${{pathHtml()}}</section><section class="panel"><h2>图例</h2><div class="legend"><span><i style="border-color:var(--green)"></i>答案路径</span><span><i style="border-color:var(--red);border-style:dashed"></i>故障移除边</span><span><i style="border-color:#a6b0b8"></i>其他物理链路</span><span>红色节点：故障设备</span><span>蓝色节点：源节点</span><span>紫色节点：目标节点</span></div></section>`;bindPaths();}}
function showSummary(reset=true){{if(reset){{selected=null;selectedPath=0;}}currentDetail=`<section class="panel"><h2>任务概览</h2><div class="kv"><b>源节点</b><span>${{esc(data.task.source)}}</span><b>目标节点</b><span>${{esc(data.task.target)}}</span><b>故障节点</b><span>${{esc(data.task.failedNode)}}</span><b>最短跳数</b><span>${{data.answer.path_length}}</span><b>答案路径数</b><span>${{data.answerPaths.length}}</span><b>失效链路数</b><span>${{data.edges.filter(e=>e.isRemoved).length}}</span><b>目标角色</b><span>${{esc(data.metadata.target_role||'<missing>')}}</span></div></section>`;render();updateSidebar();}}
function showNode(node){{selected=`n${{node.id}}`;currentDetail=`<section class="panel"><h2>节点详情</h2><div class="kv"><b>ID</b><span>${{esc(node.id)}}</span><b>DEVICEROLE</b><span>${{esc(node.role)}}</span><b>设备名称</b><span>${{esc(node.name)}}</span><b>TYPE</b><span>${{esc(node.type)}}</span><b>MODEL</b><span>${{esc(node.model)}}</span><b>原图度数</b><span>${{node.degree}}</span><b>任务身份</b><span>${{node.isFailed?'故障节点':node.isSource?'源节点':node.isTarget?'目标节点':node.inAnswer?'答案路径节点':'普通节点'}}</span></div></section>`;render();updateSidebar();}}
function showEdge(edge){{selected=`e${{edge.index}}`;currentDetail=`<section class="panel"><h2>链路详情</h2><div class="kv"><b>source</b><span>${{esc(edge.source)}}</span><b>LEFTPORT</b><span>${{esc(edge.leftPort)}}</span><b>target</b><span>${{esc(edge.target)}}</span><b>RIGHTPORT</b><span>${{esc(edge.rightPort)}}</span><b>LABEL</b><span>${{esc(edge.label)}}</span><b>故障后状态</b><span>${{edge.isRemoved?'随故障节点移除':'保留'}}</span><b>路径归属</b><span>${{edge.inAnswer?'标准答案路径 #'+edge.answerPathIndexes.join(', #'):'非答案链路'}}</span></div></section>`;render();updateSidebar();}}
function startDrag(event,node){{event.preventDefault();event.stopPropagation();dragNode=node;dragMoved=false;dragStart={{x:event.clientX,y:event.clientY}};}}
window.addEventListener("mousemove",event=>{{if(!dragNode)return;if(Math.hypot(event.clientX-dragStart.x,event.clientY-dragStart.y)>3)dragMoved=true;const rect=svg.getBoundingClientRect();dragNode.x=Math.max(35,Math.min(data.canvas.width-35,(event.clientX-rect.left)/scale));dragNode.y=Math.max(40,Math.min(data.canvas.height-40,(event.clientY-rect.top)/scale));render();}});window.addEventListener("mouseup",()=>{{dragNode=null;setTimeout(()=>{{dragMoved=false;}},0);}});
document.getElementById("showAll").addEventListener("click",()=>{{taskOnly=false;document.getElementById("showAll").classList.add("active");document.getElementById("showTask").classList.remove("active");render();}});document.getElementById("showTask").addEventListener("click",()=>{{taskOnly=true;document.getElementById("showTask").classList.add("active");document.getElementById("showAll").classList.remove("active");render();}});document.getElementById("labels").addEventListener("change",e=>{{allLabels=e.target.checked;render();}});
function locate(){{const q=document.getElementById("search").value.trim().toLowerCase();if(!q)return;const node=data.nodes.find(n=>n.id.toLowerCase().includes(q)||n.name.toLowerCase().includes(q));if(!node)return;showNode(node);scale=Math.max(scale,1);applyScale();viewport.scrollTo({{left:Math.max(0,node.x*scale-viewport.clientWidth/2),top:Math.max(0,node.y*scale-viewport.clientHeight/2),behavior:"smooth"}});}}document.getElementById("find").addEventListener("click",locate);document.getElementById("search").addEventListener("keydown",event=>{{if(event.key==="Enter")locate();}});
document.getElementById("zoomIn").addEventListener("click",()=>{{scale=Math.min(3,scale*1.2);applyScale();}});document.getElementById("zoomOut").addEventListener("click",()=>{{scale=Math.max(.2,scale/1.2);applyScale();}});document.getElementById("fit").addEventListener("click",()=>{{scale=Math.min(1,(viewport.clientWidth-20)/data.canvas.width,(viewport.clientHeight-20)/data.canvas.height);viewport.scrollTo(0,0);applyScale();}});
render();showSummary();setTimeout(()=>document.getElementById("fit").click(),0);
</script></body></html>''')


def index_html(records: list[PageRecord]) -> str:
    rows = []
    for record in records:
        rows.append(
            f'<tr data-text="{html.escape(" ".join((record.source_file, record.source_id, record.target_id, record.failed_node_id)).lower())}" '
            f'data-split="{html.escape(record.split)}"><td><a href="{html.escape(record.output_file)}">'
            f"{html.escape(record.source_file)}</a></td><td>{html.escape(record.split)}</td>"
            f"<td>{html.escape(record.source_id)}</td><td>{html.escape(record.target_id)}</td>"
            f"<td>{html.escape(record.failed_node_id)}</td><td>{record.path_length}</td>"
            f"<td>{record.path_count}</td><td>{record.removed_edge_count}</td></tr>"
        )
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>节点故障绕行数据集可视化</title><style>
*{{box-sizing:border-box}}body{{margin:0;font-family:Inter,"Noto Sans SC",Arial,sans-serif;color:#17212b;background:#f2f5f6}}header{{padding:20px 5%;background:#fff;border-bottom:1px solid #d7dde3}}h1{{margin:0 0 7px;font-size:22px}}.stats{{font-size:13px;color:#62707d}}main{{padding:17px 5%}}.filters{{display:flex;gap:8px;margin-bottom:11px}}input,select{{height:34px;border:1px solid #aeb9c3;background:#fff;padding:0 9px}}input{{width:min(450px,70vw)}}.table{{overflow:auto;border:1px solid #d7dde3;background:#fff}}table{{width:100%;border-collapse:collapse;font-size:12px}}th,td{{padding:9px 10px;border-bottom:1px solid #e2e7ea;text-align:left;white-space:nowrap}}th{{position:sticky;top:0;background:#edf1f3}}a{{color:#176fa6;text-decoration:none}}a:hover{{text-decoration:underline}}
</style></head><body><header><h1>节点故障绕行数据集可视化</h1><div class="stats">样本 {len(records)}</div></header><main><div class="filters"><input id="q" type="search" placeholder="按文件名、节点 ID 筛选"><select id="split"><option value="">全部划分</option><option>train</option><option>val</option></select></div><div class="table"><table><thead><tr><th>文件</th><th>划分</th><th>源节点</th><th>目标节点</th><th>故障节点</th><th>跳数</th><th>答案路径数</th><th>失效边数</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div></main><script>
const q=document.getElementById('q'),s=document.getElementById('split'),rows=[...document.querySelectorAll('tbody tr')];function filter(){{const text=q.value.trim().toLowerCase();rows.forEach(row=>row.hidden=!(row.dataset.text.includes(text)&&(!s.value||row.dataset.split===s.value)));}}q.addEventListener('input',filter);s.addEventListener('change',filter);
</script></body></html>'''


def collect_files(root: Path, split: str) -> list[tuple[Path, str]]:
    if root.is_file():
        return [(root, root.name)]
    if not root.is_dir():
        raise FileNotFoundError(f"输入不存在: {root}")
    selected = ("train", "val") if split == "all" else (split,)
    has_split_dirs = any((root / name).is_dir() for name in ("train", "val"))
    files: list[tuple[Path, str]] = []
    if has_split_dirs:
        for name in selected:
            split_root = root / name
            if split_root.is_dir():
                files.extend(
                    (path, path.relative_to(root).as_posix())
                    for path in sorted(split_root.rglob("*.json"))
                )
    else:
        files.extend(
            (path, path.relative_to(root).as_posix())
            for path in sorted(root.rglob("*.json"))
        )
    return files


def main() -> None:
    args = parse_args()
    files = collect_files(args.dataset_root, args.split)
    if args.max_files is not None:
        files = files[: args.max_files]
    args.output_root.mkdir(parents=True, exist_ok=True)
    records: list[PageRecord] = []
    errors: list[dict[str, str]] = []
    for index, (path, label) in enumerate(files, 1):
        try:
            payload, record = parse_sample(path, label)
            relative_output = Path(label).with_suffix(".html")
            output_path = args.output_root / relative_output
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(page_html(payload), encoding="utf-8")
            records.append(
                PageRecord(**{**asdict(record), "output_file": relative_output.as_posix()})
            )
        except (json.JSONDecodeError, OSError, ValueError) as error:
            errors.append({"file": label, "error": f"{type(error).__name__}: {error}"})
        if args.progress_interval and (
            index % args.progress_interval == 0 or index == len(files)
        ):
            print(f"进度: {index}/{len(files)}，已生成 {len(records)}，错误 {len(errors)}")

    (args.output_root / "index.html").write_text(index_html(records), encoding="utf-8")
    summary = {
        "input": str(args.dataset_root),
        "split": args.split,
        "scanned_json_files": len(files),
        "generated_pages": len(records),
        "validation_issue_pages": sum(bool(record.validation_issue_count) for record in records),
        "total_removed_edges": sum(record.removed_edge_count for record in records),
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
