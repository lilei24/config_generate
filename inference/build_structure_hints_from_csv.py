#!/usr/bin/env python3
"""Build TOP_LEVEL_KEY_STRUCTURE_HINTS from output structure distribution CSV."""

from __future__ import annotations

import argparse
import csv
import pprint
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


DEFAULT_INPUT_CSV = Path("output-structure-analysis/output_structure_distribution.csv")
DEFAULT_OUTPUT_FILE = Path("top_level_key_structure_hints.py")
DEFAULT_MIN_SAMPLE_COUNT = 5
VALUE_PLACEHOLDER = "<VALUE>"
ARRAY_TOKEN = object()


@dataclass
class PathNode:
    children: Dict[Any, "PathNode"] = field(default_factory=dict)


def parse_csv_values(text: str) -> Set[str]:
    return {item.strip() for item in text.split(",") if item.strip()}


def unescape_path_key(key: str) -> str:
    return key.replace("~1", "/").replace("~0", "~")


def parse_path(path: str) -> Tuple[Any, ...]:
    """Parse paths emitted by analyze_output_structures.py."""

    if not path.startswith("/"):
        raise ValueError("path must start with '/': %s" % path)

    tokens: List[Any] = []
    for raw_segment in path[1:].split("/"):
        array_depth = 0
        while raw_segment.endswith("[]"):
            raw_segment = raw_segment[:-2]
            array_depth += 1
        if raw_segment:
            tokens.append(unescape_path_key(raw_segment))
        tokens.extend(ARRAY_TOKEN for _ in range(array_depth))
    return tuple(tokens)


def insert_path(root: PathNode, tokens: Iterable[Any]) -> None:
    node = root
    for token in tokens:
        node = node.children.setdefault(token, PathNode())


def path_tree(paths: Iterable[str]) -> PathNode:
    root = PathNode()
    for path in paths:
        normalized = path.strip()
        if normalized:
            insert_path(root, parse_path(normalized))
    return root


def node_to_value(node: PathNode) -> Any:
    """Convert a path trie into a JSON-like skeleton."""

    if ARRAY_TOKEN in node.children:
        array_node = node.children[ARRAY_TOKEN]
        # The path format cannot distinguish an empty array from an array of
        # primitive values. A single placeholder preserves the array shape.
        return [node_to_value(array_node)]

    object_children = [
        (str(key), child)
        for key, child in node.children.items()
        if key is not ARRAY_TOKEN
    ]
    if object_children:
        return {
            key: node_to_value(child)
            for key, child in sorted(object_children, key=lambda item: item[0])
        }
    return VALUE_PLACEHOLDER


def structure_from_paths(top_level_key: str, paths: Iterable[str]) -> Dict[str, Any]:
    tree = path_tree(paths)
    root_node = tree.children.get(top_level_key)
    if root_node is None:
        raise ValueError("paths do not contain top-level key %r" % top_level_key)
    return {top_level_key: node_to_value(root_node)}


def read_distribution_rows(
    input_csv: Path,
    min_sample_count: int,
    splits: Set[str],
    tasks: Set[str],
) -> List[Dict[str, str]]:
    with input_csv.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        required_fields = {
            "split",
            "task",
            "top_level_key",
            "structure_id",
            "sample_count",
            "paths",
        }
        missing_fields = required_fields - set(reader.fieldnames or [])
        if missing_fields:
            raise ValueError(
                "input CSV is missing required fields: %s"
                % ", ".join(sorted(missing_fields))
            )

        rows: List[Dict[str, str]] = []
        for row in reader:
            if splits and row["split"] not in splits:
                continue
            if tasks and row["task"] not in tasks:
                continue
            if int(row["sample_count"]) <= min_sample_count:
                continue
            rows.append(row)
        return rows


def build_hints(rows: List[Dict[str, str]]) -> Dict[str, List[Dict[str, Any]]]:
    hints: Dict[str, List[Dict[str, Any]]] = {}
    seen: Set[Tuple[str, str]] = set()

    sorted_rows = sorted(
        rows,
        key=lambda row: (
            row["top_level_key"],
            -int(row["sample_count"]),
            row["structure_id"],
            row["split"],
            row["task"],
        ),
    )
    for row in sorted_rows:
        top_level_key = row["top_level_key"]
        dedup_key = (top_level_key, row["structure_id"])
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        paths = [line.strip() for line in row["paths"].splitlines() if line.strip()]
        hints.setdefault(top_level_key, []).append(
            structure_from_paths(top_level_key, paths)
        )
    return hints


def write_python_file(
    output_file: Path,
    hints: Dict[str, List[Dict[str, Any]]],
    input_csv: Path,
    min_sample_count: int,
) -> None:
    formatted_hints = pprint.pformat(
        hints,
        width=100,
        sort_dicts=False,
    )
    content = (
        '"""Generated structure hints for batch_infer_qa.py.\n\n'
        "Source: %s\n"
        "Filter: sample_count > %s\n"
        'Leaf values use the generic placeholder "<VALUE>" because the source CSV contains paths only.\n'
        '"""\n\n'
        "TOP_LEVEL_KEY_STRUCTURE_HINTS = %s\n"
        % (input_csv, min_sample_count, formatted_hints)
    )
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(content, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build TOP_LEVEL_KEY_STRUCTURE_HINTS from output_structure_distribution.csv."
    )
    parser.add_argument("--input-csv", type=Path, default=DEFAULT_INPUT_CSV)
    parser.add_argument("--output-file", type=Path, default=DEFAULT_OUTPUT_FILE)
    parser.add_argument(
        "--min-sample-count",
        type=int,
        default=DEFAULT_MIN_SAMPLE_COUNT,
        help="Keep rows whose sample_count is strictly greater than this value. Default: 5.",
    )
    parser.add_argument(
        "--splits",
        default="",
        help="Optional comma-separated split filter, e.g. train,val. Empty means all.",
    )
    parser.add_argument(
        "--tasks",
        default="",
        help="Optional comma-separated task filter, e.g. node_config_qa,device_config_qa. Empty means all.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = read_distribution_rows(
        input_csv=args.input_csv,
        min_sample_count=args.min_sample_count,
        splits=parse_csv_values(args.splits),
        tasks=parse_csv_values(args.tasks),
    )
    hints = build_hints(rows)
    write_python_file(
        output_file=args.output_file,
        hints=hints,
        input_csv=args.input_csv,
        min_sample_count=args.min_sample_count,
    )
    structure_count = sum(len(structures) for structures in hints.values())
    print(
        "[structure-hints] wrote %s top-level keys and %s structures to %s"
        % (len(hints), structure_count, args.output_file),
        flush=True,
    )


if __name__ == "__main__":
    main()
