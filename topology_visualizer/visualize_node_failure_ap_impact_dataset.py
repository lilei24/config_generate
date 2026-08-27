#!/usr/bin/env python3
"""将节点故障影响 AP 任务的 with_answer 数据集生成为交互式 HTML。"""

from __future__ import annotations

import argparse
import html
import json
from collections import Counter, defaultdict, deque
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional


DEFAULT_DATASET_ROOT = Path("node_failure_ap_impact_dataset/with_answer")
DEFAULT_OUTPUT_ROOT = Path("/tmp/node_failure_ap_impact_visualizations")
DEFAULT_SPLIT = "all"
DEFAULT_PROGRESS_INTERVAL = 20


@dataclass(frozen=True)
class PageRecord:
    source_file: str
    split: str
    output_file: str
    failed_node_id: str
    failed_node_role: str
    impacted_ap_count: int
    impact_level: str
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
    parser.add_argument("--max-files", type=int, default=None)
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
    text = str(value).strip()
    return text or None


def node_device(node: dict[str, Any]) -> dict[str, Any]:
    value = node.get("devices")
    if not isinstance(value, dict):
        value = node.get("device")
    return value if isinstance(value, dict) else {}


def normalize_node_ids(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        node_id = scalar_text(item)
        if node_id is not None and node_id not in seen:
            seen.add(node_id)
            result.append(node_id)
    return result


def impact_level(count: int) -> str:
    if count <= 5:
        return "small"
    if count <= 20:
        return "medium"
    return "large"


def initial_positions(
    node_ids: list[str],
    adjacency: dict[str, set[str]],
    failed_node_id: str,
    affected_ap_ids: set[str],
) -> tuple[dict[str, tuple[float, float]], int, int]:
    """按距故障节点的跳数分层，并在每层优先排列受影响 AP。"""
    distances: dict[str, int] = {}
    if failed_node_id in adjacency:
        distances[failed_node_id] = 0
        queue = deque([failed_node_id])
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
        ordered = sorted(values, key=lambda node_id: (node_id not in affected_ap_ids, node_id))
        max_rows = max(max_rows, len(ordered))
        for index, node_id in enumerate(ordered):
            positions[node_id] = (140 + layer * 270, 100 + index * 88)
    width = max(980, (max(layers, default=0) + 1) * 270 + 250)
    height = max(680, max_rows * 88 + 180)
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

    failed_node_id = scalar_text(document.get("task_failed_node_id"))
    if failed_node_id is None:
        raise ValueError("缺少 task_failed_node_id")
    answer = document.get("task_answer")
    if not isinstance(answer, dict):
        raise ValueError("缺少 task_answer 对象")
    raw_impacted_ids = answer.get("impacted_ap_ids")
    impacted_ap_ids = normalize_node_ids(raw_impacted_ids)
    if not isinstance(raw_impacted_ids, list):
        raise ValueError("task_answer.impacted_ap_ids 不是数组")
    impacted_ap_set = set(impacted_ap_ids)

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
        role = (
            scalar_text(topology.get("DEVICEROLE"))
            if isinstance(topology, dict)
            else None
        ) or "<missing>"
        nodes_by_id[node_id] = {
            "id": node_id,
            "name": scalar_text(device.get("NAME")) or "<missing>",
            "type": scalar_text(device.get("TYPE")) or "<missing>",
            "model": scalar_text(device.get("MODEL")) or "<missing>",
            "role": role,
        }
    if failed_node_id not in nodes_by_id:
        issues["failed-node-not-found"] += 1
    for node_id in impacted_ap_ids:
        node = nodes_by_id.get(node_id)
        if node is None:
            issues["answer-ap-not-found"] += 1
        elif node["role"] != "AP":
            issues["answer-node-role-not-ap"] += 1
    if failed_node_id in impacted_ap_set:
        issues["failed-node-listed-as-impacted-ap"] += 1

    adjacency = {node_id: set() for node_id in nodes_by_id}
    edges: list[dict[str, Any]] = []
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
        adjacency[left_id].add(right_id)
        adjacency[right_id].add(left_id)
        edges.append(
            {
                "index": link_index,
                "source": left_id,
                "target": right_id,
                "leftPort": scalar_text(detail.get("LEFTPORT")) or "<missing>",
                "rightPort": scalar_text(detail.get("RIGHTPORT")) or "<missing>",
                "label": scalar_text(detail.get("LABEL")) or "<missing>",
                "isRemoved": failed_node_id in (left_id, right_id),
            }
        )

    positions, width, height = initial_positions(
        sorted(nodes_by_id), adjacency, failed_node_id, impacted_ap_set
    )
    nodes: list[dict[str, Any]] = []
    for node_id, node in sorted(nodes_by_id.items()):
        node["x"], node["y"] = positions[node_id]
        node["degree"] = len(adjacency[node_id])
        node["isFailed"] = node_id == failed_node_id
        node["isAffectedAp"] = node_id in impacted_ap_set
        nodes.append(node)

    level = impact_level(len(impacted_ap_ids))
    payload = {
        "sourceFile": source_label,
        "task": {
            "failedNode": failed_node_id,
            "question": document.get("task_question"),
            "targetRolePriority": document.get("task_target_role_priority"),
        },
        "answer": answer,
        "impactedApIds": impacted_ap_ids,
        "impactLevel": level,
        "nodes": nodes,
        "edges": edges,
        "issues": dict(sorted(issues.items())),
        "canvas": {"width": width, "height": height},
    }
    split = source_label.split("/", 1)[0] if "/" in source_label else "single"
    failed_role = nodes_by_id.get(failed_node_id, {}).get("role", "<missing>")
    record = PageRecord(
        source_file=source_label,
        split=split,
        output_file="",
        failed_node_id=failed_node_id,
        failed_node_role=failed_role,
        impacted_ap_count=len(impacted_ap_ids),
        impact_level=level,
        node_count=len(nodes),
        edge_count=len(edges),
        removed_edge_count=sum(edge["isRemoved"] for edge in edges),
        validation_issue_count=sum(issues.values()),
    )
    return payload, record


def page_html(payload: dict[str, Any]) -> str:
    title = html.escape(payload["sourceFile"])
    return inject_graph_pan_zoom(f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} - 故障影响 AP 可视化</title><style>
:root{{--border:#d7dde3;--muted:#62707d;--bg:#eef2f4;--red:#c93636;--amber:#d97706;--blue:#176fa6;color-scheme:light;font-family:Inter,"Noto Sans SC",Arial,sans-serif}}*{{box-sizing:border-box}}html,body{{width:100%;height:100%;margin:0;color:#17212b;background:var(--bg)}}body{{display:grid;grid-template-rows:auto auto minmax(0,1fr);overflow:hidden}}header{{display:flex;align-items:center;gap:12px;padding:10px 14px;background:#fff;border-bottom:1px solid var(--border)}}h1{{min-width:0;margin:0;font-size:16px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}.stats{{margin-left:auto;display:flex;gap:7px;white-space:nowrap}}.pill{{padding:3px 7px;border:1px solid var(--border);border-radius:4px;background:#f8fafb;font-size:12px}}.toolbar{{display:flex;align-items:center;gap:8px;padding:8px 12px;background:#fff;border-bottom:1px solid var(--border);overflow-x:auto}}button,input{{height:32px;border:1px solid #aeb9c3;background:#fff;color:#17212b;font-size:12px}}button{{padding:0 10px;cursor:pointer;white-space:nowrap}}button:hover,button.active{{border-color:#5f7180;background:#e9eef1}}input{{width:210px;padding:0 9px}}label.toggle{{display:flex;align-items:center;gap:5px;font-size:12px;white-space:nowrap}}label.toggle input{{width:auto;height:auto}}.spacer{{flex:1}}.app{{min-height:0;display:grid;grid-template-columns:minmax(0,1fr) 400px}}.viewport{{position:relative;min-width:0;min-height:0;overflow:auto;background-color:#f2f5f6;background-image:radial-gradient(#c9d0d5 .7px,transparent .7px);background-size:20px 20px}}#graph{{display:block;transform-origin:0 0}}.edge{{stroke:#a6b0b8;stroke-width:1.5;vector-effect:non-scaling-stroke;cursor:pointer}}.edge:hover,.edge.selected{{stroke:#202a32!important;stroke-width:5!important}}.edge.removed{{stroke:var(--red);stroke-width:4;stroke-dasharray:9 6}}.edge.dim{{opacity:.1}}.remove-x{{stroke:var(--red);stroke-width:3;vector-effect:non-scaling-stroke;pointer-events:none}}.node{{cursor:grab}}.node:active{{cursor:grabbing}}.node circle{{fill:#fff;stroke:#687886;stroke-width:2;vector-effect:non-scaling-stroke}}.node.affected circle{{fill:#fff0d8;stroke:var(--amber);stroke-width:5}}.node.failed circle{{fill:#ffe2e2;stroke:var(--red);stroke-width:6;stroke-dasharray:5 3}}.node:hover circle,.node.selected circle{{stroke:#111!important;stroke-width:6!important}}.node .short-id{{font-size:9px;font-weight:700;text-anchor:middle;dominant-baseline:middle;pointer-events:none}}.node .short-role{{font-size:8px;fill:#4d5d69;text-anchor:middle;dominant-baseline:middle;pointer-events:none}}.node-label text{{font-size:11px;text-anchor:middle;dominant-baseline:middle;pointer-events:none}}.node-label rect{{fill:#fff;stroke:#bdc7cf;stroke-width:1;rx:3;vector-effect:non-scaling-stroke}}.node-label line{{stroke:#87949f;stroke-width:1;vector-effect:non-scaling-stroke}}.badge{{font-size:9px;font-weight:700;text-anchor:middle;pointer-events:none}}.badge.failed{{fill:#a51616}}.badge.affected{{fill:#995100}}aside{{min-height:0;overflow:auto;background:#fff;border-left:1px solid var(--border)}}.panel{{padding:13px 15px;border-bottom:1px solid var(--border)}}.panel h2{{margin:0 0 9px;font-size:13px}}.kv{{display:grid;grid-template-columns:112px minmax(0,1fr);gap:5px 9px;font-size:12px;line-height:1.55}}.kv b{{color:var(--muted);font-weight:600}}pre{{margin:5px 0 0;white-space:pre-wrap;overflow-wrap:anywhere;font:11px/1.5 ui-monospace,SFMono-Regular,Consolas,monospace}}.legend{{display:grid;grid-template-columns:1fr 1fr;gap:8px;font-size:11px;color:var(--muted)}}.legend i{{display:inline-block;width:24px;margin-right:5px;border-top:4px solid;vertical-align:middle}}.warning{{color:#a05b00}}@media(max-width:850px){{.app{{grid-template-columns:minmax(0,1fr) 320px}}.stats .optional{{display:none}}}}@media(max-width:620px){{body{{overflow:auto;display:block}}header,.toolbar{{position:sticky;top:0;z-index:3}}.app{{display:block}}.viewport{{height:62vh}}aside{{height:auto;border-left:0;border-top:1px solid var(--border)}}}}
</style></head><body><header><h1 title="{title}">{title}</h1><div class="stats" id="stats"></div></header><div class="toolbar"><button id="showAll" class="active">完整拓扑</button><button id="showImpact">仅影响面</button><label class="toggle"><input id="labels" type="checkbox">显示完整标签</label><input id="search" type="search" placeholder="搜索节点 ID / NAME"><button id="find">定位</button><span class="spacer"></span><button id="zoomOut">−</button><button id="fit">适配</button><button id="zoomIn">+</button></div><div class="app"><main class="viewport" id="viewport"><svg id="graph" role="img" aria-label="节点故障影响 AP 拓扑图"></svg></main><aside id="sidebar"></aside></div>
<script id="payload" type="application/json">{json_for_script(payload)}</script><script>
"use strict";const data=JSON.parse(document.getElementById("payload").textContent),NS="http://www.w3.org/2000/svg",svg=document.getElementById("graph"),viewport=document.getElementById("viewport"),sidebar=document.getElementById("sidebar"),nodes=new Map(data.nodes.map(n=>[n.id,n]));let scale=1,impactOnly=false,allLabels=false,selected=null,currentDetail="",dragNode=null,dragMoved=false,dragStart=null;const esc=v=>{{const e=document.createElement("div");e.textContent=v==null?"":String(v);return e.innerHTML;}},make=(tag,attrs={{}})=>{{const e=document.createElementNS(NS,tag);Object.entries(attrs).forEach(([k,v])=>e.setAttribute(k,String(v)));return e;}},clip=(value,n=20)=>String(value).length<=n?String(value):String(value).slice(0,n-1)+"…",textWidth=(value,size=11)=>Math.ceil([...String(value)].reduce((sum,c)=>sum+(c.charCodeAt(0)>255?size:size*.62),0)),overlap=(a,b,p=5)=>!(a.x+a.w+p<b.x||b.x+b.w+p<a.x||a.y+a.h+p<b.y||b.y+b.h+p<a.y),linePoint=(a,b,d)=>{{const dx=b.x-a.x,dy=b.y-a.y,len=Math.max(1,Math.hypot(dx,dy));return{{x:a.x+dx*d/len,y:a.y+dy*d/len}};}};document.getElementById("stats").innerHTML=`<span class="pill">故障 ${{esc(data.task.failedNode)}}</span><span class="pill">受影响 AP ${{data.impactedApIds.length}}</span><span class="pill optional">影响等级 ${{data.impactLevel}}</span>`;
function visibleNode(node){{return !impactOnly||node.isFailed||node.isAffectedAp}}function visibleEdge(edge){{return !impactOnly||edge.isRemoved}}function labelPosition(node,text,occupied){{const w=textWidth(text)+12,h=20,candidates=[[0,39],[0,-41],[42,0],[-42,0],[40,31],[-40,31],[40,-31],[-40,-31]];for(const[dx,dy]of candidates){{const box={{x:node.x+dx-w/2,y:node.y+dy-h/2,w,h,dx,dy}};if(!occupied.some(other=>overlap(box,other))){{occupied.push(box);return box;}}}}const box={{x:node.x-w/2,y:node.y+39,w,h,dx:0,dy:49}};occupied.push(box);return box;}}
function render(){{svg.replaceChildren();svg.setAttribute("width",data.canvas.width);svg.setAttribute("height",data.canvas.height);svg.setAttribute("viewBox",`0 0 ${{data.canvas.width}} ${{data.canvas.height}}`);const edgeLayer=make("g"),markLayer=make("g"),nodeLayer=make("g"),labelLayer=make("g");svg.append(edgeLayer,markLayer,nodeLayer,labelLayer);data.edges.forEach(edge=>{{const a=nodes.get(edge.source),b=nodes.get(edge.target);if(!a||!b)return;const visible=visibleEdge(edge),start=linePoint(a,b,28),end=linePoint(b,a,28),line=make("line",{{x1:start.x,y1:start.y,x2:end.x,y2:end.y,class:`edge${{edge.isRemoved?' removed':''}}${{selected===`e${{edge.index}}`?' selected':''}}${{visible?'':' dim'}}`}});line.addEventListener("click",()=>showEdge(edge));edgeLayer.append(line);if(edge.isRemoved&&visible){{const x=(a.x+b.x)/2,y=(a.y+b.y)/2,s=7;markLayer.append(make("line",{{x1:x-s,y1:y-s,x2:x+s,y2:y+s,class:"remove-x"}}),make("line",{{x1:x-s,y1:y+s,x2:x+s,y2:y-s,class:"remove-x"}}));}}}});const occupied=[];data.nodes.forEach(node=>occupied.push({{x:node.x-31,y:node.y-31,w:62,h:62}}));data.nodes.forEach(node=>{{if(!visibleNode(node))return;const group=make("g",{{class:`node${{node.isAffectedAp?' affected':''}}${{node.isFailed?' failed':''}}${{selected===`n${{node.id}}`?' selected':''}}`,transform:`translate(${{node.x}} ${{node.y}})`}});group.addEventListener("mousedown",event=>startDrag(event,node));group.addEventListener("click",()=>{{if(!dragMoved)showNode(node);}});group.append(make("circle",{{r:25}}));const id=make("text",{{class:"short-id",y:-5}});id.textContent=clip(node.id,10);group.append(id);const role=make("text",{{class:"short-role",y:8}});role.textContent=clip(node.role,11);group.append(role);if(node.isFailed||node.isAffectedAp){{const badge=make("text",{{class:`badge ${{node.isFailed?'failed':'affected'}}`,y:-34}});badge.textContent=node.isFailed?'故障':'受影响 AP';group.append(badge);}}const tip=make("title");tip.textContent=`${{node.id}}\nNAME: ${{node.name}}\nTYPE: ${{node.type}}\nROLE: ${{node.role}}`;group.append(tip);nodeLayer.append(group);if(allLabels||node.isFailed){{const text=clip(`${{node.id}} · ${{node.role}}`,30),box=labelPosition(node,text,occupied),label=make("g",{{class:"node-label"}});label.append(make("rect",{{x:box.x,y:box.y,width:box.w,height:box.h}}));const value=make("text",{{x:box.x+box.w/2,y:box.y+box.h/2+1}});value.textContent=text;label.append(value);labelLayer.append(label);}}}});applyScale();}}
function applyScale(){{svg.style.transform=`scale(${{scale}})`;svg.style.marginRight=`${{data.canvas.width*(scale-1)}}px`;svg.style.marginBottom=`${{data.canvas.height*(scale-1)}}px`;}}function updateSidebar(){{const issues=Object.entries(data.issues).map(([k,v])=>`<b>${{esc(k)}}</b><span class="warning">${{v}}</span>`).join('');sidebar.innerHTML=`${{currentDetail}}<section class="panel"><h2>Question</h2><pre>${{esc(data.task.question||'')}}</pre></section><section class="panel"><h2>Answer</h2><pre>${{esc(JSON.stringify(data.answer,null,2))}}</pre></section><section class="panel"><h2>图例</h2><div class="legend"><span><i style="border-color:var(--red);border-style:dashed"></i>故障节点/失效边</span><span><i style="border-color:var(--amber)"></i>答案中的受影响 AP</span><span><i style="border-color:#a6b0b8"></i>其他物理链路</span><span>圆内：ID / DEVICEROLE</span></div></section><section class="panel"><h2>数据校验</h2><div class="kv">${{issues||'<span>未发现结构或答案问题</span>'}}</div></section>`;}}function showSummary(){{selected=null;currentDetail=`<section class="panel"><h2>影响面概览</h2><div class="kv"><b>故障节点</b><span>${{esc(data.task.failedNode)}}</span><b>受影响 AP 数</b><span>${{data.impactedApIds.length}}</span><b>影响等级</b><span>${{esc(data.impactLevel)}}</span><b>失效链路数</b><span>${{data.edges.filter(e=>e.isRemoved).length}}</span><b>角色优先级</b><span>${{esc((data.task.targetRolePriority||[]).join(' > '))}}</span></div></section>`;render();updateSidebar();}}function showNode(node){{selected=`n${{node.id}}`;currentDetail=`<section class="panel"><h2>节点详情</h2><div class="kv"><b>ID</b><span>${{esc(node.id)}}</span><b>DEVICEROLE</b><span>${{esc(node.role)}}</span><b>设备名称</b><span>${{esc(node.name)}}</span><b>TYPE</b><span>${{esc(node.type)}}</span><b>MODEL</b><span>${{esc(node.model)}}</span><b>原图度数</b><span>${{node.degree}}</span><b>影响状态</b><span>${{node.isFailed?'故障节点':node.isAffectedAp?'受影响 AP':'未列入答案'}}</span></div></section>`;render();updateSidebar();}}function showEdge(edge){{selected=`e${{edge.index}}`;currentDetail=`<section class="panel"><h2>链路详情</h2><div class="kv"><b>source</b><span>${{esc(edge.source)}}</span><b>LEFTPORT</b><span>${{esc(edge.leftPort)}}</span><b>target</b><span>${{esc(edge.target)}}</span><b>RIGHTPORT</b><span>${{esc(edge.rightPort)}}</span><b>LABEL</b><span>${{esc(edge.label)}}</span><b>故障后状态</b><span>${{edge.isRemoved?'随故障节点移除':'保留'}}</span></div></section>`;render();updateSidebar();}}
function startDrag(event,node){{event.preventDefault();event.stopPropagation();dragNode=node;dragMoved=false;dragStart={{x:event.clientX,y:event.clientY}};}}window.addEventListener("mousemove",event=>{{if(!dragNode)return;if(Math.hypot(event.clientX-dragStart.x,event.clientY-dragStart.y)>3)dragMoved=true;const rect=svg.getBoundingClientRect();dragNode.x=Math.max(35,Math.min(data.canvas.width-35,(event.clientX-rect.left)/scale));dragNode.y=Math.max(40,Math.min(data.canvas.height-40,(event.clientY-rect.top)/scale));render();}});window.addEventListener("mouseup",()=>{{dragNode=null;setTimeout(()=>{{dragMoved=false;}},0);}});document.getElementById("showAll").addEventListener("click",()=>{{impactOnly=false;document.getElementById("showAll").classList.add("active");document.getElementById("showImpact").classList.remove("active");render();}});document.getElementById("showImpact").addEventListener("click",()=>{{impactOnly=true;document.getElementById("showImpact").classList.add("active");document.getElementById("showAll").classList.remove("active");render();}});document.getElementById("labels").addEventListener("change",event=>{{allLabels=event.target.checked;render();}});function locate(){{const q=document.getElementById("search").value.trim().toLowerCase();if(!q)return;const node=data.nodes.find(n=>n.id.toLowerCase().includes(q)||n.name.toLowerCase().includes(q));if(!node)return;showNode(node);scale=Math.max(scale,1);applyScale();viewport.scrollTo({{left:Math.max(0,node.x*scale-viewport.clientWidth/2),top:Math.max(0,node.y*scale-viewport.clientHeight/2),behavior:"smooth"}});}}document.getElementById("find").addEventListener("click",locate);document.getElementById("search").addEventListener("keydown",event=>{{if(event.key==="Enter")locate();}});document.getElementById("zoomIn").addEventListener("click",()=>{{scale=Math.min(3,scale*1.2);applyScale();}});document.getElementById("zoomOut").addEventListener("click",()=>{{scale=Math.max(.2,scale/1.2);applyScale();}});document.getElementById("fit").addEventListener("click",()=>{{scale=Math.min(1,(viewport.clientWidth-20)/data.canvas.width,(viewport.clientHeight-20)/data.canvas.height);viewport.scrollTo(0,0);applyScale();}});render();showSummary();setTimeout(()=>document.getElementById("fit").click(),0);
</script></body></html>''')


def index_html(records: list[PageRecord]) -> str:
    rows = []
    for record in records:
        status = "有问题" if record.validation_issue_count else "通过"
        search_text = " ".join(
            (record.source_file, record.failed_node_id, record.failed_node_role)
        ).lower()
        rows.append(
            f'<tr data-text="{html.escape(search_text)}" data-split="{html.escape(record.split)}">'
            f'<td><a href="{html.escape(record.output_file)}">{html.escape(record.source_file)}</a></td>'
            f"<td>{html.escape(record.split)}</td><td>{html.escape(record.failed_node_id)}</td>"
            f"<td>{html.escape(record.failed_node_role)}</td><td>{record.impacted_ap_count}</td>"
            f"<td>{html.escape(record.impact_level)}</td><td>{record.removed_edge_count}</td><td>{status}</td></tr>"
        )
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>节点故障影响 AP 可视化</title><style>*{{box-sizing:border-box}}body{{margin:0;font-family:Inter,"Noto Sans SC",Arial,sans-serif;color:#17212b;background:#f2f5f6}}header{{padding:20px 5%;background:#fff;border-bottom:1px solid #d7dde3}}h1{{margin:0 0 7px;font-size:22px}}.stats{{font-size:13px;color:#62707d}}main{{padding:17px 5%}}.filters{{display:flex;gap:8px;margin-bottom:11px}}input,select{{height:34px;border:1px solid #aeb9c3;background:#fff;padding:0 9px}}input{{width:min(450px,70vw)}}.table{{overflow:auto;border:1px solid #d7dde3;background:#fff}}table{{width:100%;border-collapse:collapse;font-size:12px}}th,td{{padding:9px 10px;border-bottom:1px solid #e2e7ea;text-align:left;white-space:nowrap}}th{{position:sticky;top:0;background:#edf1f3}}a{{color:#176fa6;text-decoration:none}}a:hover{{text-decoration:underline}}</style></head><body><header><h1>节点故障影响 AP 可视化</h1><div class="stats">样本 {len(records)} · 受影响 AP {sum(r.impacted_ap_count for r in records)} · 校验异常页面 {sum(bool(r.validation_issue_count) for r in records)}</div></header><main><div class="filters"><input id="q" type="search" placeholder="按文件名、故障节点筛选"><select id="split"><option value="">全部划分</option><option>train</option><option>val</option></select></div><div class="table"><table><thead><tr><th>文件</th><th>划分</th><th>故障节点</th><th>故障角色</th><th>受影响 AP</th><th>影响等级</th><th>失效边</th><th>校验</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div></main><script>const q=document.getElementById('q'),s=document.getElementById('split'),rows=[...document.querySelectorAll('tbody tr')];function filter(){{const text=q.value.trim().toLowerCase();rows.forEach(row=>row.hidden=!(row.dataset.text.includes(text)&&(!s.value||row.dataset.split===s.value)));}}q.addEventListener('input',filter);s.addEventListener('change',filter);</script></body></html>'''


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
    for index, (path, label) in enumerate(files, start=1):
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
        "total_impacted_aps": sum(record.impacted_ap_count for record in records),
        "validation_issue_pages": sum(bool(record.validation_issue_count) for record in records),
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
