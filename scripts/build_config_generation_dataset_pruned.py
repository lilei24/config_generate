#!/usr/bin/env python3
"""从图 JSON 数据集构造配置生成任务的 QA 样本，并裁剪过长上下文。

当前任务粒度是预测一个 config 对象里的一个顶层 key：

- node 配置来自 ``nodes[].configs[]``，同时兼容历史样例里的 ``nodes[].config[]``。
- deviceGroup 配置来自 ``deviceGroups[].configs[]``。
- 一个训练样本只遮挡一个顶层 key，目标输出也只包含该 key 对应的配置对象。

脚本把“选择哪个 key”与“怎样遮挡 key”拆成独立策略，后续可以在不改主流程
的前提下新增前部 key、后部 key 选择策略，或者新增占位符类遮挡策略。

当图上下文过长时，本脚本会先随机选择一个中心节点，再逐个删除距离中心最远
的节点，直到估算 token 数低于阈值，之后再构造 node/deviceGroup QA。
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import random
import time
from collections import Counter, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Deque, Dict, Iterable, List, Optional, Sequence, Set, Tuple


# 本地默认路径。输入数据集目录结构约定为：
# datasets/train/*.json
# datasets/val/*.json
# 如果真实数据在别的位置，可以改这里，也可以用命令行参数覆盖。
DEFAULT_DATASET_ROOT = Path("datasets")
DEFAULT_OUTPUT_DIR = Path("QA")
# 固定默认随机种子，保证同一份输入数据多次构造时随机选中的目标可复现。
DEFAULT_RANDOM_SEED = 20260522
DEFAULT_PROGRESS_INTERVAL = 100
DEFAULT_MAX_INPUT_TOKENS = 100000


@dataclass(frozen=True)
class ConfigTarget:
    """一个可被预测的配置顶层 key 的定位信息。

    owner_index 指向所属 node 或 deviceGroup 在原图 list 中的位置。
    config_index 指向所属 config/configs 列表中的对象位置。
    config_field 记录该列表在原始 JSON 里的字段名，node 侧通常是 configs。
    config_key 是真正需要遮挡和预测的顶层配置名。
    """

    source_kind: str
    owner_index: int
    config_index: int
    config_field: str
    config_key: str
    node_id: Optional[str] = None
    device_group_name: Optional[str] = None
    device_group_type: Optional[str] = None


@dataclass(frozen=True)
class BuildIssue:
    """构造数据集时需要落盘记录的源文件问题。"""

    split: str
    file: str
    issue: str
    detail: str = ""


@dataclass(frozen=True)
class PruneResult:
    """单张图的上下文裁剪结果。"""

    graph: Dict[str, Any]
    center_node_id: Optional[str]
    original_token_estimate: int
    final_token_estimate: int
    original_node_count: int
    final_node_count: int
    removed_node_count: int
    pruned: bool
    still_over_limit: bool


# 目标选择器只关心“从候选池选谁”，不负责改图。
TargetSelector = Callable[[Sequence[ConfigTarget], random.Random], Optional[ConfigTarget]]
# 遮挡策略只关心“给定目标后如何生成 input”，不负责挑目标。
MaskStrategy = Callable[[Dict[str, Any], ConfigTarget], Dict[str, Any]]


def stable_json_text(value: Any) -> str:
    """把图上下文转成稳定 JSON 文本，并保留原字段顺序。"""

    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def rough_bpe_token_count(text: str) -> int:
    """粗略估算 BPE token 数。

    这不是任何具体模型的精确 tokenizer，只用于在构造样本时控制上下文长度量级。
    规则与 analyze_qa_tokens.py 保持一致，便于前后统计口径接近。
    """

    count = 0
    index = 0
    while index < len(text):
        char = text[index]
        code = ord(char)
        if char.isspace():
            index += 1
            continue
        if 0x4E00 <= code <= 0x9FFF:
            count += 1
            index += 1
            continue
        if char.isascii() and (char.isalnum() or char in "_-./"):
            start = index
            while index < len(text):
                current = text[index]
                if current.isascii() and (current.isalnum() or current in "_-./"):
                    index += 1
                    continue
                break
            count += max(1, math.ceil((index - start) / 4))
            continue
        count += 1
        index += 1
    return count


def graph_token_estimate(graph: Dict[str, Any]) -> int:
    """估算当前图上下文 token 数。"""

    return rough_bpe_token_count(stable_json_text(graph))


def iter_json_files(dataset_root: Path, splits: Iterable[str]) -> Iterable[Tuple[str, Path]]:
    """按 split 递归枚举 JSON 文件。

    这里保留递归扫描，允许 train/val 下继续按业务目录分层。
    """

    for split in splits:
        split_dir = dataset_root / split
        if not split_dir.exists():
            continue
        for path in sorted(split_dir.rglob("*.json")):
            if path.is_file():
                yield split, path


def list_split_json_files(dataset_root: Path, split: str) -> List[Path]:
    """列出单个 split 下的 JSON 文件，便于提前知道进度总数。"""

    return [path for _, path in iter_json_files(dataset_root, [split])]


def load_graph(path: Path) -> Tuple[Optional[Dict[str, Any]], str]:
    """读取一张图。

    返回 ``(graph, "")`` 表示成功；返回 ``(None, detail)`` 表示该文件不能
    用来构造样本，调用方会把 detail 写入 build_issues.jsonl。
    """

    try:
        graph = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - bad source files are recorded and skipped.
        return None, str(exc)
    if not isinstance(graph, dict):
        return None, f"top-level JSON type is {type(graph).__name__}, expected object"
    return graph, ""


def node_id_at(node: Any) -> Optional[str]:
    """读取 node id；没有 id 的异常节点不能作为中心点或图距离节点。"""

    if not isinstance(node, dict):
        return None
    node_id = node.get("id")
    return str(node_id) if node_id is not None else None


def graph_nodes(graph: Dict[str, Any]) -> List[Any]:
    """安全读取 nodes 列表。"""

    nodes = graph.get("nodes")
    return nodes if isinstance(nodes, list) else []


def choose_random_center_node_id(graph: Dict[str, Any], rng: random.Random) -> Optional[str]:
    """从当前图中随机选择一个中心节点。"""

    node_ids = [node_id_at(node) for node in graph_nodes(graph)]
    valid_node_ids = [node_id for node_id in node_ids if node_id is not None]
    return rng.choice(valid_node_ids) if valid_node_ids else None


def build_adjacency(graph: Dict[str, Any]) -> Dict[str, Set[str]]:
    """根据 links 构造无向邻接表。

    源数据 directed=false；即便某些文件字段缺失，也只使用存在于 nodes 中的端点。
    """

    node_ids = {node_id for node_id in (node_id_at(node) for node in graph_nodes(graph)) if node_id is not None}
    adjacency: Dict[str, Set[str]] = {node_id: set() for node_id in node_ids}
    links = graph.get("links")
    if not isinstance(links, list):
        return adjacency
    for link in links:
        if not isinstance(link, dict):
            continue
        source = link.get("source")
        target = link.get("target")
        if source is None or target is None:
            continue
        source_id = str(source)
        target_id = str(target)
        if source_id not in adjacency or target_id not in adjacency:
            continue
        adjacency[source_id].add(target_id)
        adjacency[target_id].add(source_id)
    return adjacency


def shortest_distances(graph: Dict[str, Any], center_node_id: str) -> Dict[str, float]:
    """计算中心节点到每个节点的最短路距离；不可达节点距离为无穷。"""

    adjacency = build_adjacency(graph)
    distances: Dict[str, float] = {node_id: math.inf for node_id in adjacency}
    if center_node_id not in adjacency:
        return distances
    distances[center_node_id] = 0
    queue: Deque[str] = deque([center_node_id])
    while queue:
        current = queue.popleft()
        for neighbor in adjacency[current]:
            if distances[neighbor] != math.inf:
                continue
            distances[neighbor] = distances[current] + 1
            queue.append(neighbor)
    return distances


def farthest_removable_node_id(graph: Dict[str, Any], center_node_id: str) -> Optional[str]:
    """选择当前图里离中心点最远的可删除节点。

    多个节点距离相同的时候，删除原 nodes 列表中更靠后的节点，使行为稳定。
    """

    distances = shortest_distances(graph, center_node_id)
    best_node_id: Optional[str] = None
    best_rank: Tuple[int, float, int] = (-1, -1.0, -1)
    for node_index, node in enumerate(graph_nodes(graph)):
        node_id = node_id_at(node)
        if node_id is None or node_id == center_node_id:
            continue
        distance = distances.get(node_id, math.inf)
        rank = (1 if distance == math.inf else 0, distance, node_index)
        if rank > best_rank:
            best_rank = rank
            best_node_id = node_id
    return best_node_id


def remove_node_from_graph(graph: Dict[str, Any], removed_node_id: str) -> None:
    """从图中删除一个节点对象，并删除所有连接到该节点的 link。"""

    nodes = graph.get("nodes")
    if isinstance(nodes, list):
        graph["nodes"] = [node for node in nodes if node_id_at(node) != removed_node_id]

    links = graph.get("links")
    if isinstance(links, list):
        graph["links"] = [
            link
            for link in links
            if not (
                isinstance(link, dict)
                and (str(link.get("source")) == removed_node_id or str(link.get("target")) == removed_node_id)
            )
        ]


def prune_graph_to_token_limit(
    graph: Dict[str, Any],
    rng: random.Random,
    max_input_tokens: int,
) -> PruneResult:
    """随机选中心节点，并按最远节点优先删除，直到上下文 token 估算满足限制。"""

    working_graph = copy.deepcopy(graph)
    original_token_estimate = graph_token_estimate(working_graph)
    original_node_count = len(graph_nodes(working_graph))
    center_node_id = choose_random_center_node_id(working_graph, rng)

    if max_input_tokens <= 0 or original_token_estimate <= max_input_tokens or center_node_id is None:
        return PruneResult(
            graph=working_graph,
            center_node_id=center_node_id,
            original_token_estimate=original_token_estimate,
            final_token_estimate=original_token_estimate,
            original_node_count=original_node_count,
            final_node_count=original_node_count,
            removed_node_count=0,
            pruned=False,
            still_over_limit=max_input_tokens > 0 and original_token_estimate > max_input_tokens,
        )

    current_token_estimate = original_token_estimate
    removed_node_count = 0
    while current_token_estimate > max_input_tokens:
        removed_node_id = farthest_removable_node_id(working_graph, center_node_id)
        if removed_node_id is None:
            break
        remove_node_from_graph(working_graph, removed_node_id)
        removed_node_count += 1
        current_token_estimate = graph_token_estimate(working_graph)

    return PruneResult(
        graph=working_graph,
        center_node_id=center_node_id,
        original_token_estimate=original_token_estimate,
        final_token_estimate=current_token_estimate,
        original_node_count=original_node_count,
        final_node_count=len(graph_nodes(working_graph)),
        removed_node_count=removed_node_count,
        pruned=removed_node_count > 0,
        still_over_limit=current_token_estimate > max_input_tokens,
    )


def top_level_config_keys(config_items: Any) -> Iterable[Tuple[int, str]]:
    """枚举 config/configs 列表内所有可预测顶层 key。

    一个 config 对象通常只有一个顶层 key，但这里不依赖该假设。若一个对象里
    有多个顶层 key，会把它们分别列成候选目标，后续只遮挡被选中的那一个。
    """

    if not isinstance(config_items, list):
        return
    for config_index, config_item in enumerate(config_items):
        if not isinstance(config_item, dict):
            continue
        for config_key in config_item:
            yield config_index, str(config_key)


def node_config_items(node: Dict[str, Any]) -> Tuple[Optional[str], Any]:
    """读取 node 配置列表字段。

    真实数据使用 configs；保留 config 兼容早期测试 JSON。
    """

    if "configs" in node:
        return "configs", node.get("configs")
    if "config" in node:
        return "config", node.get("config")
    return None, None


def collect_node_targets(graph: Dict[str, Any]) -> List[ConfigTarget]:
    """收集整张图中所有 node config 候选目标。"""

    targets: List[ConfigTarget] = []
    nodes = graph.get("nodes")
    if not isinstance(nodes, list):
        return targets

    for node_index, node in enumerate(nodes):
        if not isinstance(node, dict):
            continue
        # node_id 会写入 prompt 和 metadata，方便模型定位，也方便人工回查。
        node_id = str(node.get("id")) if node.get("id") is not None else None
        config_field, config_items = node_config_items(node)
        if config_field is None:
            continue
        for config_index, config_key in top_level_config_keys(config_items):
            targets.append(
                ConfigTarget(
                    source_kind="node",
                    owner_index=node_index,
                    config_index=config_index,
                    config_field=config_field,
                    config_key=config_key,
                    node_id=node_id,
                )
            )
    return targets


def collect_device_group_targets(graph: Dict[str, Any]) -> List[ConfigTarget]:
    """收集整张图中所有 deviceGroup configs 候选目标。"""

    targets: List[ConfigTarget] = []
    device_groups = graph.get("deviceGroups")
    if not isinstance(device_groups, list):
        return targets

    for device_group_index, device_group_item in enumerate(device_groups):
        if not isinstance(device_group_item, dict):
            continue
        # NAME 和 DEVICEGROUPTYPES 不是定位目标所必需，但保留它们后 prompt 和
        # metadata 会更利于排查样本来源。
        device_group = device_group_item.get("deviceGroup")
        device_group_name = None
        device_group_type = None
        if isinstance(device_group, dict):
            if device_group.get("NAME") is not None:
                device_group_name = str(device_group["NAME"])
            if device_group.get("DEVICEGROUPTYPES") is not None:
                device_group_type = str(device_group["DEVICEGROUPTYPES"])
        for config_index, config_key in top_level_config_keys(device_group_item.get("configs")):
            targets.append(
                ConfigTarget(
                    source_kind="device_group",
                    owner_index=device_group_index,
                    config_index=config_index,
                    config_field="configs",
                    config_key=config_key,
                    device_group_name=device_group_name,
                    device_group_type=device_group_type,
                )
            )
    return targets


def select_random_target(candidates: Sequence[ConfigTarget], rng: random.Random) -> Optional[ConfigTarget]:
    """从候选池里随机选择一个目标。

    候选池顺序来自源 JSON 中 node/deviceGroup 和 config key 的原始顺序。后续如果
    需要优先选择靠前或靠后的 key，可以新增选择器复用这个有序候选池，不需要改
    样本构造和遮挡逻辑。
    """
    return rng.choice(candidates) if candidates else None


TARGET_SELECTORS: Dict[str, TargetSelector] = {
    # 新增目标选择策略时在这里注册，命令行 --selector 会自动暴露可选项。
    "random": select_random_target,
}


def get_target_object(graph: Dict[str, Any], target: ConfigTarget) -> Dict[str, Any]:
    """根据 ConfigTarget 找到包含目标 key 的 config 对象。"""

    if target.source_kind == "node":
        owner = graph["nodes"][target.owner_index]
        return owner[target.config_field][target.config_index]
    if target.source_kind == "device_group":
        owner = graph["deviceGroups"][target.owner_index]
        return owner[target.config_field][target.config_index]
    raise ValueError(f"unsupported target source_kind: {target.source_kind}")


def get_target_config_list(graph: Dict[str, Any], target: ConfigTarget) -> List[Any]:
    """根据 ConfigTarget 找到目标所属的 config/configs 列表。"""

    if target.source_kind == "node":
        return graph["nodes"][target.owner_index][target.config_field]
    if target.source_kind == "device_group":
        return graph["deviceGroups"][target.owner_index][target.config_field]
    raise ValueError(f"unsupported target source_kind: {target.source_kind}")


def remove_random_key(graph: Dict[str, Any], target: ConfigTarget) -> Dict[str, Any]:
    """复制原图，并从 input 中删除被选中的顶层配置 key。

    当前遮挡方式不额外插入占位符。若目标 key 所在 config 对象因此变成空 dict，
    继续保留这个空对象没有有效上下文含义，所以把它从 config/configs 列表移除。
    """

    # 一定在深拷贝上操作，保证 output 仍能从原图取到完整配置内容。
    masked_graph = copy.deepcopy(graph)
    target_object = get_target_object(masked_graph, target)
    target_object.pop(target.config_key)
    if not target_object:
        config_list = get_target_config_list(masked_graph, target)
        config_list.pop(target.config_index)
    return masked_graph


MASK_STRATEGIES: Dict[str, MaskStrategy] = {
    # 后续可在这里注册占位符遮挡、字段级遮挡等策略。
    "remove_random_key": remove_random_key,
}


TASK_DIRS = {
    "node": "node_config_qa",
    "device_group": "device_config_qa",
}


def target_output(graph: Dict[str, Any], target: ConfigTarget) -> Dict[str, Any]:
    """从未遮挡的原图中提取监督目标。"""

    target_object = get_target_object(graph, target)
    return {target.config_key: copy.deepcopy(target_object[target.config_key])}


def prompt_for_target(target: ConfigTarget) -> str:
    """根据目标来源生成对应任务提示词。"""

    if target.source_kind == "node":
        node_hint = f"节点 id 为 {target.node_id} 的" if target.node_id else "指定节点的"
        return (
            f"请根据给定网络图上下文预测{node_hint}节点配置 {target.config_key}。"
            "只输出该配置对象的 JSON，保持顶层配置名和 JSON 结构。"
        )
    if target.source_kind == "device_group":
        group_hint = ""
        if target.device_group_name:
            group_hint = f"设备组 {target.device_group_name} 的"
        return (
            f"请根据给定网络图上下文预测{group_hint}全局设备配置 {target.config_key}。"
            "只输出该配置对象的 JSON，保持顶层配置名和 JSON 结构。"
        )
    raise ValueError(f"unsupported target source_kind: {target.source_kind}")


def target_metadata(target: ConfigTarget) -> Dict[str, Any]:
    """把目标定位信息写入样本，便于回溯原始 JSON。"""

    metadata: Dict[str, Any] = {
        "source_kind": target.source_kind,
        "owner_index": target.owner_index,
        "config_index": target.config_index,
        "config_field": target.config_field,
        "config_key": target.config_key,
    }
    if target.node_id is not None:
        metadata["node_id"] = target.node_id
    if target.device_group_name is not None:
        metadata["device_group_name"] = target.device_group_name
    if target.device_group_type is not None:
        metadata["device_group_type"] = target.device_group_type
    return metadata


def build_sample(
    graph: Dict[str, Any],
    split: str,
    source_file: str,
    target: ConfigTarget,
    mask_strategy_name: str,
    mask_strategy: MaskStrategy,
    pruning_metadata: Dict[str, Any],
) -> Dict[str, Any]:
    """构造一条训练样本。

    prompt 描述要预测什么，input 是遮挡后的完整图上下文，output 是被遮挡的
    单个配置顶层对象，metadata 用于调试和溯源，不承担模型输入职责。
    """

    return {
        "prompt": prompt_for_target(target),
        "input": mask_strategy(graph, target),
        "output": target_output(graph, target),
        "metadata": {
            "split": split,
            "source_file": source_file,
            "mask_strategy": mask_strategy_name,
            "context_pruning": pruning_metadata,
            "target": target_metadata(target),
        },
    }


def write_json(path: Path, data: Any) -> None:
    """写格式化 JSON，并保留 dict 当前字段顺序。

    Python 读取 JSON 后会保留源文件中的对象 key 顺序。这里不要开启 sort_keys，
    否则 input 内原图字段会被按字典序重排，人工和原始 JSON 对照会很困难。
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    """将问题清单逐行写成 JSONL。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def output_path_for_sample(output_dir: Path, split: str, source_kind: str, source_file: str) -> Path:
    """根据 split、任务类型和原始文件名确定单样本输出路径。"""

    task_dir = TASK_DIRS[source_kind]
    return output_dir / split / task_dir / Path(source_file).name


def ensure_split_task_dirs(output_dir: Path, splits: Iterable[str]) -> None:
    """预先创建 QA/<split>/<task_dir>/ 目录。"""

    for split in splits:
        for task_dir in TASK_DIRS.values():
            (output_dir / split / task_dir).mkdir(parents=True, exist_ok=True)


def pruning_metadata(prune_result: PruneResult, max_input_tokens: int) -> Dict[str, Any]:
    """整理写入样本和 summary 的裁剪字段。"""

    return {
        "max_input_tokens": max_input_tokens,
        "center_node_id": prune_result.center_node_id,
        "original_token_estimate": prune_result.original_token_estimate,
        "final_token_estimate": prune_result.final_token_estimate,
        "original_node_count": prune_result.original_node_count,
        "final_node_count": prune_result.final_node_count,
        "removed_node_count": prune_result.removed_node_count,
        "pruned": prune_result.pruned,
        "still_over_limit": prune_result.still_over_limit,
    }


def build_split_samples(
    dataset_root: Path,
    output_dir: Path,
    split: str,
    split_files: List[Path],
    rng: random.Random,
    selector: TargetSelector,
    mask_strategy_name: str,
    mask_strategy: MaskStrategy,
    progress_interval: int,
    max_input_tokens: int,
) -> Tuple[List[BuildIssue], Counter[str]]:
    """构造单个 split 的样本和统计信息。

    对每张图分别建立 node 与 device_group 两个候选池，再各选一个目标，因此
    当前每个源 JSON 最多产出两个样本；如果某一类没有候选 key，则只产出另一类。
    """

    issues: List[BuildIssue] = []
    counts: Counter[str] = Counter()
    used_output_paths: Set[Path] = set()
    total_files = len(split_files)
    started_at = time.time()

    if progress_interval > 0:
        print("[%s] start: %s files" % (split, total_files), flush=True)
        if total_files == 0:
            print("[%s] 0/0 files (100.00%%), elapsed 0.0s, 0.00 files/s, eta 0.0s, samples 0" % split, flush=True)

    for file_index, path in enumerate(split_files, start=1):
        counts["files"] += 1
        source_file = str(path.relative_to(dataset_root))
        graph, load_detail = load_graph(path)
        if graph is None:
            counts["skipped_bad_graph"] += 1
            issues.append(BuildIssue(split, source_file, "bad_graph", load_detail))
            continue

        prune_result = prune_graph_to_token_limit(graph, rng, max_input_tokens)
        graph = prune_result.graph
        graph_pruning_metadata = pruning_metadata(prune_result, max_input_tokens)
        counts["original_token_estimate_total"] += prune_result.original_token_estimate
        counts["final_token_estimate_total"] += prune_result.final_token_estimate
        counts["original_node_count_total"] += prune_result.original_node_count
        counts["final_node_count_total"] += prune_result.final_node_count
        counts["removed_node_count_total"] += prune_result.removed_node_count
        if prune_result.pruned:
            counts["pruned_graphs"] += 1
        if prune_result.still_over_limit:
            counts["graphs_still_over_limit"] += 1
            issues.append(
                BuildIssue(
                    split,
                    source_file,
                    "graph_still_over_token_limit",
                    json.dumps(graph_pruning_metadata, ensure_ascii=False),
                )
            )

        # 分开建池可以控制 node/deviceGroup 两类任务的产样粒度。默认规则是每类
        # 随机取一个，而不是把两类目标混到一个池里后只取一个。
        source_pools = {
            "node": collect_node_targets(graph),
            "device_group": collect_device_group_targets(graph),
        }
        for source_kind, candidates in source_pools.items():
            counts[f"{source_kind}_candidate_keys"] += len(candidates)
            target = selector(candidates, rng)
            if target is None:
                counts[f"{source_kind}_graphs_without_target"] += 1
                continue
            sample = build_sample(
                graph,
                split,
                source_file,
                target,
                mask_strategy_name,
                mask_strategy,
                graph_pruning_metadata,
            )
            sample_path = output_path_for_sample(output_dir, split, source_kind, source_file)
            if sample_path in used_output_paths:
                counts["output_name_collisions"] += 1
                issues.append(BuildIssue(split, source_file, "output_name_collision", str(sample_path)))
                continue
            used_output_paths.add(sample_path)
            write_json(sample_path, sample)
            counts[f"{source_kind}_samples"] += 1
            counts["samples"] += 1

        if progress_interval > 0 and (file_index % progress_interval == 0 or file_index == total_files):
            elapsed = max(0.001, time.time() - started_at)
            speed = file_index / elapsed
            remaining = max(0, total_files - file_index)
            eta = remaining / speed if speed > 0 else 0
            percent = (file_index / total_files * 100) if total_files else 100
            print(
                "[%s] %s/%s files (%.2f%%), elapsed %.1fs, %.2f files/s, eta %.1fs, samples %s"
                % (split, file_index, total_files, percent, elapsed, speed, eta, counts["samples"]),
                flush=True,
            )

    return issues, counts


def build_dataset(
    dataset_root: Path,
    output_dir: Path,
    splits: List[str],
    seed: int,
    selector_name: str,
    mask_strategy_name: str,
    progress_interval: int,
    max_input_tokens: int,
) -> None:
    """按 split 和任务类型生成 QA JSON、问题清单和构造摘要。"""

    selector = TARGET_SELECTORS[selector_name]
    mask_strategy = MASK_STRATEGIES[mask_strategy_name]
    output_dir.mkdir(parents=True, exist_ok=True)
    ensure_split_task_dirs(output_dir, splits)

    all_issues: List[Dict[str, Any]] = []
    summary: Dict[str, Any] = {
        "dataset_root": str(dataset_root),
        "output_dir": str(output_dir),
        "seed": seed,
        "selector": selector_name,
        "mask_strategy": mask_strategy_name,
        "max_input_tokens": max_input_tokens,
        "token_estimator": "rough_bpe",
        "missing_split_dirs": [split for split in splits if not (dataset_root / split).exists()],
        "splits": {},
    }

    for split_index, split in enumerate(splits):
        split_files = list_split_json_files(dataset_root, split)
        # 每个 split 有独立但可复现的随机流，避免前一个 split 文件数变化后影响
        # 后一个 split 的随机选择结果。
        split_rng = random.Random(seed + split_index)
        split_issues, split_counts = build_split_samples(
            dataset_root,
            output_dir,
            split,
            split_files,
            split_rng,
            selector,
            mask_strategy_name,
            mask_strategy,
            progress_interval,
            max_input_tokens,
        )
        all_issues.extend(
            {
                "split": issue.split,
                "file": issue.file,
                "issue": issue.issue,
                "detail": issue.detail,
            }
            for issue in split_issues
        )
        split_summary = dict(split_counts)
        files = split_counts.get("files", 0)
        if files:
            split_summary["original_token_estimate_mean"] = split_counts.get("original_token_estimate_total", 0) / files
            split_summary["final_token_estimate_mean"] = split_counts.get("final_token_estimate_total", 0) / files
            split_summary["original_node_count_mean"] = split_counts.get("original_node_count_total", 0) / files
            split_summary["final_node_count_mean"] = split_counts.get("final_node_count_total", 0) / files
        summary["splits"][split] = split_summary

    write_jsonl(output_dir / "build_issues.jsonl", all_issues)
    write_json(output_dir / "build_summary.json", summary)


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""

    parser = argparse.ArgumentParser(description="Build config generation QA JSON files from graph JSON datasets.")
    parser.add_argument(
        "dataset_root",
        nargs="?",
        type=Path,
        default=DEFAULT_DATASET_ROOT,
        help=f"Dataset root containing train/ and val/ directories. Default: {DEFAULT_DATASET_ROOT}",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Directory for generated QA data. Default: {DEFAULT_OUTPUT_DIR}",
    )
    parser.add_argument("--splits", nargs="+", default=["train", "val"], help="Split directory names to build.")
    parser.add_argument("--seed", type=int, default=DEFAULT_RANDOM_SEED, help="Seed for deterministic target selection.")
    parser.add_argument(
        "--selector",
        choices=sorted(TARGET_SELECTORS),
        default="random",
        help="Target key selector. New selection policies can be registered in TARGET_SELECTORS.",
    )
    parser.add_argument(
        "--mask-strategy",
        choices=sorted(MASK_STRATEGIES),
        default="remove_random_key",
        help="How the selected config key is hidden from input.",
    )
    parser.add_argument(
        "--progress-interval",
        type=int,
        default=DEFAULT_PROGRESS_INTERVAL,
        help="Print progress every N source JSON files. Use 0 to disable. Default: %(default)s",
    )
    parser.add_argument(
        "--max-input-tokens",
        type=int,
        default=DEFAULT_MAX_INPUT_TOKENS,
        help=(
            "Rough token limit for graph context before QA construction. "
            "Use 0 to disable pruning. Default: %(default)s"
        ),
    )
    return parser.parse_args()


def main() -> None:
    """脚本入口。"""

    args = parse_args()
    build_dataset(
        args.dataset_root,
        args.output_dir,
        args.splits,
        args.seed,
        args.selector,
        args.mask_strategy,
        args.progress_interval,
        args.max_input_tokens,
    )
    print(f"Wrote config generation data to {args.output_dir}")


if __name__ == "__main__":
    main()
