#!/usr/bin/env python3
"""Build JSONL samples for config generation from graph JSON datasets."""

from __future__ import annotations

import argparse
import copy
import json
import random
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence


# Local defaults. The expected input layout is:
# datasets/train/*.json
# datasets/val/*.json
DEFAULT_DATASET_ROOT = Path("datasets")
DEFAULT_OUTPUT_DIR = Path("/tmp/config_generation_dataset")
DEFAULT_RANDOM_SEED = 20260522


@dataclass(frozen=True)
class ConfigTarget:
    source_kind: str
    owner_index: int
    config_index: int
    config_key: str
    node_id: str | None = None
    device_group_name: str | None = None
    device_group_type: str | None = None


@dataclass(frozen=True)
class BuildIssue:
    split: str
    file: str
    issue: str
    detail: str = ""


TargetSelector = Callable[[Sequence[ConfigTarget], random.Random], ConfigTarget | None]
MaskStrategy = Callable[[dict[str, Any], ConfigTarget], dict[str, Any]]


def iter_json_files(dataset_root: Path, splits: Iterable[str]) -> Iterable[tuple[str, Path]]:
    for split in splits:
        split_dir = dataset_root / split
        if not split_dir.exists():
            continue
        for path in sorted(split_dir.rglob("*.json")):
            if path.is_file():
                yield split, path


def load_graph(path: Path) -> tuple[dict[str, Any] | None, str]:
    try:
        graph = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - bad source files are recorded and skipped.
        return None, str(exc)
    if not isinstance(graph, dict):
        return None, f"top-level JSON type is {type(graph).__name__}, expected object"
    return graph, ""


def top_level_config_keys(config_items: Any) -> Iterable[tuple[int, str]]:
    if not isinstance(config_items, list):
        return
    for config_index, config_item in enumerate(config_items):
        if not isinstance(config_item, dict):
            continue
        for config_key in config_item:
            yield config_index, str(config_key)


def collect_node_targets(graph: dict[str, Any]) -> list[ConfigTarget]:
    targets: list[ConfigTarget] = []
    nodes = graph.get("nodes")
    if not isinstance(nodes, list):
        return targets

    for node_index, node in enumerate(nodes):
        if not isinstance(node, dict):
            continue
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


def collect_device_group_targets(graph: dict[str, Any]) -> list[ConfigTarget]:
    targets: list[ConfigTarget] = []
    device_groups = graph.get("deviceGroups")
    if not isinstance(device_groups, list):
        return targets

    for device_group_index, device_group_item in enumerate(device_groups):
        if not isinstance(device_group_item, dict):
            continue
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


def select_random_target(candidates: Sequence[ConfigTarget], rng: random.Random) -> ConfigTarget | None:
    """Select one target from an ordered pool.

    Future selectors that prefer earlier or later config keys can reuse the same
    ordered candidate pool without changing sample building or mask strategies.
    """
    return rng.choice(candidates) if candidates else None


TARGET_SELECTORS: dict[str, TargetSelector] = {
    "random": select_random_target,
}


def get_target_object(graph: dict[str, Any], target: ConfigTarget) -> dict[str, Any]:
    if target.source_kind == "node":
        owner = graph["nodes"][target.owner_index]
        return owner["config"][target.config_index]
    if target.source_kind == "device_group":
        owner = graph["deviceGroups"][target.owner_index]
        return owner["configs"][target.config_index]
    raise ValueError(f"unsupported target source_kind: {target.source_kind}")


def get_target_config_list(graph: dict[str, Any], target: ConfigTarget) -> list[Any]:
    if target.source_kind == "node":
        return graph["nodes"][target.owner_index]["config"]
    if target.source_kind == "device_group":
        return graph["deviceGroups"][target.owner_index]["configs"]
    raise ValueError(f"unsupported target source_kind: {target.source_kind}")


def remove_target_key(graph: dict[str, Any], target: ConfigTarget) -> dict[str, Any]:
    """Remove only the selected config top-level key from a copied graph."""
    masked_graph = copy.deepcopy(graph)
    target_object = get_target_object(masked_graph, target)
    target_object.pop(target.config_key)
    if not target_object:
        config_list = get_target_config_list(masked_graph, target)
        config_list.pop(target.config_index)
    return masked_graph


MASK_STRATEGIES: dict[str, MaskStrategy] = {
    "remove_target_key": remove_target_key,
}


def target_output(graph: dict[str, Any], target: ConfigTarget) -> dict[str, Any]:
    target_object = get_target_object(graph, target)
    return {target.config_key: copy.deepcopy(target_object[target.config_key])}


def prompt_for_target(target: ConfigTarget) -> str:
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


def target_metadata(target: ConfigTarget) -> dict[str, Any]:
    metadata: dict[str, Any] = {
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
    graph: dict[str, Any],
    split: str,
    source_file: str,
    target: ConfigTarget,
    mask_strategy_name: str,
    mask_strategy: MaskStrategy,
) -> dict[str, Any]:
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


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def build_split_samples(
    dataset_root: Path,
    split: str,
    rng: random.Random,
    selector: TargetSelector,
    mask_strategy_name: str,
    mask_strategy: MaskStrategy,
) -> tuple[list[dict[str, Any]], list[BuildIssue], Counter[str]]:
    samples: list[dict[str, Any]] = []
    issues: list[BuildIssue] = []
    counts: Counter[str] = Counter()

    for _, path in iter_json_files(dataset_root, [split]):
        counts["files"] += 1
        source_file = str(path.relative_to(dataset_root))
        graph, load_detail = load_graph(path)
        if graph is None:
            counts["skipped_bad_graph"] += 1
            issues.append(BuildIssue(split, source_file, "bad_graph", load_detail))
            continue

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
            samples.append(build_sample(graph, split, source_file, target, mask_strategy_name, mask_strategy))
            counts[f"{source_kind}_samples"] += 1

    counts["samples"] = len(samples)
    return samples, issues, counts


def build_dataset(
    dataset_root: Path,
    output_dir: Path,
    splits: list[str],
    seed: int,
    selector_name: str,
    mask_strategy_name: str,
) -> None:
    selector = TARGET_SELECTORS[selector_name]
    mask_strategy = MASK_STRATEGIES[mask_strategy_name]
    output_dir.mkdir(parents=True, exist_ok=True)

    all_issues: list[dict[str, Any]] = []
    summary: dict[str, Any] = {
        "dataset_root": str(dataset_root),
        "output_dir": str(output_dir),
        "seed": seed,
        "selector": selector_name,
        "mask_strategy": mask_strategy_name,
        "missing_split_dirs": [split for split in splits if not (dataset_root / split).exists()],
        "splits": {},
    }

    for split_index, split in enumerate(splits):
        split_rng = random.Random(seed + split_index)
        split_samples, split_issues, split_counts = build_split_samples(
            dataset_root,
            split,
            split_rng,
            selector,
            mask_strategy_name,
            mask_strategy,
        )
        write_jsonl(output_dir / f"{split}.jsonl", split_samples)
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
    (output_dir / "build_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build config generation JSONL data from graph JSON datasets.")
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
        help=f"Directory for generated JSONL data. Default: {DEFAULT_OUTPUT_DIR}",
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
        default="remove_target_key",
        help="How the selected config key is hidden from input.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    build_dataset(args.dataset_root, args.output_dir, args.splits, args.seed, args.selector, args.mask_strategy)
    print(f"Wrote config generation data to {args.output_dir}")


if __name__ == "__main__":
    main()
