#!/usr/bin/env python3
"""按正则查找 node/deviceGroup 配置中的 VLAN Key，并输出源码行号和配置层级。"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator


DEFAULT_DATASET_ROOT = Path("datasets")
DEFAULT_OUTPUT_ROOT = Path("vlan-config-analysis")
DEFAULT_SPLITS = ("train", "val")
DEFAULT_VLAN_PATTERN = r"(?i)vlan"
DEFAULT_PROGRESS_INTERVAL = 100
DEFAULT_MAX_VALUE_LENGTH = 1000
DEFAULT_MAX_SOURCE_LINE_LENGTH = 1000

SUMMARY_FILE = "vlan_analysis_summary.csv"
KEY_SUMMARY_FILE = "vlan_key_summary.csv"
ERROR_FILE = "analysis_errors.jsonl"

JSON_KEY_PATTERN = re.compile(r'(?P<key>"(?:\\.|[^"\\])*")\s*:')


@dataclass(frozen=True)
class KeyLocation:
    line_number: int
    source_line: str


@dataclass(frozen=True)
class ConfigRoot:
    scope: str
    owner: str
    field_name: str
    config_index: int | None
    top_level_key: str
    value: Any
    key_path: tuple[str | int, ...]
    display_prefix: tuple[str, ...]


@dataclass(frozen=True)
class VlanMatch:
    split: str
    source_file: str
    line_number: int | None
    source_line: str
    scope: str
    owner: str
    field_name: str
    top_level_key: str
    hierarchy: str
    parent_hierarchy: str
    matched_key: str
    matched_value: Any
    json_path: str


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
        help="逐文件 TXT 和汇总输出目录，默认: %(default)s",
    )
    parser.add_argument(
        "--splits",
        nargs="+",
        default=list(DEFAULT_SPLITS),
        help="处理的数据划分，默认: train val",
    )
    parser.add_argument(
        "--vlan-pattern",
        default=DEFAULT_VLAN_PATTERN,
        help="匹配配置 Key 的正则表达式，默认: %(default)s",
    )
    parser.add_argument(
        "--progress-interval",
        type=int,
        default=DEFAULT_PROGRESS_INTERVAL,
        help="每处理 N 个文件打印进度，0 表示关闭",
    )
    parser.add_argument(
        "--max-value-length",
        type=int,
        default=DEFAULT_MAX_VALUE_LENGTH,
        help="TXT 中匹配值的最大字符数，0 表示不限制",
    )
    parser.add_argument(
        "--max-source-line-length",
        type=int,
        default=DEFAULT_MAX_SOURCE_LINE_LENGTH,
        help="TXT 中原始源码行的最大字符数，0 表示不限制",
    )
    args = parser.parse_args()
    if args.progress_interval < 0:
        parser.error("--progress-interval 不能小于 0")
    if args.max_value_length < 0 or args.max_source_line_length < 0:
        parser.error("最大字符数不能小于 0")
    try:
        re.compile(args.vlan_pattern)
    except re.error as error:
        parser.error(f"--vlan-pattern 不是合法正则: {error}")
    return args


def iter_json_files(dataset_root: Path, split: str) -> list[Path]:
    split_root = dataset_root / split
    if not split_root.is_dir():
        return []
    return sorted(path for path in split_root.rglob("*.json") if path.is_file())


def truncate(text: str, limit: int) -> str:
    if limit == 0 or len(text) <= limit:
        return text
    omitted = len(text) - limit
    return f"{text[:limit]} ... <省略 {omitted} 个字符>"


def decode_key_token(token: str) -> str:
    value = json.loads(token)
    if not isinstance(value, str):
        raise ValueError("JSON key token did not decode to string")
    return value


def scan_key_locations(raw_text: str) -> list[tuple[str, KeyLocation]]:
    lines = raw_text.splitlines()
    locations: list[tuple[str, KeyLocation]] = []
    line_number = 1
    previous_end = 0
    for match in JSON_KEY_PATTERN.finditer(raw_text):
        line_number += raw_text.count("\n", previous_end, match.start("key"))
        previous_end = match.start("key")
        source_line = lines[line_number - 1].strip() if lines else ""
        locations.append(
            (
                decode_key_token(match.group("key")),
                KeyLocation(line_number=line_number, source_line=source_line),
            )
        )
    return locations


def walk_object_keys(
    value: Any,
    path: tuple[str | int, ...] = (),
) -> Iterator[tuple[tuple[str | int, ...], str]]:
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            key_path = (*path, key_text)
            yield key_path, key_text
            yield from walk_object_keys(child, key_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk_object_keys(child, (*path, index))


def build_location_map(
    raw_text: str,
    document: dict[str, Any],
) -> tuple[dict[tuple[str | int, ...], KeyLocation], str]:
    source_keys = scan_key_locations(raw_text)
    parsed_keys = list(walk_object_keys(document))
    if len(source_keys) != len(parsed_keys):
        return {}, (
            "源码 Key 数量与解析后 Key 数量不一致，可能存在重复 JSON Key："
            f"source={len(source_keys)}, parsed={len(parsed_keys)}"
        )

    location_by_path: dict[tuple[str | int, ...], KeyLocation] = {}
    for (path, parsed_key), (source_key, location) in zip(parsed_keys, source_keys):
        if parsed_key != source_key:
            return {}, (
                "源码 Key 顺序与解析结构不一致："
                f"path={format_json_path(path)}, parsed={parsed_key!r}, "
                f"source={source_key!r}"
            )
        location_by_path[path] = location
    return location_by_path, ""


def config_container_items(value: Any) -> list[tuple[int | None, dict[str, Any]]]:
    if isinstance(value, list):
        return [
            (index, item)
            for index, item in enumerate(value)
            if isinstance(item, dict)
        ]
    if isinstance(value, dict):
        return [(None, value)]
    return []


def node_owner(node: dict[str, Any], node_index: int) -> str:
    node_id = node.get("id")
    return str(node_id) if node_id is not None else f"nodes[{node_index}]"


def group_owner(group: dict[str, Any], group_index: int) -> str:
    group_data = group.get("deviceGroup")
    if isinstance(group_data, dict):
        name = group_data.get("NAME")
        if name is not None and str(name).strip():
            return str(name)
    return f"deviceGroups[{group_index}]"


def iter_config_roots(document: dict[str, Any]) -> Iterator[ConfigRoot]:
    nodes = document.get("nodes")
    if isinstance(nodes, list):
        for node_index, node in enumerate(nodes):
            if not isinstance(node, dict):
                continue
            owner = node_owner(node, node_index)
            for field_name in ("configs", "config"):
                for config_index, config in config_container_items(node.get(field_name)):
                    container_path: tuple[str | int, ...] = (
                        "nodes",
                        node_index,
                        field_name,
                    )
                    display_container = f"{field_name}"
                    if config_index is not None:
                        container_path = (*container_path, config_index)
                        display_container += f"[{config_index}]"
                    for top_key, value in config.items():
                        yield ConfigRoot(
                            scope="node",
                            owner=owner,
                            field_name=field_name,
                            config_index=config_index,
                            top_level_key=str(top_key),
                            value=value,
                            key_path=(*container_path, str(top_key)),
                            display_prefix=(str(top_key),),
                        )

    groups = document.get("deviceGroups")
    if isinstance(groups, list):
        for group_index, group in enumerate(groups):
            if not isinstance(group, dict):
                continue
            owner = group_owner(group, group_index)
            for config_index, config in config_container_items(group.get("configs")):
                container_path = ("deviceGroups", group_index, "configs")
                if config_index is not None:
                    container_path = (*container_path, config_index)
                for top_key, value in config.items():
                    yield ConfigRoot(
                        scope="deviceGroup",
                        owner=owner,
                        field_name="configs",
                        config_index=config_index,
                        top_level_key=str(top_key),
                        value=value,
                        key_path=(*container_path, str(top_key)),
                        display_prefix=(str(top_key),),
                    )


def format_json_path(path: tuple[str | int, ...]) -> str:
    parts: list[str] = []
    for value in path:
        if isinstance(value, int):
            if parts:
                parts[-1] += f"[{value}]"
            else:
                parts.append(f"[{value}]")
        else:
            parts.append(value)
    return ".".join(parts)


def hierarchy_text(parts: tuple[str, ...]) -> str:
    return " > ".join(parts)


def list_hierarchy(parts: tuple[str, ...], index: int) -> tuple[str, ...]:
    if not parts:
        return (f"[{index}]",)
    return (*parts[:-1], f"{parts[-1]}[{index}]")


def find_matches_in_value(
    value: Any,
    key_path: tuple[str | int, ...],
    hierarchy: tuple[str, ...],
    pattern: re.Pattern[str],
    root: ConfigRoot,
    split: str,
    source_file: str,
    location_by_path: dict[tuple[str | int, ...], KeyLocation],
) -> Iterator[VlanMatch]:
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            child_path = (*key_path, key_text)
            child_hierarchy = (*hierarchy, key_text)
            if pattern.search(key_text):
                location = location_by_path.get(child_path)
                yield VlanMatch(
                    split=split,
                    source_file=source_file,
                    line_number=location.line_number if location else None,
                    source_line=location.source_line if location else "",
                    scope=root.scope,
                    owner=root.owner,
                    field_name=root.field_name,
                    top_level_key=root.top_level_key,
                    hierarchy=hierarchy_text(child_hierarchy),
                    parent_hierarchy=hierarchy_text(hierarchy),
                    matched_key=key_text,
                    matched_value=child,
                    json_path=format_json_path(child_path),
                )
            yield from find_matches_in_value(
                child,
                child_path,
                child_hierarchy,
                pattern,
                root,
                split,
                source_file,
                location_by_path,
            )
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from find_matches_in_value(
                child,
                (*key_path, index),
                list_hierarchy(hierarchy, index),
                pattern,
                root,
                split,
                source_file,
                location_by_path,
            )


def find_vlan_matches(
    document: dict[str, Any],
    split: str,
    source_file: str,
    pattern: re.Pattern[str],
    location_by_path: dict[tuple[str | int, ...], KeyLocation],
) -> list[VlanMatch]:
    matches: list[VlanMatch] = []
    for root in iter_config_roots(document):
        if pattern.search(root.top_level_key):
            location = location_by_path.get(root.key_path)
            matches.append(
                VlanMatch(
                    split=split,
                    source_file=source_file,
                    line_number=location.line_number if location else None,
                    source_line=location.source_line if location else "",
                    scope=root.scope,
                    owner=root.owner,
                    field_name=root.field_name,
                    top_level_key=root.top_level_key,
                    hierarchy=root.top_level_key,
                    parent_hierarchy="<配置根>",
                    matched_key=root.top_level_key,
                    matched_value=root.value,
                    json_path=format_json_path(root.key_path),
                )
            )
        matches.extend(
            find_matches_in_value(
                root.value,
                root.key_path,
                root.display_prefix,
                pattern,
                root,
                split,
                source_file,
                location_by_path,
            )
        )
    return sorted(
        matches,
        key=lambda item: (
            item.line_number is None,
            item.line_number if item.line_number is not None else 0,
            item.json_path,
        ),
    )


def value_text(value: Any, max_length: int) -> str:
    text = json.dumps(value, ensure_ascii=False, indent=2)
    return truncate(text, max_length)


def render_txt(
    split: str,
    source_file: str,
    matches: list[VlanMatch],
    location_warning: str,
    max_value_length: int,
    max_source_line_length: int,
) -> str:
    owners = {(item.scope, item.owner) for item in matches}
    lines = [
        f"文件：{split}/{source_file}",
        f"VLAN 匹配数量：{len(matches)}",
        f"涉及设备数量：{len(owners)}",
    ]
    if location_warning:
        lines.extend((f"行号定位警告：{location_warning}", ""))
    else:
        lines.append("")

    if not matches:
        lines.append("未发现 Key 名中包含 VLAN 的节点或设备组配置。")
        return "\n".join(lines) + "\n"

    for index, item in enumerate(matches, start=1):
        lines.extend(
            (
                "=" * 72,
                f"记录 {index}",
                "=" * 72,
                f"原始行号：{item.line_number if item.line_number is not None else '<unknown>'}",
                f"设备类型：{item.scope}",
                f"设备名称：{item.owner}",
                f"配置字段：{item.field_name}",
                f"顶层配置名：{item.top_level_key}",
                f"配置层级：{item.hierarchy}",
                f"上层配置：{item.parent_hierarchy}",
                f"匹配字段：{item.matched_key}",
                f"JSON 路径：{item.json_path}",
                "匹配内容：",
                value_text(item.matched_value, max_value_length),
                "原始内容：",
                truncate(item.source_line, max_source_line_length)
                if item.source_line
                else "<unknown>",
                "",
            )
        )
    return "\n".join(lines)


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def append_error(path: Path, error: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(error, ensure_ascii=False) + "\n")


def run(args: argparse.Namespace) -> None:
    dataset_root = args.dataset_root.resolve()
    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    error_path = output_root / ERROR_FILE
    if error_path.exists():
        error_path.unlink()
    pattern = re.compile(args.vlan_pattern)

    summary_rows: list[dict[str, Any]] = []
    all_matches: list[VlanMatch] = []
    total_files = sum(
        len(iter_json_files(dataset_root, split)) for split in args.splits
    )
    processed = 0
    failed = 0

    for split in args.splits:
        files = iter_json_files(dataset_root, split)
        print(f"[{split}] found {len(files)} json files", flush=True)
        for source_path in files:
            processed += 1
            relative_path = source_path.relative_to(dataset_root / split)
            txt_path = output_root / split / relative_path.with_suffix(".txt")
            txt_path.parent.mkdir(parents=True, exist_ok=True)
            status = True
            error_text = ""
            location_warning = ""
            matches: list[VlanMatch] = []
            try:
                raw_text = source_path.read_text(encoding="utf-8")
                document = json.loads(raw_text)
                if not isinstance(document, dict):
                    raise ValueError(
                        f"JSON 顶层必须是对象，实际为 {type(document).__name__}"
                    )
                location_by_path, location_warning = build_location_map(
                    raw_text,
                    document,
                )
                matches = find_vlan_matches(
                    document,
                    split,
                    str(relative_path),
                    pattern,
                    location_by_path,
                )
                txt_content = render_txt(
                    split,
                    str(relative_path),
                    matches,
                    location_warning,
                    args.max_value_length,
                    args.max_source_line_length,
                )
            except Exception as error:  # noqa: BLE001 - 坏文件生成错误 TXT 后继续。
                status = False
                failed += 1
                error_text = f"{type(error).__name__}: {error}"
                txt_content = (
                    f"文件：{split}/{relative_path}\n"
                    "分析状态：失败\n"
                    f"错误：{error_text}\n"
                )
                append_error(
                    error_path,
                    {
                        "split": split,
                        "source_file": str(relative_path),
                        "error": error_text,
                    },
                )
            txt_path.write_text(txt_content, encoding="utf-8")
            all_matches.extend(matches)
            owners = {(item.scope, item.owner) for item in matches}
            summary_rows.append(
                {
                    "split": split,
                    "source_file": str(relative_path),
                    "output_file": str(txt_path.relative_to(output_root)),
                    "status": status,
                    "vlan_match_count": len(matches),
                    "owner_count": len(owners),
                    "line_mapping_warning": location_warning,
                    "error": error_text,
                }
            )

            if args.progress_interval > 0 and (
                processed % args.progress_interval == 0 or processed == total_files
            ):
                print(
                    f"进度 {processed}/{total_files}，失败 {failed}，"
                    f"VLAN 匹配 {len(all_matches)}",
                    flush=True,
                )

    write_csv(
        output_root / SUMMARY_FILE,
        [
            "split",
            "source_file",
            "output_file",
            "status",
            "vlan_match_count",
            "owner_count",
            "line_mapping_warning",
            "error",
        ],
        summary_rows,
    )

    key_counts = Counter(item.matched_key for item in all_matches)
    key_files: dict[str, set[tuple[str, str]]] = defaultdict(set)
    key_owners: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for item in all_matches:
        key_files[item.matched_key].add((item.split, item.source_file))
        key_owners[item.matched_key].add((item.scope, item.owner))
    key_rows = [
        {
            "matched_key": key,
            "match_count": count,
            "file_count": len(key_files[key]),
            "owner_count": len(key_owners[key]),
        }
        for key, count in sorted(key_counts.items(), key=lambda item: (-item[1], item[0]))
    ]
    write_csv(
        output_root / KEY_SUMMARY_FILE,
        ["matched_key", "match_count", "file_count", "owner_count"],
        key_rows,
    )
    print(
        f"完成：处理 {processed} 个文件，失败 {failed}，"
        f"VLAN 匹配 {len(all_matches)}；输出：{output_root}",
        flush=True,
    )


if __name__ == "__main__":
    run(parse_args())
