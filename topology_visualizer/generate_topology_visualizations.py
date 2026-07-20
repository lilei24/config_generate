#!/usr/bin/env python3
"""为原始拓扑数据集生成无需外部依赖的交互式 HTML 可视化。"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import time
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


DEFAULT_DATASET_ROOT = Path("datasets")
DEFAULT_OUTPUT_ROOT = Path("/tmp/topology_visualizations")
DEFAULT_PROGRESS_INTERVAL = 20
MISSING_NAME = "<missing>"
MISSING_ROLE = "<missing>"
MISSING_TYPE = "<missing>"

ROLE_COLORS = {
    "CORE": "#c62828",
    "Gateway+CORE": "#7f1d1d",
    "Gateway_vRR": "#ea580c",
    "Gateway": "#f59e0b",
    "AGG": "#7e22ce",
    "ACC": "#2563eb",
    "AP": "#16a34a",
    "Firewall": "#d97706",
    "WAC": "#0891b2",
    MISSING_ROLE: "#6b7280",
}
FALLBACK_COLORS = (
    "#be123c",
    "#4f46e5",
    "#0f766e",
    "#a16207",
    "#9333ea",
    "#0369a1",
    "#b91c1c",
)


@dataclass
class GraphData:
    split: str
    source_file: str
    directed: bool
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    role_counts: Counter[str]
    type_counts: Counter[str]
    isolated_count: int
    degree_one_count: int
    component_count: int
    duplicate_node_ids: int
    invalid_links: int
    duplicate_links: int


def scalar_text(value: Any, fallback: str) -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    return text if text else fallback


def get_device(node: dict[str, Any]) -> dict[str, Any] | None:
    # 原始格式使用 devices；同时兼容可能出现的历史字段 device。
    device = node.get("devices")
    if not isinstance(device, dict):
        device = node.get("device")
    return device if isinstance(device, dict) else None


def get_device_name(node: dict[str, Any]) -> str:
    device = get_device(node)
    if device is None:
        return MISSING_NAME
    return scalar_text(device.get("NAME"), MISSING_NAME)


def get_device_type(node: dict[str, Any]) -> str:
    device = get_device(node)
    if device is None:
        return MISSING_TYPE
    return scalar_text(device.get("TYPE"), MISSING_TYPE)


def get_device_role(node: dict[str, Any]) -> str:
    topology_node = node.get("topologyNode")
    if not isinstance(topology_node, dict):
        return MISSING_ROLE
    return scalar_text(topology_node.get("DEVICEROLE"), MISSING_ROLE)


def role_color(role: str) -> str:
    if role in ROLE_COLORS:
        return ROLE_COLORS[role]
    digest = hashlib.sha256(role.encode("utf-8")).digest()
    return FALLBACK_COLORS[digest[0] % len(FALLBACK_COLORS)]


def connected_components(
    node_ids: Iterable[str], adjacency: dict[str, set[str]]
) -> list[list[str]]:
    remaining = set(node_ids)
    components: list[list[str]] = []
    while remaining:
        start = min(remaining)
        remaining.remove(start)
        queue = deque([start])
        component: list[str] = []
        while queue:
            node_id = queue.popleft()
            component.append(node_id)
            for neighbor in sorted(adjacency[node_id]):
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    queue.append(neighbor)
        components.append(component)
    return sorted(components, key=lambda item: (-len(item), item[0]))


def calculate_initial_positions(
    nodes: list[dict[str, Any]],
    adjacency: dict[str, set[str]],
) -> dict[str, tuple[float, float]]:
    """有 CORE 时按距离分层，否则按连通分量给出确定性的圆形初始布局。"""
    node_ids = [node["id"] for node in nodes]
    core_ids = [node["id"] for node in nodes if node["role"] == "CORE"]
    positions: dict[str, tuple[float, float]] = {}

    if core_ids:
        distances: dict[str, int] = {}
        queue = deque()
        for node_id in sorted(core_ids):
            distances[node_id] = 0
            queue.append(node_id)
        while queue:
            node_id = queue.popleft()
            for neighbor in sorted(adjacency[node_id]):
                if neighbor not in distances:
                    distances[neighbor] = distances[node_id] + 1
                    queue.append(neighbor)

        layers: dict[int, list[str]] = defaultdict(list)
        unreachable: list[str] = []
        for node_id in node_ids:
            if node_id in distances:
                layers[distances[node_id]].append(node_id)
            else:
                unreachable.append(node_id)
        max_layer = max(layers, default=0)
        for layer, layer_nodes in sorted(layers.items()):
            ordered = sorted(layer_nodes)
            for index, node_id in enumerate(ordered):
                x = (index + 1) / (len(ordered) + 1)
                y = 0.08 + layer * (0.72 / max(1, max_layer))
                positions[node_id] = (x, y)
        for index, node_id in enumerate(sorted(unreachable)):
            positions[node_id] = (
                (index + 1) / (len(unreachable) + 1),
                0.94,
            )
        return positions

    components = connected_components(node_ids, adjacency)
    total = max(1, len(node_ids))
    cursor = 0.0
    for component in components:
        width = max(0.16, len(component) / total)
        center_x = min(0.9, cursor + width / 2)
        radius = min(0.18, 0.035 + math.sqrt(len(component)) * 0.012)
        ordered = sorted(component)
        if len(ordered) == 1:
            positions[ordered[0]] = (center_x, 0.5)
        else:
            for index, node_id in enumerate(ordered):
                angle = 2 * math.pi * index / len(ordered)
                positions[node_id] = (
                    center_x + radius * math.cos(angle),
                    0.5 + radius * math.sin(angle),
                )
        cursor += width
    return positions


def parse_graph(dataset_root: Path, split: str, path: Path) -> GraphData:
    with path.open("r", encoding="utf-8") as file:
        raw = json.load(file)
    if not isinstance(raw, dict):
        raise ValueError("top-level JSON must be an object")

    raw_nodes = raw.get("nodes", [])
    if not isinstance(raw_nodes, list):
        raise ValueError("nodes must be a list")

    node_map: dict[str, dict[str, Any]] = {}
    duplicate_node_ids = 0
    for raw_node in raw_nodes:
        if not isinstance(raw_node, dict) or raw_node.get("id") is None:
            continue
        node_id = str(raw_node["id"])
        if node_id in node_map:
            duplicate_node_ids += 1
            continue
        node_map[node_id] = raw_node

    adjacency = {node_id: set() for node_id in node_map}
    edge_pairs: set[tuple[str, str]] = set()
    invalid_links = 0
    duplicate_links = 0
    raw_links = raw.get("links", [])
    if not isinstance(raw_links, list):
        raw_links = []
        invalid_links += 1
    for link in raw_links:
        if not isinstance(link, dict):
            invalid_links += 1
            continue
        source = link.get("source")
        target = link.get("target")
        if source is None or target is None:
            invalid_links += 1
            continue
        source_id = str(source)
        target_id = str(target)
        if source_id not in node_map or target_id not in node_map:
            invalid_links += 1
            continue
        if source_id == target_id:
            invalid_links += 1
            continue
        pair = tuple(sorted((source_id, target_id)))
        if pair in edge_pairs:
            duplicate_links += 1
            continue
        edge_pairs.add(pair)
        adjacency[source_id].add(target_id)
        adjacency[target_id].add(source_id)

    nodes: list[dict[str, Any]] = []
    role_counts: Counter[str] = Counter()
    type_counts: Counter[str] = Counter()
    for node_id, raw_node in node_map.items():
        role = get_device_role(raw_node)
        device_type = get_device_type(raw_node)
        role_counts[role] += 1
        type_counts[device_type] += 1
        nodes.append(
            {
                "id": node_id,
                "name": get_device_name(raw_node),
                "type": device_type,
                "role": role,
                "color": role_color(role),
                "degree": len(adjacency[node_id]),
            }
        )

    positions = calculate_initial_positions(nodes, adjacency)
    for node in nodes:
        node["x"] = round(positions[node["id"]][0], 6)
        node["y"] = round(positions[node["id"]][1], 6)

    edges = [
        {"source": source, "target": target}
        for source, target in sorted(edge_pairs)
    ]
    components = connected_components(node_map, adjacency) if node_map else []
    return GraphData(
        split=split,
        source_file=str(path.relative_to(dataset_root)),
        directed=bool(raw.get("directed", False)),
        nodes=nodes,
        edges=edges,
        role_counts=role_counts,
        type_counts=type_counts,
        isolated_count=sum(node["degree"] == 0 for node in nodes),
        degree_one_count=sum(node["degree"] == 1 for node in nodes),
        component_count=len(components),
        duplicate_node_ids=duplicate_node_ids,
        invalid_links=invalid_links,
        duplicate_links=duplicate_links,
    )


def json_for_script(value: Any) -> str:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        .replace("<", "\\u003c")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def graph_page(graph: GraphData) -> str:
    graph_payload = {
        "nodes": graph.nodes,
        "edges": graph.edges,
        "sourceFile": graph.source_file,
    }
    role_payload = [
        {"role": role, "count": count, "color": role_color(role)}
        for role, count in sorted(
            graph.role_counts.items(), key=lambda item: (-item[1], item[0])
        )
    ]
    type_payload = [
        {"type": device_type, "count": count}
        for device_type, count in sorted(
            graph.type_counts.items(), key=lambda item: (-item[1], item[0])
        )
    ]
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(graph.source_file)} - 拓扑可视化</title>
<style>
:root {{ color-scheme: light; font-family: Inter, "Noto Sans SC", Arial, sans-serif; }}
* {{ box-sizing: border-box; }}
html, body {{ width: 100%; height: 100%; margin: 0; overflow: hidden; background: #f7f8fa; color: #17202a; }}
header {{ height: 52px; display: flex; align-items: center; gap: 14px; padding: 0 16px; background: #fff; border-bottom: 1px solid #d7dce2; }}
h1 {{ min-width: 0; margin: 0; font-size: 16px; font-weight: 650; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.stats {{ margin-left: auto; display: flex; gap: 12px; color: #52606d; font-size: 12px; white-space: nowrap; }}
.app {{ height: calc(100% - 52px); display: grid; grid-template-columns: 270px minmax(0, 1fr); }}
aside {{ overflow: auto; padding: 14px; background: #fff; border-right: 1px solid #d7dce2; }}
.section {{ padding: 0 0 14px; margin: 0 0 14px; border-bottom: 1px solid #e5e7eb; }}
.section:last-child {{ border: 0; }}
.section h2 {{ margin: 0 0 9px; font-size: 12px; color: #52606d; text-transform: uppercase; }}
.search-row {{ display: grid; grid-template-columns: 1fr 34px; gap: 6px; }}
input[type=search] {{ width: 100%; height: 34px; border: 1px solid #b8c0ca; padding: 0 9px; font-size: 13px; }}
button {{ height: 34px; border: 1px solid #aeb7c2; background: #fff; color: #17202a; cursor: pointer; font-size: 13px; }}
button:hover {{ background: #eef2f6; }}
.button-row {{ display: grid; grid-template-columns: 1fr 1fr; gap: 6px; margin-top: 8px; }}
.role {{ display: grid; grid-template-columns: 18px 13px minmax(0, 1fr) auto; gap: 7px; align-items: center; min-height: 29px; font-size: 12px; }}
.swatch {{ width: 11px; height: 11px; border-radius: 50%; }}
.role-name {{ overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.role-count {{ color: #697586; font-variant-numeric: tabular-nums; }}
.details {{ font-size: 12px; line-height: 1.65; overflow-wrap: anywhere; }}
.details b {{ color: #52606d; font-weight: 600; }}
.legend-line {{ display: flex; align-items: center; gap: 8px; min-height: 25px; font-size: 12px; }}
.degree-one {{ width: 13px; height: 13px; border: 3px solid #111827; border-radius: 50%; }}
.isolated {{ width: 13px; height: 13px; border: 2px dashed #111827; border-radius: 50%; }}
main {{ position: relative; min-width: 0; min-height: 0; background: #f7f8fa; }}
canvas {{ display: block; width: 100%; height: 100%; cursor: grab; }}
canvas.dragging {{ cursor: grabbing; }}
.empty {{ position: absolute; inset: 0; display: none; align-items: center; justify-content: center; color: #697586; }}
@media (max-width: 760px) {{
  .app {{ grid-template-columns: 210px minmax(0, 1fr); }}
  .stats span:nth-child(n+4) {{ display: none; }}
}}
</style>
</head>
<body>
<header>
  <h1 title="{html.escape(graph.source_file)}">{html.escape(graph.source_file)}</h1>
  <div class="stats">
    <span>节点 {len(graph.nodes)}</span><span>链路 {len(graph.edges)}</span>
    <span>分量 {graph.component_count}</span><span>度1 {graph.degree_one_count}</span>
    <span>孤立 {graph.isolated_count}</span>
  </div>
</header>
<div class="app">
  <aside>
    <section class="section">
      <h2>节点</h2>
      <div class="search-row">
        <input id="search" type="search" placeholder="ID / NAME" autocomplete="off">
        <button id="searchButton" title="查找节点">⌕</button>
      </div>
      <div class="button-row">
        <button id="fitButton">适应画布</button>
        <button id="physicsButton">暂停布局</button>
      </div>
    </section>
    <section class="section">
      <h2>DEVICEROLE</h2>
      <div id="roles"></div>
    </section>
    <section class="section">
      <h2>DEVICE.TYPE</h2>
      <div id="types"></div>
    </section>
    <section class="section">
      <h2>选中节点</h2>
      <div id="details" class="details">未选择</div>
    </section>
    <section class="section">
      <h2>标记</h2>
      <div class="legend-line"><span class="degree-one"></span><span>无向度数 = 1</span></div>
      <div class="legend-line"><span class="isolated"></span><span>孤立节点</span></div>
    </section>
  </aside>
  <main><canvas id="canvas"></canvas><div id="empty" class="empty">当前筛选没有节点</div></main>
</div>
<script>
"use strict";
const graph = {json_for_script(graph_payload)};
const roles = {json_for_script(role_payload)};
const deviceTypes = {json_for_script(type_payload)};
const canvas = document.getElementById("canvas");
const ctx = canvas.getContext("2d");
const main = canvas.parentElement;
const state = {{ scale: 1, offsetX: 0, offsetY: 0, selected: null, running: true, draggingNode: null, panning: false, lastX: 0, lastY: 0 }};
const enabledRoles = new Set(roles.map(item => item.role));
const enabledTypes = new Set(deviceTypes.map(item => item.type));
const nodeById = new Map();
const neighbors = new Map();
graph.nodes.forEach((node, index) => {{
  node.x = 80 + node.x * Math.max(600, main.clientWidth - 160);
  node.y = 70 + node.y * Math.max(400, main.clientHeight - 140);
  node.vx = 0; node.vy = 0; node.index = index;
  nodeById.set(node.id, node); neighbors.set(node.id, new Set());
}});
graph.edges.forEach(edge => {{ neighbors.get(edge.source)?.add(edge.target); neighbors.get(edge.target)?.add(edge.source); }});

function visibleNodes() {{ return graph.nodes.filter(node => enabledRoles.has(node.role) && enabledTypes.has(node.type)); }}
function worldPoint(clientX, clientY) {{
  const rect = canvas.getBoundingClientRect();
  return {{ x: (clientX - rect.left - state.offsetX) / state.scale, y: (clientY - rect.top - state.offsetY) / state.scale }};
}}
function resize() {{
  const ratio = window.devicePixelRatio || 1;
  const rect = main.getBoundingClientRect();
  canvas.width = Math.max(1, Math.floor(rect.width * ratio)); canvas.height = Math.max(1, Math.floor(rect.height * ratio));
  canvas.style.width = `${{rect.width}}px`; canvas.style.height = `${{rect.height}}px`;
  draw();
}}
function fit() {{
  const nodes = visibleNodes();
  if (!nodes.length) return;
  const minX = Math.min(...nodes.map(n => n.x)), maxX = Math.max(...nodes.map(n => n.x));
  const minY = Math.min(...nodes.map(n => n.y)), maxY = Math.max(...nodes.map(n => n.y));
  const width = Math.max(100, maxX - minX + 90), height = Math.max(100, maxY - minY + 90);
  state.scale = Math.min(main.clientWidth / width, main.clientHeight / height, 2.2);
  state.offsetX = main.clientWidth / 2 - ((minX + maxX) / 2) * state.scale;
  state.offsetY = main.clientHeight / 2 - ((minY + maxY) / 2) * state.scale;
  draw();
}}
function nodeRadius(node) {{ return node.role === "CORE" ? 9 : 7; }}
function draw() {{
  const ratio = window.devicePixelRatio || 1;
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0); ctx.clearRect(0, 0, main.clientWidth, main.clientHeight);
  const nodes = visibleNodes(), visibleIds = new Set(nodes.map(n => n.id));
  document.getElementById("empty").style.display = nodes.length ? "none" : "flex";
  ctx.save(); ctx.translate(state.offsetX, state.offsetY); ctx.scale(state.scale, state.scale);
  const selectedNeighbors = state.selected ? neighbors.get(state.selected) : null;
  graph.edges.forEach(edge => {{
    if (!visibleIds.has(edge.source) || !visibleIds.has(edge.target)) return;
    const source = nodeById.get(edge.source), target = nodeById.get(edge.target);
    const active = !state.selected || edge.source === state.selected || edge.target === state.selected;
    ctx.beginPath(); ctx.moveTo(source.x, source.y); ctx.lineTo(target.x, target.y);
    ctx.strokeStyle = active ? "#7b8794" : "#d6dbe1"; ctx.lineWidth = active ? 1.4 : 0.7; ctx.stroke();
  }});
  const showLabels = nodes.length <= 100 || state.scale >= 1.35;
  nodes.forEach(node => {{
    const active = !state.selected || node.id === state.selected || selectedNeighbors?.has(node.id);
    const radius = nodeRadius(node);
    ctx.save(); ctx.globalAlpha = active ? 1 : 0.3;
    ctx.beginPath(); ctx.arc(node.x, node.y, radius, 0, Math.PI * 2); ctx.fillStyle = node.color; ctx.fill();
    if (node.degree === 0) ctx.setLineDash([3, 2]);
    ctx.strokeStyle = node.id === state.selected ? "#111827" : (node.degree <= 1 ? "#111827" : "#ffffff");
    ctx.lineWidth = node.id === state.selected ? 4 : (node.degree === 1 ? 3 : 1.2); ctx.stroke(); ctx.setLineDash([]);
    if (showLabels || node.id === state.selected) {{
      const label = node.name === "<missing>" ? node.id : node.name;
      ctx.font = "11px Arial"; ctx.textAlign = "center"; ctx.textBaseline = "top";
      ctx.fillStyle = "#17202a"; ctx.fillText(label, node.x, node.y + radius + 4);
    }}
    ctx.restore();
  }});
  ctx.restore();
}}
function simulationStep() {{
  if (!state.running || state.draggingNode) return;
  const nodes = visibleNodes(); if (nodes.length < 2) return;
  const visibleIds = new Set(nodes.map(n => n.id));
  graph.edges.forEach(edge => {{
    if (!visibleIds.has(edge.source) || !visibleIds.has(edge.target)) return;
    const a = nodeById.get(edge.source), b = nodeById.get(edge.target);
    const dx = b.x - a.x, dy = b.y - a.y, distance = Math.max(1, Math.hypot(dx, dy));
    const force = (distance - 72) * 0.0009; const fx = dx / distance * force, fy = dy / distance * force;
    a.vx += fx; a.vy += fy; b.vx -= fx; b.vy -= fy;
  }});
  const checks = nodes.length <= 300 ? nodes.length - 1 : 45;
  nodes.forEach((a, i) => {{
    for (let step = 1; step <= checks; step++) {{
      const j = nodes.length <= 300 ? i + step : (i + step * 17) % nodes.length;
      if (j >= nodes.length || j === i) continue;
      const b = nodes[j], dx = b.x - a.x, dy = b.y - a.y, d2 = Math.max(80, dx * dx + dy * dy);
      const force = Math.min(0.12, 80 / d2); a.vx -= dx * force; a.vy -= dy * force;
      if (nodes.length <= 300) {{ b.vx += dx * force; b.vy += dy * force; }}
    }}
    a.vx += (main.clientWidth / 2 - a.x) * 0.00005; a.vy += (main.clientHeight / 2 - a.y) * 0.00005;
  }});
  nodes.forEach(node => {{ node.vx *= 0.82; node.vy *= 0.82; node.x += Math.max(-5, Math.min(5, node.vx)); node.y += Math.max(-5, Math.min(5, node.vy)); }});
}}
function animate() {{ simulationStep(); draw(); requestAnimationFrame(animate); }}
function findNodeAt(clientX, clientY) {{
  const point = worldPoint(clientX, clientY); let found = null, best = Infinity;
  visibleNodes().forEach(node => {{ const distance = Math.hypot(node.x - point.x, node.y - point.y); if (distance < 13 / state.scale && distance < best) {{ found = node; best = distance; }} }});
  return found;
}}
function selectNode(node) {{
  state.selected = node ? node.id : null;
  const details = document.getElementById("details");
  details.innerHTML = node ? `<b>ID</b> ${{escapeHtml(node.id)}}<br><b>NAME</b> ${{escapeHtml(node.name)}}<br><b>TYPE</b> ${{escapeHtml(node.type)}}<br><b>DEVICEROLE</b> ${{escapeHtml(node.role)}}<br><b>邻居数</b> ${{node.degree}}` : "未选择";
  draw();
}}
function escapeHtml(value) {{ const div = document.createElement("div"); div.textContent = value; return div.innerHTML; }}

canvas.addEventListener("mousedown", event => {{
  const node = findNodeAt(event.clientX, event.clientY); state.lastX = event.clientX; state.lastY = event.clientY;
  if (node) {{ state.draggingNode = node; selectNode(node); }} else {{ state.panning = true; selectNode(null); }}
  canvas.classList.add("dragging");
}});
window.addEventListener("mousemove", event => {{
  if (state.draggingNode) {{ const point = worldPoint(event.clientX, event.clientY); state.draggingNode.x = point.x; state.draggingNode.y = point.y; state.draggingNode.vx = 0; state.draggingNode.vy = 0; }}
  else if (state.panning) {{ state.offsetX += event.clientX - state.lastX; state.offsetY += event.clientY - state.lastY; }}
  state.lastX = event.clientX; state.lastY = event.clientY;
}});
window.addEventListener("mouseup", () => {{ state.draggingNode = null; state.panning = false; canvas.classList.remove("dragging"); }});
canvas.addEventListener("wheel", event => {{
  event.preventDefault(); const rect = canvas.getBoundingClientRect(); const mx = event.clientX - rect.left, my = event.clientY - rect.top;
  const oldScale = state.scale; state.scale = Math.max(0.15, Math.min(6, state.scale * (event.deltaY < 0 ? 1.12 : 0.89)));
  state.offsetX = mx - (mx - state.offsetX) * state.scale / oldScale; state.offsetY = my - (my - state.offsetY) * state.scale / oldScale;
}}, {{ passive: false }});

const roleContainer = document.getElementById("roles");
roles.forEach(item => {{
  const row = document.createElement("label"); row.className = "role";
  row.innerHTML = `<input type="checkbox" checked><span class="swatch" style="background:${{item.color}}"></span><span class="role-name" title="${{escapeHtml(item.role)}}">${{escapeHtml(item.role)}}</span><span class="role-count">${{item.count}}</span>`;
  row.querySelector("input").addEventListener("change", event => {{ event.target.checked ? enabledRoles.add(item.role) : enabledRoles.delete(item.role); if (state.selected && !visibleNodes().some(node => node.id === state.selected)) selectNode(null); fit(); }});
  roleContainer.appendChild(row);
}});
const typeContainer = document.getElementById("types");
deviceTypes.forEach(item => {{
  const row = document.createElement("label"); row.className = "role";
  row.innerHTML = `<input type="checkbox" checked><span></span><span class="role-name" title="${{escapeHtml(item.type)}}">${{escapeHtml(item.type)}}</span><span class="role-count">${{item.count}}</span>`;
  row.querySelector("input").addEventListener("change", event => {{ event.target.checked ? enabledTypes.add(item.type) : enabledTypes.delete(item.type); if (state.selected && !visibleNodes().some(node => node.id === state.selected)) selectNode(null); fit(); }});
  typeContainer.appendChild(row);
}});
function runSearch() {{
  const query = document.getElementById("search").value.trim().toLowerCase(); if (!query) return;
  const node = graph.nodes.find(item => enabledRoles.has(item.role) && enabledTypes.has(item.type) && (item.id.toLowerCase().includes(query) || item.name.toLowerCase().includes(query)));
  if (!node) return; selectNode(node); state.scale = Math.max(state.scale, 1.5); state.offsetX = main.clientWidth / 2 - node.x * state.scale; state.offsetY = main.clientHeight / 2 - node.y * state.scale;
}}
document.getElementById("searchButton").addEventListener("click", runSearch);
document.getElementById("search").addEventListener("keydown", event => {{ if (event.key === "Enter") runSearch(); }});
document.getElementById("fitButton").addEventListener("click", fit);
document.getElementById("physicsButton").addEventListener("click", event => {{ state.running = !state.running; event.target.textContent = state.running ? "暂停布局" : "继续布局"; }});
window.addEventListener("resize", resize);
resize(); setTimeout(fit, 20); animate();
</script>
</body>
</html>
"""


def index_page(records: list[dict[str, Any]], title: str, root_prefix: str = "") -> str:
    rows = []
    for record in records:
        role_text = ", ".join(
            f"{role}: {count}" for role, count in record["roles"].items()
        )
        type_text = ", ".join(
            f"{device_type}: {count}"
            for device_type, count in record["types"].items()
        )
        rows.append(
            "<tr>"
            f"<td><a href=\"{html.escape(root_prefix + record['html_file'])}\">"
            f"{html.escape(record['source_file'])}</a></td>"
            f"<td>{record['node_count']}</td><td>{record['edge_count']}</td>"
            f"<td>{record['component_count']}</td><td>{record['degree_one_count']}</td>"
            f"<td>{record['isolated_count']}</td><td>{'是' if record['has_core'] else '否'}</td>"
            f"<td>{html.escape(role_text)}</td><td>{html.escape(type_text)}</td></tr>"
        )
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title>
<style>
* {{ box-sizing: border-box; }} body {{ margin: 0; font-family: Inter,"Noto Sans SC",Arial,sans-serif; color: #17202a; background: #f7f8fa; }}
header {{ padding: 18px 24px; background: #fff; border-bottom: 1px solid #d7dce2; }} h1 {{ margin: 0; font-size: 20px; }}
main {{ padding: 18px 24px 36px; overflow: auto; }} table {{ width: 100%; border-collapse: collapse; background: #fff; font-size: 13px; }}
th, td {{ padding: 9px 10px; text-align: left; border-bottom: 1px solid #e5e7eb; vertical-align: top; }} th {{ position: sticky; top: 0; background: #eef2f6; white-space: nowrap; }}
tr:hover td {{ background: #f1f5f9; }} a {{ color: #075bb5; text-decoration: none; }} a:hover {{ text-decoration: underline; }}
.count {{ margin-top: 6px; color: #697586; font-size: 13px; }}
</style></head><body><header><h1>{html.escape(title)}</h1><div class="count">共 {len(records)} 张图</div></header>
<main><table><thead><tr><th>文件</th><th>节点</th><th>链路</th><th>分量</th><th>度1</th><th>孤立</th><th>CORE</th><th>DEVICEROLE</th><th>DEVICE.TYPE</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></main></body></html>"""


def list_json_files(dataset_root: Path, split: str) -> list[Path]:
    split_dir = dataset_root / split
    if not split_dir.is_dir():
        return []
    return sorted(path for path in split_dir.rglob("*.json") if path.is_file())


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def output_html_path(output_root: Path, graph: GraphData) -> Path:
    relative = Path(graph.source_file)
    return output_root / relative.with_suffix(".html")


def build_visualizations(args: argparse.Namespace) -> None:
    dataset_root = args.dataset_root.resolve()
    output_root = args.output_root.resolve()
    splits = ["train", "val"] if args.split == "all" else [args.split]
    all_records: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    for split in splits:
        paths = list_json_files(dataset_root, split)
        if args.max_files is not None:
            paths = paths[: args.max_files]
        started_at = time.time()
        print(f"[{split}] 开始生成：{len(paths)} 个文件", flush=True)
        split_records: list[dict[str, Any]] = []
        for index, path in enumerate(paths, start=1):
            try:
                graph = parse_graph(dataset_root, split, path)
                html_path = output_html_path(output_root, graph)
                write_text(html_path, graph_page(graph))
                record = {
                    "split": split,
                    "source_file": graph.source_file,
                    "html_file": str(html_path.relative_to(output_root)),
                    "node_count": len(graph.nodes),
                    "edge_count": len(graph.edges),
                    "component_count": graph.component_count,
                    "degree_one_count": graph.degree_one_count,
                    "isolated_count": graph.isolated_count,
                    "has_core": graph.role_counts.get("CORE", 0) > 0,
                    "roles": dict(
                        sorted(
                            graph.role_counts.items(),
                            key=lambda item: (-item[1], item[0]),
                        )
                    ),
                    "types": dict(
                        sorted(
                            graph.type_counts.items(),
                            key=lambda item: (-item[1], item[0]),
                        )
                    ),
                    "duplicate_node_ids": graph.duplicate_node_ids,
                    "invalid_links": graph.invalid_links,
                    "duplicate_links": graph.duplicate_links,
                }
                split_records.append(record)
                all_records.append(record)
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
                errors.append(
                    {
                        "split": split,
                        "source_file": str(path.relative_to(dataset_root)),
                        "error": f"{type(error).__name__}: {error}",
                    }
                )
            if args.progress_interval > 0 and (
                index % args.progress_interval == 0 or index == len(paths)
            ):
                elapsed = max(0.001, time.time() - started_at)
                speed = index / elapsed
                eta = (len(paths) - index) / speed if speed else 0.0
                print(
                    f"[{split}] {index}/{len(paths)}，{speed:.2f} 文件/秒，"
                    f"预计剩余 {eta:.1f} 秒",
                    flush=True,
                )
        split_index = output_root / split / "index.html"
        adjusted_records = []
        for record in split_records:
            adjusted = dict(record)
            adjusted["html_file"] = str(
                Path(record["html_file"]).relative_to(split)
            )
            adjusted_records.append(adjusted)
        write_text(split_index, index_page(adjusted_records, f"{split} 拓扑索引"))

    write_text(output_root / "index.html", index_page(all_records, "拓扑数据集可视化"))
    summary = {
        "dataset_root": str(dataset_root),
        "output_root": str(output_root),
        "splits": splits,
        "generated_graphs": len(all_records),
        "failed_files": len(errors),
        "total_nodes": sum(record["node_count"] for record in all_records),
        "total_edges": sum(record["edge_count"] for record in all_records),
        "errors": errors,
        "graphs": all_records,
    }
    write_text(
        output_root / "visualization_summary.json",
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
    )
    print(f"完成：生成 {len(all_records)} 张图，失败 {len(errors)} 个文件")
    print(f"入口：{output_root / 'index.html'}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="为原始 train/val 拓扑 JSON 生成交互式 HTML 可视化。"
    )
    parser.add_argument(
        "dataset_root",
        nargs="?",
        type=Path,
        default=DEFAULT_DATASET_ROOT,
        help=f"数据集根目录。默认：{DEFAULT_DATASET_ROOT}",
    )
    parser.add_argument(
        "-o",
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help=f"可视化输出目录。默认：{DEFAULT_OUTPUT_ROOT}",
    )
    parser.add_argument(
        "--split",
        choices=["train", "val", "all"],
        default="all",
        help="处理 train、val 或全部数据。默认：all",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=None,
        help="每个 split 最多处理的文件数，默认不限制。",
    )
    parser.add_argument(
        "--progress-interval",
        type=int,
        default=DEFAULT_PROGRESS_INTERVAL,
        help="每处理 N 个文件打印一次进度，0 表示关闭。默认：%(default)s",
    )
    args = parser.parse_args()
    if args.max_files is not None and args.max_files <= 0:
        parser.error("--max-files 必须大于 0")
    if args.progress_interval < 0:
        parser.error("--progress-interval 不能小于 0")
    return args


if __name__ == "__main__":
    build_visualizations(parse_args())
