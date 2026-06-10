#!/usr/bin/env python3
"""Analyze JSON path structure distributions of QA output values."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, DefaultDict, Dict, Iterable, List, Optional, Set, Tuple


DEFAULT_QA_ROOT = Path("520QA")
DEFAULT_OUTPUT_ROOT = Path("output-structure-analysis")
DEFAULT_SPLITS = "train"
DEFAULT_TASKS = "node_config_qa"
DEFAULT_PROGRESS_INTERVAL = 500
STRUCTURE_ID_LENGTH = 16


PER_FILE_FIELDS = [
    "split",
    "task",
    "file",
    "status",
    "error",
    "top_level_key",
    "structure_id",
    "path_count",
    "paths",
]


TOP_KEY_SUMMARY_FIELDS = [
    "split",
    "task",
    "top_level_key",
    "sample_count",
    "distinct_structure_count",
    "most_common_structure_id",
    "most_common_structure_count",
    "most_common_structure_ratio",
    "singleton_structure_count",
    "singleton_structure_ratio",
    "singleton_sample_count",
    "singleton_sample_ratio",
]


STRUCTURE_DISTRIBUTION_FIELDS = [
    "split",
    "task",
    "top_level_key",
    "structure_rank",
    "structure_id",
    "sample_count",
    "ratio_within_top_key",
    "cumulative_ratio",
    "path_count",
    "paths",
]


ERROR_FIELDS = [
    "split",
    "task",
    "status",
    "error",
    "count",
]


@dataclass(frozen=True)
class StructureRow:
    split: str
    task: str
    file: str
    status: str
    error: str
    top_level_key: str
    structure_id: str
    paths: Tuple[str, ...]


def parse_csv_values(text: str) -> List[str]:
    return [item.strip() for item in text.split(",") if item.strip()]


def iter_qa_files(
    qa_root: Path,
    splits: Iterable[str],
    tasks: Iterable[str],
) -> Iterable[Tuple[str, str, Path]]:
    """Enumerate QA files as qa_root/<split>/<task>/**/*.json."""

    for split in splits:
        for task in tasks:
            task_root = qa_root / split / task
            if not task_root.exists():
                continue
            for path in sorted(task_root.rglob("*.json")):
                if path.is_file():
                    yield split, task, path


def read_json(path: Path) -> Tuple[Optional[Dict[str, Any]], str]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - bad source files are recorded.
        return None, "bad_json: %s" % exc
    if not isinstance(value, dict):
        return None, "sample_not_object"
    return value, ""


def escape_path_key(key: Any) -> str:
    return str(key).replace("~", "~0").replace("/", "~1")


def collect_structure_paths(top_level_key: str, value: Any) -> Tuple[str, ...]:
    """Collect unique JSON paths for one top-level key.

    Values and object key order are ignored. Array indexes and array lengths are
    normalized to ``[]``. Container paths are retained, so empty objects and
    arrays still have a visible structure path.
    """

    root_path = "/" + escape_path_key(top_level_key)
    paths: Set[str] = {root_path}

    def walk(current: Any, current_path: str) -> None:
        if isinstance(current, dict):
            for key, child in current.items():
                child_path = current_path + "/" + escape_path_key(key)
                paths.add(child_path)
                walk(child, child_path)
        elif isinstance(current, list):
            array_path = current_path + "[]"
            paths.add(array_path)
            for item in current:
                walk(item, array_path)

    walk(value, root_path)
    return tuple(sorted(paths))


def structure_id(paths: Tuple[str, ...]) -> str:
    canonical = json.dumps(paths, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:STRUCTURE_ID_LENGTH]


def collect_rows(
    qa_root: Path,
    splits: List[str],
    tasks: List[str],
    progress_interval: int,
    limit: int,
) -> List[StructureRow]:
    files = list(iter_qa_files(qa_root, splits, tasks))
    if limit:
        files = files[:limit]

    rows: List[StructureRow] = []
    total = len(files)
    started_at = time.time()
    print("[output-structure] start: %s files" % total, flush=True)

    for index, (split, task, path) in enumerate(files, start=1):
        file_name = str(path.relative_to(qa_root))
        sample, error = read_json(path)
        if error or sample is None:
            rows.append(StructureRow(split, task, file_name, "error", error, "", "", ()))
        elif "output" not in sample:
            rows.append(StructureRow(split, task, file_name, "error", "missing_output", "", "", ()))
        elif not isinstance(sample["output"], dict):
            rows.append(
                StructureRow(
                    split,
                    task,
                    file_name,
                    "error",
                    "output_not_object: %s" % type(sample["output"]).__name__,
                    "",
                    "",
                    (),
                )
            )
        elif not sample["output"]:
            rows.append(StructureRow(split, task, file_name, "error", "empty_output_object", "", "", ()))
        else:
            for top_level_key, value in sample["output"].items():
                top_key_text = str(top_level_key)
                paths = collect_structure_paths(top_key_text, value)
                rows.append(
                    StructureRow(
                        split=split,
                        task=task,
                        file=file_name,
                        status="ok",
                        error="",
                        top_level_key=top_key_text,
                        structure_id=structure_id(paths),
                        paths=paths,
                    )
                )

        if progress_interval > 0 and (index % progress_interval == 0 or index == total):
            elapsed = max(0.001, time.time() - started_at)
            speed = index / elapsed
            eta = (total - index) / speed if speed > 0 else 0.0
            percent = index / total * 100 if total else 100.0
            print(
                "[output-structure] %s/%s files (%.2f%%), %.2f files/s, eta %.1fs"
                % (index, total, percent, speed, eta),
                flush=True,
            )
    return rows


def paths_text(paths: Tuple[str, ...]) -> str:
    return "\n".join(paths)


def per_file_rows(rows: List[StructureRow]) -> List[Dict[str, Any]]:
    return [
        {
            "split": row.split,
            "task": row.task,
            "file": row.file,
            "status": row.status,
            "error": row.error,
            "top_level_key": row.top_level_key,
            "structure_id": row.structure_id,
            "path_count": len(row.paths),
            "paths": paths_text(row.paths),
        }
        for row in rows
    ]


GroupKey = Tuple[str, str, str]
StructureKey = Tuple[str, str, str, str]


def valid_rows(rows: List[StructureRow]) -> List[StructureRow]:
    return [row for row in rows if row.status == "ok"]


def structure_counts(rows: List[StructureRow]) -> Counter:
    return Counter((row.split, row.task, row.top_level_key, row.structure_id) for row in valid_rows(rows))


def top_key_counts(rows: List[StructureRow]) -> Counter:
    return Counter((row.split, row.task, row.top_level_key) for row in valid_rows(rows))


def structure_paths_map(rows: List[StructureRow]) -> Dict[StructureKey, Tuple[str, ...]]:
    return {
        (row.split, row.task, row.top_level_key, row.structure_id): row.paths
        for row in valid_rows(rows)
    }


def build_distribution_rows(rows: List[StructureRow]) -> List[Dict[str, Any]]:
    counts = structure_counts(rows)
    totals = top_key_counts(rows)
    paths_by_structure = structure_paths_map(rows)
    grouped: DefaultDict[GroupKey, List[Tuple[str, int]]] = defaultdict(list)
    for (split, task, top_key, current_structure_id), count in counts.items():
        grouped[(split, task, top_key)].append((current_structure_id, count))

    output: List[Dict[str, Any]] = []
    for group_key in sorted(grouped):
        split, task, top_key = group_key
        total = totals[group_key]
        ranked = sorted(grouped[group_key], key=lambda item: (-item[1], item[0]))
        cumulative_count = 0
        for rank, (current_structure_id, count) in enumerate(ranked, start=1):
            cumulative_count += count
            paths = paths_by_structure[(split, task, top_key, current_structure_id)]
            output.append(
                {
                    "split": split,
                    "task": task,
                    "top_level_key": top_key,
                    "structure_rank": rank,
                    "structure_id": current_structure_id,
                    "sample_count": count,
                    "ratio_within_top_key": count / total if total else 0.0,
                    "cumulative_ratio": cumulative_count / total if total else 0.0,
                    "path_count": len(paths),
                    "paths": paths_text(paths),
                }
            )
    return output


def build_top_key_summary_rows(
    rows: List[StructureRow],
    distribution_rows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    totals = top_key_counts(rows)
    structures_by_group: DefaultDict[GroupKey, List[Dict[str, Any]]] = defaultdict(list)
    for row in distribution_rows:
        structures_by_group[(row["split"], row["task"], row["top_level_key"])].append(row)

    output: List[Dict[str, Any]] = []
    for group_key in sorted(totals):
        split, task, top_key = group_key
        structures = structures_by_group[group_key]
        most_common = structures[0]
        singleton_count = sum(1 for row in structures if row["sample_count"] == 1)
        output.append(
            {
                "split": split,
                "task": task,
                "top_level_key": top_key,
                "sample_count": totals[group_key],
                "distinct_structure_count": len(structures),
                "most_common_structure_id": most_common["structure_id"],
                "most_common_structure_count": most_common["sample_count"],
                "most_common_structure_ratio": most_common["ratio_within_top_key"],
                "singleton_structure_count": singleton_count,
                "singleton_structure_ratio": singleton_count / len(structures) if structures else 0.0,
                "singleton_sample_count": singleton_count,
                "singleton_sample_ratio": singleton_count / totals[group_key] if totals[group_key] else 0.0,
            }
        )
    return output


def build_structure_paths_json(rows: List[StructureRow]) -> Dict[str, Any]:
    grouped: DefaultDict[str, DefaultDict[str, Dict[str, Any]]] = defaultdict(lambda: defaultdict(dict))
    counts = structure_counts(rows)
    for (split, task, top_key, current_structure_id), paths in sorted(structure_paths_map(rows).items()):
        group_name = "%s/%s" % (split, task)
        grouped[group_name][top_key][current_structure_id] = {
            "sample_count": counts[(split, task, top_key, current_structure_id)],
            "path_count": len(paths),
            "paths": list(paths),
        }
    return {
        group_name: {top_key: structures for top_key, structures in top_keys.items()}
        for group_name, top_keys in grouped.items()
    }


def build_error_rows(rows: List[StructureRow]) -> List[Dict[str, Any]]:
    counts = Counter(
        (row.split, row.task, row.status, row.error)
        for row in rows
        if row.status != "ok"
    )
    return [
        {
            "split": split,
            "task": task,
            "status": status,
            "error": error,
            "count": count,
        }
        for (split, task, status, error), count in counts.most_common()
    ]


def write_csv(path: Path, rows: List[Dict[str, Any]], fieldnames: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> None:
    splits = parse_csv_values(args.splits)
    tasks = parse_csv_values(args.tasks)
    rows = collect_rows(
        qa_root=args.qa_root,
        splits=splits,
        tasks=tasks,
        progress_interval=args.progress_interval,
        limit=args.limit,
    )
    distribution_rows = build_distribution_rows(rows)
    top_key_summary_rows = build_top_key_summary_rows(rows, distribution_rows)
    error_rows = build_error_rows(rows)

    write_csv(args.output_root / "output_structure_per_file.csv", per_file_rows(rows), PER_FILE_FIELDS)
    write_csv(
        args.output_root / "output_top_key_summary.csv",
        top_key_summary_rows,
        TOP_KEY_SUMMARY_FIELDS,
    )
    write_csv(
        args.output_root / "output_structure_distribution.csv",
        distribution_rows,
        STRUCTURE_DISTRIBUTION_FIELDS,
    )
    write_csv(args.output_root / "output_structure_errors.csv", error_rows, ERROR_FIELDS)
    write_json(args.output_root / "output_structure_paths.json", build_structure_paths_json(rows))
    write_json(
        args.output_root / "output_structure_summary.json",
        {
            "qa_root": str(args.qa_root),
            "output_root": str(args.output_root),
            "splits": splits,
            "tasks": tasks,
            "structure_definition": {
                "source_field": "output",
                "grouping": "split + task + output top-level key",
                "signature": "sorted unique JSON paths",
                "value_ignored": True,
                "object_key_order_ignored": True,
                "array_index_ignored": True,
                "array_length_ignored": True,
                "array_marker": "[]",
                "structure_id": "first %s characters of SHA-256" % STRUCTURE_ID_LENGTH,
            },
            "source_file_count": len({(row.split, row.task, row.file) for row in rows}),
            "analysis_row_count": len(rows),
            "ok_rows": sum(1 for row in rows if row.status == "ok"),
            "error_rows": sum(1 for row in rows if row.status != "ok"),
            "top_level_key_group_count": len(top_key_summary_rows),
            "distinct_structure_group_count": len(distribution_rows),
            "errors": error_rows,
        },
    )
    print("[output-structure] done. output: %s" % args.output_root, flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze QA output JSON path structure distributions.")
    parser.add_argument("--qa-root", type=Path, default=DEFAULT_QA_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--splits", default=DEFAULT_SPLITS, help="Comma-separated splits, e.g. train,val.")
    parser.add_argument(
        "--tasks",
        default=DEFAULT_TASKS,
        help="Comma-separated tasks, e.g. node_config_qa,device_config_qa.",
    )
    parser.add_argument("--progress-interval", type=int, default=DEFAULT_PROGRESS_INTERVAL)
    parser.add_argument("--limit", type=int, default=0, help="Only analyze first N files. 0 means all.")
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
