#!/usr/bin/env python3
"""匹配直连交换机链路两端的 LSW 接口配置。"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Optional


DEFAULT_DATASET_ROOT = Path("datasets")
DEFAULT_OUTPUT_FILE = Path("/tmp/lsw_link_interface_analysis.json")
DEFAULT_SPLIT = "all"
DEFAULT_CONFIG_FIELDS = ("configs",)
DEFAULT_PROGRESS_INTERVAL = 100

LSW_TYPE = "LSW"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "dataset_root",
        nargs="?",
        type=Path,
        default=DEFAULT_DATASET_ROOT,
        help="数据集根目录，目录下应包含 train/val，默认: %(default)s",
    )
    parser.add_argument(
        "-o",
        "--output-file",
        type=Path,
        default=DEFAULT_OUTPUT_FILE,
        help="单个分析结果 JSON 文件，默认: %(default)s",
    )
    parser.add_argument(
        "--split",
        choices=["train", "val", "all"],
        default=DEFAULT_SPLIT,
        help="分析 train、val 或全部数据，默认: %(default)s",
    )
    parser.add_argument(
        "--config-fields",
        nargs="+",
        default=list(DEFAULT_CONFIG_FIELDS),
        help="需要扫描的节点配置字段，默认只扫描 configs",
    )
    parser.add_argument(
        "--progress-interval",
        type=int,
        default=DEFAULT_PROGRESS_INTERVAL,
        help="每处理 N 个文件打印一次进度，0 表示关闭，默认: %(default)s",
    )
    args = parser.parse_args()
    if not args.config_fields or any(not field for field in args.config_fields):
        parser.error("--config-fields 至少需要一个非空字段名")
    if len(args.config_fields) != len(set(args.config_fields)):
        parser.error("--config-fields 不能包含重复字段名")
    if args.progress_interval < 0:
        parser.error("--progress-interval 不能小于 0")
    return args


def iter_json_files(dataset_root: Path, split: str) -> list[Path]:
    split_root = dataset_root / split
    if not split_root.is_dir():
        raise FileNotFoundError(f"数据划分目录不存在: {split_root}")
    return sorted(path for path in split_root.rglob("*.json") if path.is_file())


def load_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON 顶层必须是对象，实际为 {type(value).__name__}")
    return value


def object_items(value: Any) -> Iterable[tuple[int, dict[str, Any]]]:
    if isinstance(value, dict):
        yield 0, value
    elif isinstance(value, list):
        for index, item in enumerate(value):
            if isinstance(item, dict):
                yield index, item


def scalar_text(value: Any) -> Optional[str]:
    if value is None or isinstance(value, (dict, list, bool)):
        return None
    text = str(value).strip()
    return text or None


def node_device(node: dict[str, Any]) -> Optional[dict[str, Any]]:
    device = node.get("devices")
    if not isinstance(device, dict):
        device = node.get("device")
    return device if isinstance(device, dict) else None


def is_lsw_node(node: dict[str, Any]) -> bool:
    device = node_device(node)
    if device is None:
        return False
    device_type = scalar_text(device.get("TYPE"))
    return device_type is not None and device_type.upper() == LSW_TYPE


def collect_interface_configs(
    node: dict[str, Any],
    port_name: Optional[str],
    config_fields: list[str],
) -> tuple[str, list[dict[str, Any]], int]:
    """返回端口匹配状态、全部匹配结果及扫描到的接口对象数。"""

    scanned_count = 0
    matches: list[dict[str, Any]] = []
    for config_field in config_fields:
        for config_index, config in object_items(node.get(config_field)):
            businesses = config.get("lsw-interfaces-business")
            for business_index, business in object_items(businesses):
                interfaces = business.get("lsw-interface")
                for interface_index, interface in object_items(interfaces):
                    scanned_count += 1
                    interface_name = scalar_text(interface.get("interface-name"))
                    if port_name is None or interface_name != port_name:
                        continue
                    matches.append(
                        {
                            "config_field": config_field,
                            "config_index": config_index,
                            "business_index": business_index,
                            "interface_index": interface_index,
                            "interface_config": interface,
                        }
                    )

    if port_name is None:
        status = "port-missing"
    elif not matches:
        status = "interface-not-found"
    elif len(matches) == 1:
        status = "matched"
    else:
        status = "multiple-matches"
    return status, matches, scanned_count


def endpoint_result(
    node: dict[str, Any],
    port_value: Any,
    config_fields: list[str],
) -> dict[str, Any]:
    port_name = scalar_text(port_value)
    status, matches, scanned_count = collect_interface_configs(
        node,
        port_name,
        config_fields,
    )
    return {
        "node_id": node.get("id"),
        "device": node_device(node),
        "port": port_value,
        "interface_match_status": status,
        "scanned_interface_count": scanned_count,
        "interface_configs": matches,
    }


def analyze_graph(
    graph: dict[str, Any],
    split: str,
    source_file: str,
    source_relative_path: str,
    config_fields: list[str],
) -> tuple[list[dict[str, Any]], Counter[str]]:
    records: list[dict[str, Any]] = []
    counters: Counter[str] = Counter()
    nodes = graph.get("nodes")
    links = graph.get("links")
    if not isinstance(nodes, list):
        counters["files-with-nodes-not-list"] += 1
        return records, counters
    if not isinstance(links, list):
        counters["files-with-links-not-list"] += 1
        return records, counters

    node_by_id: dict[str, dict[str, Any]] = {}
    for node in nodes:
        if not isinstance(node, dict):
            counters["invalid-node-items"] += 1
            continue
        node_id = scalar_text(node.get("id"))
        if node_id is None:
            counters["nodes-without-id"] += 1
            continue
        if node_id in node_by_id:
            counters["duplicate-node-ids"] += 1
            continue
        node_by_id[node_id] = node

    counters["links"] += len(links)
    for link_index, link in enumerate(links):
        if not isinstance(link, dict):
            counters["invalid-link-items"] += 1
            continue
        source_id = scalar_text(link.get("source"))
        target_id = scalar_text(link.get("target"))
        source_node = node_by_id.get(source_id or "")
        target_node = node_by_id.get(target_id or "")
        if source_node is None or target_node is None:
            counters["links-with-unresolved-endpoints"] += 1
            continue
        if not (is_lsw_node(source_node) and is_lsw_node(target_node)):
            counters["non-lsw-to-lsw-links"] += 1
            continue

        link_attributes = link.get("link")
        if not isinstance(link_attributes, dict):
            link_attributes = {}
        left = endpoint_result(
            source_node,
            link_attributes.get("LEFTPORT"),
            config_fields,
        )
        right = endpoint_result(
            target_node,
            link_attributes.get("RIGHTPORT"),
            config_fields,
        )
        counters["lsw-to-lsw-links"] += 1
        counters[f"left-{left['interface_match_status']}"] += 1
        counters[f"right-{right['interface_match_status']}"] += 1
        if (
            left["interface_match_status"] == "matched"
            and right["interface_match_status"] == "matched"
        ):
            counters["links-with-both-interfaces-matched"] += 1
        else:
            counters["links-with-incomplete-interface-match"] += 1

        records.append(
            {
                "split": split,
                "source_file": source_file,
                "source_relative_path": source_relative_path,
                "link_index": link_index,
                "link": link,
                "left_node": left,
                "right_node": right,
            }
        )
    return records, counters


def counter_summary(counters: Counter[str]) -> dict[str, int]:
    keys = (
        "input-files",
        "valid-files",
        "invalid-files",
        "links",
        "lsw-to-lsw-links",
        "links-with-both-interfaces-matched",
        "links-with-incomplete-interface-match",
        "left-matched",
        "left-multiple-matches",
        "left-interface-not-found",
        "left-port-missing",
        "right-matched",
        "right-multiple-matches",
        "right-interface-not-found",
        "right-port-missing",
        "links-with-unresolved-endpoints",
        "non-lsw-to-lsw-links",
        "duplicate-node-ids",
        "nodes-without-id",
        "invalid-node-items",
        "invalid-link-items",
        "files-with-nodes-not-list",
        "files-with-links-not-list",
    )
    return {key.replace("-", "_"): counters[key] for key in keys}


def run(args: argparse.Namespace) -> dict[str, Any]:
    dataset_root = args.dataset_root.resolve()
    output_file = args.output_file.resolve()
    splits = ["train", "val"] if args.split == "all" else [args.split]
    all_records: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    total_counters: Counter[str] = Counter()
    by_split: dict[str, dict[str, int]] = {}

    for split in splits:
        split_root = dataset_root / split
        files = iter_json_files(dataset_root, split)
        split_counters: Counter[str] = Counter()
        split_counters["input-files"] = len(files)
        started_at = time.time()
        for index, path in enumerate(files, start=1):
            relative_path = path.relative_to(split_root).as_posix()
            try:
                graph = load_json_object(path)
                records, counters = analyze_graph(
                    graph,
                    split,
                    path.name,
                    relative_path,
                    args.config_fields,
                )
                all_records.extend(records)
                split_counters.update(counters)
                split_counters["valid-files"] += 1
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
                split_counters["invalid-files"] += 1
                errors.append(
                    {
                        "split": split,
                        "source_file": path.name,
                        "source_relative_path": relative_path,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )

            if args.progress_interval and (
                index % args.progress_interval == 0 or index == len(files)
            ):
                elapsed = max(time.time() - started_at, 0.001)
                speed = index / elapsed
                eta = (len(files) - index) / speed if speed else 0.0
                print(
                    f"[{split}] {index}/{len(files)}，LSW 直连链路 "
                    f"{split_counters['lsw-to-lsw-links']}，"
                    f"双端匹配 {split_counters['links-with-both-interfaces-matched']}，"
                    f"预计剩余 {eta:.1f} 秒",
                    flush=True,
                )

        by_split[split] = counter_summary(split_counters)
        total_counters.update(split_counters)

    result = {
        "dataset_root": str(dataset_root),
        "splits": splits,
        "config_fields": args.config_fields,
        "matching_rule": {
            "link_filter": "both endpoint devices.TYPE values equal LSW",
            "left_endpoint": "link.source + link.link.LEFTPORT",
            "right_endpoint": "link.target + link.link.RIGHTPORT",
            "interface_field": (
                "nodes[].configs[].lsw-interfaces-business."
                "lsw-interface[].interface-name"
            ),
            "port_comparison": "trimmed exact string match",
        },
        "summary": {
            **counter_summary(total_counters),
            "by_split": by_split,
        },
        "errors": errors,
        "records": all_records,
    }
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"分析完成，结果已写入: {output_file}")
    return result


def main() -> None:
    run(parse_args())


if __name__ == "__main__":
    main()
