#!/usr/bin/env python3
"""统计 QA 样本 input 的 token 分布，并生成柱状图。

默认读取 build_config_generation_dataset.py 生成的 QA 目录：

QA/
  train/
    node_config_qa/*.json
    device_config_qa/*.json
  val/
    node_config_qa/*.json
    device_config_qa/*.json

注意：不同大模型 tokenizer 不完全一致。这个脚本默认使用 rough_bpe 近似估算，
用于快速判断上下文长度量级；如果后续确定具体模型，可以在这里新增对应 tokenizer。
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import mean, median
from typing import Any, DefaultDict, Dict, Iterable, List, Tuple
from xml.sax.saxutils import escape


DEFAULT_QA_ROOT = Path("QA")
DEFAULT_OUTPUT_DIR = Path("QA_token_analysis")
DEFAULT_FIELD = "input"
TASK_DIR_TO_KIND = {
    "node_config_qa": "node",
    "device_config_qa": "device",
}


@dataclass(frozen=True)
class TokenRow:
    split: str
    task: str
    file: str
    token_count: int
    char_count: int
    byte_count: int
    status: str
    detail: str = ""


def iter_qa_files(qa_root: Path, splits: Iterable[str]) -> Iterable[Tuple[str, str, Path]]:
    """枚举 QA/<split>/<task_dir>/*.json 文件。"""

    for split in splits:
        split_dir = qa_root / split
        for task_dir, task_kind in TASK_DIR_TO_KIND.items():
            task_path = split_dir / task_dir
            if not task_path.exists():
                continue
            for path in sorted(task_path.rglob("*.json")):
                if path.is_file():
                    yield split, task_kind, path


def stable_json_text(value: Any) -> str:
    """把 input/output 等字段转成稳定 JSON 文本，并保留原字段顺序。"""

    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def rough_bpe_token_count(text: str) -> int:
    """粗略估算 BPE token 数。

    经验规则：
    - CJK 字符通常接近 1 字 1 token。
    - 连续英文/数字片段按约 4 字符 1 token 估算。
    - JSON 标点、符号各计 1 token。

    这是为了估计上下文长度量级，不等价于任何具体模型的真实 tokenizer。
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


def simple_unit_token_count(text: str) -> int:
    """更直观的单位切分：CJK 单字、英文数字片段、非空白符号。"""

    pattern = re.compile(r"[\u4e00-\u9fff]|[A-Za-z0-9_\-./]+|[^\s]")
    return len(pattern.findall(text))


def token_count(text: str, tokenizer: str) -> int:
    if tokenizer == "rough_bpe":
        return rough_bpe_token_count(text)
    if tokenizer == "simple_unit":
        return simple_unit_token_count(text)
    raise ValueError("unsupported tokenizer: %s" % tokenizer)


def load_sample_field(path: Path, field: str) -> Tuple[Any, str]:
    try:
        sample = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - 统计脚本需要跳过坏文件并记录。
        return None, "bad_json: %s" % exc
    if not isinstance(sample, dict):
        return None, "sample_not_object"
    if field not in sample:
        return None, "missing_field: %s" % field
    return sample[field], ""


def collect_rows(qa_root: Path, splits: List[str], field: str, tokenizer: str) -> List[TokenRow]:
    rows: List[TokenRow] = []
    for split, task, path in iter_qa_files(qa_root, splits):
        value, error = load_sample_field(path, field)
        file_name = str(path.relative_to(qa_root))
        if error:
            rows.append(TokenRow(split, task, file_name, 0, 0, 0, "error", error))
            continue
        text = stable_json_text(value)
        rows.append(
            TokenRow(
                split=split,
                task=task,
                file=file_name,
                token_count=token_count(text, tokenizer),
                char_count=len(text),
                byte_count=len(text.encode("utf-8")),
                status="ok",
            )
        )
    return rows


def percentile(sorted_values: List[int], percent: float) -> int:
    if not sorted_values:
        return 0
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (len(sorted_values) - 1) * percent
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return sorted_values[int(rank)]
    lower_value = sorted_values[lower]
    upper_value = sorted_values[upper]
    return int(round(lower_value + (upper_value - lower_value) * (rank - lower)))


def number_summary(values: List[int]) -> Dict[str, Any]:
    sorted_values = sorted(values)
    if not sorted_values:
        return {
            "count": 0,
            "min": None,
            "max": None,
            "mean": None,
            "median": None,
            "p75": None,
            "p90": None,
            "p95": None,
            "p99": None,
        }
    return {
        "count": len(sorted_values),
        "min": sorted_values[0],
        "max": sorted_values[-1],
        "mean": round(mean(sorted_values), 4),
        "median": median(sorted_values),
        "p75": percentile(sorted_values, 0.75),
        "p90": percentile(sorted_values, 0.90),
        "p95": percentile(sorted_values, 0.95),
        "p99": percentile(sorted_values, 0.99),
    }


def histogram_bins(values: List[int], requested_bins: int) -> List[Tuple[str, int]]:
    if not values:
        return []
    max_value = max(values)
    if max_value <= 100:
        counts = Counter(values)
        return [(str(value), counts.get(value, 0)) for value in range(0, max_value + 1)]

    bin_count = max(1, requested_bins)
    bin_width = max(1, math.ceil((max_value + 1) / bin_count))
    bins: List[Tuple[int, int, int]] = []
    for start in range(0, max_value + 1, bin_width):
        end = min(start + bin_width - 1, max_value)
        bins.append((start, end, 0))
    index_by_start = {start: idx for idx, (start, _, _) in enumerate(bins)}
    for value in values:
        start = (value // bin_width) * bin_width
        idx = index_by_start[start]
        bin_start, bin_end, count = bins[idx]
        bins[idx] = (bin_start, bin_end, count + 1)
    return [("%s-%s" % (start, end), count) for start, end, count in bins]


def build_summary(rows: List[TokenRow], qa_root: Path, field: str, tokenizer: str) -> Dict[str, Any]:
    ok_rows = [row for row in rows if row.status == "ok"]
    summary: Dict[str, Any] = {
        "qa_root": str(qa_root),
        "field": field,
        "tokenizer": tokenizer,
        "tokenizer_note": "rough_bpe/simple_unit are estimates, not exact model tokenizer counts",
        "files": len(rows),
        "status_counts": dict(Counter(row.status for row in rows)),
        "token_count": number_summary([row.token_count for row in ok_rows]),
        "char_count": number_summary([row.char_count for row in ok_rows]),
        "byte_count": number_summary([row.byte_count for row in ok_rows]),
        "groups": {},
    }

    groups: DefaultDict[str, List[TokenRow]] = defaultdict(list)
    for row in ok_rows:
        groups["split:%s" % row.split].append(row)
        groups["task:%s" % row.task].append(row)
        groups["split_task:%s/%s" % (row.split, row.task)].append(row)

    group_summary: Dict[str, Any] = {}
    for group_name, group_rows in sorted(groups.items()):
        group_summary[group_name] = number_summary([row.token_count for row in group_rows])
    summary["groups"] = group_summary
    return summary


def write_rows_csv(path: Path, rows: List[TokenRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["split", "task", "file", "token_count", "char_count", "byte_count", "status", "detail"],
        )
        writer.writeheader()
        for row in sorted(rows, key=lambda item: (item.split, item.task, item.file)):
            writer.writerow(
                {
                    "split": row.split,
                    "task": row.task,
                    "file": row.file,
                    "token_count": row.token_count,
                    "char_count": row.char_count,
                    "byte_count": row.byte_count,
                    "status": row.status,
                    "detail": row.detail,
                }
            )


def write_histogram_csv(path: Path, bins: List[Tuple[str, int]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["token_count_bin", "sample_count"])
        writer.writeheader()
        for label, count in bins:
            writer.writerow({"token_count_bin": label, "sample_count": count})


def write_histogram_svg(path: Path, bins: List[Tuple[str, int]], title: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    width = 1200
    height = 720
    margin_left = 85
    margin_right = 30
    margin_top = 70
    margin_bottom = 115
    plot_width = width - margin_left - margin_right
    plot_height = height - margin_top - margin_bottom
    max_count = max((count for _, count in bins), default=1)
    bar_gap = 2
    bar_width = max(1, (plot_width - bar_gap * max(0, len(bins) - 1)) / max(1, len(bins)))

    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<svg xmlns="http://www.w3.org/2000/svg" width="%s" height="%s" viewBox="0 0 %s %s">' % (width, height, width, height),
        '<rect width="100%" height="100%" fill="white"/>',
        '<text x="%s" y="32" text-anchor="middle" font-size="24" font-family="Arial">%s</text>' % (width / 2, escape(title)),
        '<line x1="%s" y1="%s" x2="%s" y2="%s" stroke="#222"/>' % (margin_left, margin_top + plot_height, width - margin_right, margin_top + plot_height),
        '<line x1="%s" y1="%s" x2="%s" y2="%s" stroke="#222"/>' % (margin_left, margin_top, margin_left, margin_top + plot_height),
        '<text x="%s" y="%s" font-size="12" font-family="Arial">%s</text>' % (margin_left - 55, margin_top + 10, max_count),
        '<text x="%s" y="%s" font-size="12" font-family="Arial">0</text>' % (margin_left - 20, margin_top + plot_height + 4),
        '<text x="%s" y="%s" text-anchor="middle" font-size="16" font-family="Arial">input token count</text>' % (width / 2, height - 20),
        '<text x="20" y="%s" transform="rotate(-90 20 %s)" text-anchor="middle" font-size="16" font-family="Arial">sample count</text>' % (height / 2, height / 2),
    ]

    label_stride = max(1, math.ceil(len(bins) / 24))
    for idx, (label, count) in enumerate(bins):
        x = margin_left + idx * (bar_width + bar_gap)
        bar_height = 0 if max_count == 0 else (count / max_count) * plot_height
        y = margin_top + plot_height - bar_height
        parts.append('<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" fill="#4C78A8"/>' % (x, y, bar_width, bar_height))
        if idx % label_stride == 0 or idx == len(bins) - 1:
            label_x = x + bar_width / 2
            label_y = margin_top + plot_height + 18
            parts.append(
                '<text x="%.2f" y="%s" transform="rotate(45 %.2f %s)" text-anchor="start" font-size="10" font-family="Arial">%s</text>'
                % (label_x, label_y, label_x, label_y, escape(label))
            )
    parts.append("</svg>")
    path.write_text("\n".join(parts), encoding="utf-8")


def write_top_longest(path: Path, rows: List[TokenRow], limit: int) -> None:
    top_rows = sorted([row for row in rows if row.status == "ok"], key=lambda row: row.token_count, reverse=True)[:limit]
    write_rows_csv(path, top_rows)


def analyze(qa_root: Path, output_dir: Path, splits: List[str], field: str, tokenizer: str, bins: int) -> None:
    rows = collect_rows(qa_root, splits, field, tokenizer)
    ok_token_counts = [row.token_count for row in rows if row.status == "ok"]
    hist_bins = histogram_bins(ok_token_counts, bins)

    output_dir.mkdir(parents=True, exist_ok=True)
    write_rows_csv(output_dir / "qa_input_token_counts.csv", rows)
    write_top_longest(output_dir / "qa_input_token_top_longest.csv", rows, 100)
    write_histogram_csv(output_dir / "qa_input_token_histogram.csv", hist_bins)
    write_histogram_svg(output_dir / "qa_input_token_histogram.svg", hist_bins, "QA Input Token Distribution")
    (output_dir / "qa_input_token_summary.json").write_text(
        json.dumps(build_summary(rows, qa_root, field, tokenizer), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze QA input token distribution and draw a histogram.")
    parser.add_argument("qa_root", nargs="?", type=Path, default=DEFAULT_QA_ROOT, help="QA root directory. Default: QA")
    parser.add_argument("-o", "--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Output directory. Default: QA_token_analysis")
    parser.add_argument("--splits", nargs="+", default=["train", "val"], help="Split names to scan.")
    parser.add_argument("--field", default=DEFAULT_FIELD, choices=["input", "prompt", "output"], help="Sample field to tokenize. Default: input")
    parser.add_argument("--tokenizer", default="rough_bpe", choices=["rough_bpe", "simple_unit"], help="Tokenizer estimate method.")
    parser.add_argument("--bins", type=int, default=40, help="Approximate histogram bin count when token count is above 100.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    analyze(args.qa_root, args.output_dir, args.splits, args.field, args.tokenizer, args.bins)
    print("Wrote QA token analysis to %s" % args.output_dir)


if __name__ == "__main__":
    main()
