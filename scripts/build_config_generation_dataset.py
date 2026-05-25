#!/usr/bin/env python3
"""从图 JSON 数据集构造配置生成任务的 QA 样本。

当前任务粒度是预测一个 config 对象里的一个顶层 key：

- node 配置来自 ``nodes[].config[]``。
- deviceGroup 配置来自 ``deviceGroups[].configs[]``。
- 一个训练样本只遮挡一个顶层 key，目标输出也只包含该 key 对应的配置对象。

脚本把“选择哪个 key”与“怎样遮挡 key”拆成独立策略，后续可以在不改主流程
的前提下新增前部 key、后部 key 选择策略，或者新增占位符类遮挡策略。
"""

from __future__ import annotations

import argparse
import copy
import json
import random
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple


# 本地默认路径。输入数据集目录结构约定为：
# datasets/train/*.json
# datasets/val/*.json
# 如果真实数据在别的位置，可以改这里，也可以用命令行参数覆盖。
DEFAULT_DATASET_ROOT = Path("datasets")
DEFAULT_OUTPUT_DIR = Path("QA")
# 固定默认随机种子，保证同一份输入数据多次构造时随机选中的目标可复现。
DEFAULT_RANDOM_SEED = 20260522


@dataclass(frozen=True)
class ConfigTarget:
    """一个可被预测的配置顶层 key 的定位信息。

    owner_index 指向所属 node 或 deviceGroup 在原图 list 中的位置。
    config_index 指向所属 config/configs 列表中的对象位置。
    config_key 是真正需要遮挡和预测的顶层配置名。
    """

    source_kind: str
    owner_index: int
    config_index: int
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


# 目标选择器只关心“从候选池选谁”，不负责改图。
TargetSelector = Callable[[Sequence[ConfigTarget], random.Random], Optional[ConfigTarget]]
# 遮挡策略只关心“给定目标后如何生成 input”，不负责挑目标。
MaskStrategy = Callable[[Dict[str, Any], ConfigTarget], Dict[str, Any]]


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
        for config_index, config_key in top_level_config_keys(node.get("config")):
            targets.append(
                ConfigTarget(
                    source_kind="node",
                    owner_index=node_index,
                    config_index=config_index,
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
        return owner["config"][target.config_index]
    if target.source_kind == "device_group":
        owner = graph["deviceGroups"][target.owner_index]
        return owner["configs"][target.config_index]
    raise ValueError(f"unsupported target source_kind: {target.source_kind}")


def get_target_config_list(graph: Dict[str, Any], target: ConfigTarget) -> List[Any]:
    """根据 ConfigTarget 找到目标所属的 config/configs 列表。"""

    if target.source_kind == "node":
        return graph["nodes"][target.owner_index]["config"]
    if target.source_kind == "device_group":
        return graph["deviceGroups"][target.owner_index]["configs"]
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


def build_split_samples(
    dataset_root: Path,
    output_dir: Path,
    split: str,
    rng: random.Random,
    selector: TargetSelector,
    mask_strategy_name: str,
    mask_strategy: MaskStrategy,
) -> Tuple[List[BuildIssue], Counter[str]]:
    """构造单个 split 的样本和统计信息。

    对每张图分别建立 node 与 device_group 两个候选池，再各选一个目标，因此
    当前每个源 JSON 最多产出两个样本；如果某一类没有候选 key，则只产出另一类。
    """

    issues: List[BuildIssue] = []
    counts: Counter[str] = Counter()
    used_output_paths: Set[Path] = set()

    for _, path in iter_json_files(dataset_root, [split]):
        counts["files"] += 1
        source_file = str(path.relative_to(dataset_root))
        graph, load_detail = load_graph(path)
        if graph is None:
            counts["skipped_bad_graph"] += 1
            issues.append(BuildIssue(split, source_file, "bad_graph", load_detail))
            continue

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
            sample = build_sample(graph, split, source_file, target, mask_strategy_name, mask_strategy)
            sample_path = output_path_for_sample(output_dir, split, source_kind, source_file)
            if sample_path in used_output_paths:
                counts["output_name_collisions"] += 1
                issues.append(BuildIssue(split, source_file, "output_name_collision", str(sample_path)))
                continue
            used_output_paths.add(sample_path)
            write_json(sample_path, sample)
            counts[f"{source_kind}_samples"] += 1

    counts["samples"] = counts["node_samples"] + counts["device_group_samples"]
    return issues, counts


def build_dataset(
    dataset_root: Path,
    output_dir: Path,
    splits: List[str],
    seed: int,
    selector_name: str,
    mask_strategy_name: str,
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
        "missing_split_dirs": [split for split in splits if not (dataset_root / split).exists()],
        "splits": {},
    }

    for split_index, split in enumerate(splits):
        # 每个 split 有独立但可复现的随机流，避免前一个 split 文件数变化后影响
        # 后一个 split 的随机选择结果。
        split_rng = random.Random(seed + split_index)
        split_issues, split_counts = build_split_samples(
            dataset_root,
            output_dir,
            split,
            split_rng,
            selector,
            mask_strategy_name,
            mask_strategy,
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
        summary["splits"][split] = dict(split_counts)

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
    return parser.parse_args()


def main() -> None:
    """脚本入口。"""

    args = parse_args()
    build_dataset(args.dataset_root, args.output_dir, args.splits, args.seed, args.selector, args.mask_strategy)
    print(f"Wrote config generation data to {args.output_dir}")


if __name__ == "__main__":
    main()
