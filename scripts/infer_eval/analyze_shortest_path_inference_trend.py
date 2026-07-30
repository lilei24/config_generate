#!/usr/bin/env python3
"""按推理顺序分析最短路径任务指标及核心样本难度因素。"""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict
from pathlib import Path
from statistics import mean
from typing import Any

from evaluate_shortest_path_results import (
    METRIC_NAMES,
    collect_sample_items,
    evaluate_document,
    load_json_object,
)


DEFAULT_RESULT_PATH = Path("vllm-results/shortest_path")
DEFAULT_OUTPUT_DIR = Path("vllm-results/shortest_path-trend-analysis")
DEFAULT_SPLIT = "val"
DEFAULT_WINDOW_SIZE = 100
DEFAULT_PROGRESS_INTERVAL = 100
DEFAULT_FOCUS_METRIC = "path_f1"

CORE_METRICS = (
    "path_length_accuracy",
    "path_valid_rate",
    "path_precision",
    "path_recall",
    "path_f1",
    "path_exact_match_rate",
)
FACTOR_NAMES = (
    "input_context_chars",
    "node_count",
    "link_count",
    "gold_path_length",
    "gold_path_count",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "result_path",
        nargs="?",
        type=Path,
        default=DEFAULT_RESULT_PATH,
        help="包含 task_answer 和 model-output 的结果文件或目录",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="分析结果目录，默认: %(default)s",
    )
    parser.add_argument(
        "--split",
        choices=["train", "val", "all"],
        default=DEFAULT_SPLIT,
        help="分析的数据划分，默认: %(default)s",
    )
    parser.add_argument(
        "--window-size",
        type=int,
        default=DEFAULT_WINDOW_SIZE,
        help="每组包含的连续推理样本数，默认: %(default)s",
    )
    parser.add_argument(
        "--focus-metric",
        choices=CORE_METRICS,
        default=DEFAULT_FOCUS_METRIC,
        help="趋势摘要重点分析的指标，默认: %(default)s",
    )
    parser.add_argument(
        "--progress-interval",
        type=int,
        default=DEFAULT_PROGRESS_INTERVAL,
        help="每处理 N 个文件打印进度，0 表示关闭，默认: %(default)s",
    )
    args = parser.parse_args()
    if args.window_size <= 0:
        parser.error("--window-size 必须大于 0")
    if args.progress_interval < 0:
        parser.error("--progress-interval 不能小于 0")
    return args


def write_csv(
    path: Path,
    fieldnames: list[str],
    rows: list[dict[str, Any]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def count_list(value: Any) -> int:
    return len(value) if isinstance(value, list) else 0


def is_model_success(document: dict[str, Any]) -> bool:
    run_info = document.get("vllm-run")
    if not isinstance(run_info, dict):
        run_info = document.get("opencode-run")
    return bool(
        isinstance(run_info, dict)
        and run_info.get("success") is True
        and isinstance(document.get("model-output"), dict)
    )


def context_character_count(document: dict[str, Any]) -> int:
    """计算实际任务上下文的紧凑 JSON 字符数，不包含答案和推理结果。"""

    context = {
        key: value
        for key, value in document.items()
        if key
        not in {
            "task_answer",
            "model-output",
            "vllm-run",
            "opencode-run",
        }
    }
    return len(
        json.dumps(
            context,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )


def extract_factors(document: dict[str, Any]) -> dict[str, int]:
    answer = document.get("task_answer")
    if not isinstance(answer, dict):
        answer = {}
    path_length = answer.get("path_length")
    return {
        "input_context_chars": context_character_count(document),
        "node_count": count_list(document.get("nodes")),
        "link_count": count_list(document.get("links")),
        "gold_path_length": (
            path_length
            if isinstance(path_length, int) and not isinstance(path_length, bool)
            else 0
        ),
        "gold_path_count": count_list(answer.get("paths")),
    }


def build_sample_rows(
    sample_items: list[tuple[str, Path, str]],
    window_size: int,
    progress_interval: int,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    metric_sums = {name: 0.0 for name in CORE_METRICS}

    for step, (split, path, relative_path) in enumerate(sample_items, start=1):
        try:
            document = load_json_object(path)
            metrics, _ = evaluate_document(document)
            metric_values = asdict(metrics)
            factors = extract_factors(document)
            model_success = is_model_success(document)
            error_reason = ""
        except Exception as error:  # noqa: BLE001 - 坏样本记零并继续。
            metric_values = {name: 0.0 for name in METRIC_NAMES}
            factors = {name: 0 for name in FACTOR_NAMES}
            model_success = False
            error_reason = f"{type(error).__name__}: {error}"
            errors.append(
                {
                    "split": split,
                    "source_file": relative_path,
                    "error": error_reason,
                }
            )

        for name in CORE_METRICS:
            metric_sums[name] += float(metric_values[name])
        row: dict[str, Any] = {
            "step": step,
            "window_id": (step - 1) // window_size + 1,
            "split": split,
            "source_file": relative_path,
            "model_success": model_success,
            "error_reason": error_reason,
            **factors,
        }
        for name in CORE_METRICS:
            row[name] = round(float(metric_values[name]), 8)
            row[f"cumulative_{name}"] = round(metric_sums[name] / step, 8)
        rows.append(row)

        if progress_interval > 0 and (
            step % progress_interval == 0 or step == len(sample_items)
        ):
            print(f"分析进度 {step}/{len(sample_items)}", flush=True)
    return rows, errors


def build_window_rows(
    sample_rows: list[dict[str, Any]],
    window_size: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for start in range(0, len(sample_rows), window_size):
        group = sample_rows[start : start + window_size]
        row: dict[str, Any] = {
            "window_id": start // window_size + 1,
            "step_start": group[0]["step"],
            "step_end": group[-1]["step"],
            "sample_count": len(group),
            "first_file": f"{group[0]['split']}/{group[0]['source_file']}",
            "last_file": f"{group[-1]['split']}/{group[-1]['source_file']}",
            "model_success_count": sum(bool(item["model_success"]) for item in group),
            "model_success_rate": round(
                mean(float(bool(item["model_success"])) for item in group),
                8,
            ),
        }
        for name in FACTOR_NAMES:
            row[f"mean_{name}"] = round(
                mean(float(item[name]) for item in group),
                8,
            )
        for name in CORE_METRICS:
            row[name] = round(
                mean(float(item[name]) for item in group),
                8,
            )
            row[f"cumulative_{name}"] = group[-1][f"cumulative_{name}"]
        rows.append(row)
    return rows


def build_summary(
    args: argparse.Namespace,
    result_path: Path,
    output_dir: Path,
    sample_rows: list[dict[str, Any]],
    window_rows: list[dict[str, Any]],
    error_count: int,
) -> dict[str, Any]:
    focus_metric = args.focus_metric
    minimum_window = min(window_rows, key=lambda row: row[focus_metric])
    maximum_window = max(window_rows, key=lambda row: row[focus_metric])
    return {
        "result_path": str(result_path),
        "output_dir": str(output_dir),
        "split": args.split,
        "ordering": "train then val; lexicographic relative JSON path",
        "window_size": args.window_size,
        "sample_count": len(sample_rows),
        "window_count": len(window_rows),
        "read_error_count": error_count,
        "focus_metric": focus_metric,
        "first_window": {
            "window_id": window_rows[0]["window_id"],
            "value": window_rows[0][focus_metric],
        },
        "minimum_window": {
            "window_id": minimum_window["window_id"],
            "step_start": minimum_window["step_start"],
            "step_end": minimum_window["step_end"],
            "value": minimum_window[focus_metric],
        },
        "maximum_window": {
            "window_id": maximum_window["window_id"],
            "step_start": maximum_window["step_start"],
            "step_end": maximum_window["step_end"],
            "value": maximum_window[focus_metric],
        },
        "last_window": {
            "window_id": window_rows[-1]["window_id"],
            "value": window_rows[-1][focus_metric],
        },
        "notes": {
            "metric_aggregation": "each window is the macro average of all samples",
            "input_context_chars": (
                "compact JSON character count excluding answer and inference metadata; "
                "it is a tokenizer-independent length proxy"
            ),
        },
    }


def plot_trends(
    output_path: Path,
    window_rows: list[dict[str, Any]],
    focus_metric: str,
) -> str | None:
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        return "未安装 matplotlib，已跳过趋势图"

    window_ids = [row["window_id"] for row in window_rows]
    figure, axes = plt.subplots(3, 1, figsize=(13, 11), constrained_layout=True)

    axes[0].plot(
        window_ids,
        [row[focus_metric] for row in window_rows],
        marker="o",
        label=f"window {focus_metric}",
    )
    axes[0].plot(
        window_ids,
        [row[f"cumulative_{focus_metric}"] for row in window_rows],
        marker=".",
        label=f"cumulative {focus_metric}",
    )
    axes[0].plot(
        window_ids,
        [row["model_success_rate"] for row in window_rows],
        linestyle="--",
        label="model success rate",
    )
    axes[0].set_ylim(0, 1.05)
    axes[0].set_ylabel("Score")
    axes[0].set_title("Shortest-path inference trend")
    axes[0].legend()
    axes[0].grid(alpha=0.25)

    axes[1].plot(
        window_ids,
        [row["mean_input_context_chars"] for row in window_rows],
        marker="o",
        color="#D55E00",
    )
    axes[1].set_ylabel("Mean context characters")
    axes[1].grid(alpha=0.25)

    axes[2].plot(
        window_ids,
        [row["mean_node_count"] for row in window_rows],
        marker="o",
        label="node count",
    )
    axes[2].plot(
        window_ids,
        [row["mean_gold_path_length"] for row in window_rows],
        marker="s",
        label="gold path length",
    )
    axes[2].plot(
        window_ids,
        [row["mean_gold_path_count"] for row in window_rows],
        marker="^",
        label="gold path count",
    )
    axes[2].set_xlabel("Window ID (in inference order)")
    axes[2].set_ylabel("Window mean")
    axes[2].legend()
    axes[2].grid(alpha=0.25)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_path, format="svg")
    plt.close(figure)
    return None


def main() -> None:
    args = parse_args()
    result_path = args.result_path.resolve()
    output_dir = args.output_dir.resolve()
    sample_items = collect_sample_items(result_path, args.split)
    if not sample_items:
        raise FileNotFoundError(f"没有找到推理结果 JSON: {result_path}")

    sample_rows, errors = build_sample_rows(
        sample_items,
        args.window_size,
        args.progress_interval,
    )
    window_rows = build_window_rows(sample_rows, args.window_size)
    summary = build_summary(
        args,
        result_path,
        output_dir,
        sample_rows,
        window_rows,
        len(errors),
    )

    sample_fields = [
        "step",
        "window_id",
        "split",
        "source_file",
        "model_success",
        "error_reason",
        *FACTOR_NAMES,
        *CORE_METRICS,
        *(f"cumulative_{name}" for name in CORE_METRICS),
    ]
    window_fields = [
        "window_id",
        "step_start",
        "step_end",
        "sample_count",
        "first_file",
        "last_file",
        "model_success_count",
        "model_success_rate",
        *(f"mean_{name}" for name in FACTOR_NAMES),
        *CORE_METRICS,
        *(f"cumulative_{name}" for name in CORE_METRICS),
    ]
    write_csv(output_dir / "per_sample_trend.csv", sample_fields, sample_rows)
    write_csv(output_dir / "window_trend.csv", window_fields, window_rows)
    write_csv(
        output_dir / "analysis_errors.csv",
        ["split", "source_file", "error"],
        errors,
    )
    plot_warning = plot_trends(
        output_dir / "shortest_path_trend.svg",
        window_rows,
        args.focus_metric,
    )
    if plot_warning:
        summary["plot_warning"] = plot_warning
    (output_dir / "trend_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
