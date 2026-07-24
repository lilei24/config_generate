#!/usr/bin/env python3
"""任务评估脚本共用的批处理、SwanLab 记录和路径集合指标。"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any, Callable


EvaluateDocument = Callable[
    [dict[str, Any]],
    tuple[dict[str, float], dict[str, int]],
]

PATH_METRIC_NAMES = (
    "path_length_accuracy",
    "path_precision",
    "path_recall",
    "path_f1",
)
PATH_DETAIL_NAMES = (
    "predicted_path_count",
    "gold_path_count",
    "true_positive",
    "false_positive",
    "false_negative",
)


def add_evaluation_arguments(
    parser: argparse.ArgumentParser,
    *,
    default_result_path: Path,
    default_output_dir: Path,
    default_project: str,
    default_experiment: str,
) -> None:
    parser.add_argument(
        "result_path",
        nargs="?",
        type=Path,
        default=default_result_path,
        help=(
            "单个同时包含 task_answer 和 model-output 的结果 JSON，"
            "或包含 train/val 的结果目录，默认: %(default)s"
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=default_output_dir,
        help="本地评估输出目录，默认: %(default)s",
    )
    parser.add_argument(
        "--split",
        choices=["train", "val", "all"],
        default="val",
        help="评估的数据划分，默认: %(default)s",
    )
    parser.add_argument(
        "--progress-interval",
        type=int,
        default=100,
        help="每处理 N 个文件打印进度，0 表示关闭，默认: %(default)s",
    )
    parser.add_argument(
        "--swanlab-project",
        default=default_project,
        help="SwanLab 项目名称，默认: %(default)s",
    )
    parser.add_argument(
        "--swanlab-experiment",
        default=default_experiment,
        help="SwanLab 实验名称，默认: %(default)s",
    )
    parser.add_argument(
        "--swanlab-mode",
        default="cloud",
        help="SwanLab 运行模式，默认: %(default)s",
    )
    parser.add_argument(
        "--disable-swanlab",
        action="store_true",
        help="只生成本地评估文件，不初始化 SwanLab",
    )


def validate_evaluation_arguments(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
) -> None:
    if args.progress_interval < 0:
        parser.error("--progress-interval 不能小于 0")


def load_json_object(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"JSON 顶层必须是对象，实际为 {type(data).__name__}")
    return data


def normalize_path_set(
    value: Any,
) -> tuple[set[tuple[str, ...]], int, int]:
    """返回去重路径集合、原始预测数量和非法路径数量。"""

    if not isinstance(value, list):
        return set(), 0, 0
    paths: set[tuple[str, ...]] = set()
    malformed = 0
    for path in value:
        if (
            isinstance(path, list)
            and path
            and all(isinstance(node_id, str) and node_id for node_id in path)
        ):
            paths.add(tuple(path))
        else:
            malformed += 1
    return paths, len(value), malformed


def evaluate_path_document(
    document: dict[str, Any],
) -> tuple[dict[str, float], dict[str, int]]:
    metrics = {name: 0.0 for name in PATH_METRIC_NAMES}
    details = {name: 0 for name in PATH_DETAIL_NAMES}
    answer = document.get("task_answer")
    prediction = document.get("model-output")
    if not isinstance(answer, dict) or not isinstance(prediction, dict):
        return metrics, details

    gold_length = answer.get("path_length")
    predicted_length = prediction.get("path_length")
    metrics["path_length_accuracy"] = float(
        not isinstance(gold_length, bool)
        and isinstance(gold_length, int)
        and not isinstance(predicted_length, bool)
        and isinstance(predicted_length, int)
        and predicted_length == gold_length
    )

    gold_paths, _, _ = normalize_path_set(answer.get("paths"))
    predicted_paths, predicted_count, malformed = normalize_path_set(
        prediction.get("paths")
    )
    true_positive = len(predicted_paths & gold_paths)
    false_positive = len(predicted_paths - gold_paths) + malformed
    false_negative = len(gold_paths - predicted_paths)
    precision_denominator = true_positive + false_positive
    recall_denominator = true_positive + false_negative
    precision = (
        true_positive / precision_denominator if precision_denominator else 0.0
    )
    recall = true_positive / recall_denominator if recall_denominator else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0
    )
    metrics.update(
        path_precision=precision,
        path_recall=recall,
        path_f1=f1,
    )
    details.update(
        predicted_path_count=predicted_count,
        gold_path_count=len(gold_paths),
        true_positive=true_positive,
        false_positive=false_positive,
        false_negative=false_negative,
    )
    return metrics, details


def collect_sample_items(
    result_path: Path,
    split: str,
) -> list[tuple[str, Path, str]]:
    if result_path.is_file():
        if result_path.suffix.lower() != ".json":
            raise ValueError(f"结果文件必须是 JSON: {result_path}")
        return [("single", result_path, result_path.name)]
    if not result_path.is_dir():
        raise FileNotFoundError(f"结果文件或目录不存在: {result_path}")

    selected_splits = ["train", "val"] if split == "all" else [split]
    split_dirs = [
        (split_name, result_path / split_name)
        for split_name in selected_splits
        if (result_path / split_name).is_dir()
    ]
    if split_dirs:
        missing = [
            split_name
            for split_name in selected_splits
            if not (result_path / split_name).is_dir()
        ]
        if missing:
            raise FileNotFoundError("缺少结果划分目录: " + ", ".join(missing))
        return [
            (split_name, path, str(path.relative_to(split_root)))
            for split_name, split_root in split_dirs
            for path in sorted(split_root.rglob("*.json"))
            if path.is_file()
        ]

    direct_split = split if split != "all" else result_path.name
    return [
        (direct_split, path, str(path.relative_to(result_path)))
        for path in sorted(result_path.rglob("*.json"))
        if path.is_file()
    ]


def import_swanlab() -> Any:
    try:
        import swanlab
    except ImportError as error:
        raise RuntimeError(
            "缺少 swanlab 依赖，请执行 pip install swanlab，"
            "或使用 --disable-swanlab"
        ) from error
    return swanlab


def init_swanlab(
    args: argparse.Namespace,
    result_path: Path,
    metric_names: tuple[str, ...],
    task_name: str,
) -> Any | None:
    if args.disable_swanlab:
        return None
    swanlab = import_swanlab()
    swanlab.init(
        project=args.swanlab_project,
        experiment_name=args.swanlab_experiment,
        mode=args.swanlab_mode,
        config={
            "script": Path(sys.argv[0]).name,
            "task": task_name,
            "result_path": str(result_path),
            "split": args.split,
            "aggregation": "running macro average",
            "metrics": list(metric_names),
        },
    )
    return swanlab


def get_run_info(document: dict[str, Any]) -> dict[str, Any] | None:
    for field_name in ("vllm-run", "opencode-run"):
        value = document.get(field_name)
        if isinstance(value, dict):
            return value
    return None


def log_metrics(
    swanlab: Any | None,
    step: int,
    metric_names: tuple[str, ...],
    sample_metrics: dict[str, float],
    metric_sums: dict[str, float],
) -> None:
    if swanlab is None:
        return
    payload = {
        f"sample/{name}": float(sample_metrics[name])
        for name in metric_names
    }
    payload.update(
        {
            f"eval/{name}": float(metric_sums[name] / step)
            for name in metric_names
        }
    )
    swanlab.log(payload, step=step)


def json_table_text(value: Any) -> str:
    return "" if value is None else json.dumps(value, ensure_ascii=False, indent=2)


def build_table_row(
    json_name: str,
    document: dict[str, Any] | None,
) -> list[str]:
    if document is None:
        return [json_name, "", "", ""]
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
    return [
        json_name,
        json_table_text(context),
        json_table_text(document.get("task_answer")),
        json_table_text(document.get("model-output")),
    ]


def log_table(swanlab: Any | None, rows: list[list[str]]) -> None:
    if swanlab is None:
        return
    echarts = getattr(swanlab, "echarts", None)
    table_class = getattr(echarts, "Table", None) if echarts else None
    if table_class is None:
        raise RuntimeError("当前 SwanLab 版本不支持 swanlab.echarts.Table")
    table = table_class()
    table.add(["json_name", "context", "answer", "model-output"], rows)
    swanlab.log({"sample/details": table})


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


def finish_swanlab(swanlab: Any | None) -> None:
    if swanlab is None:
        return
    finish = getattr(swanlab, "finish", None)
    if callable(finish):
        finish()


def run_evaluation(
    args: argparse.Namespace,
    *,
    task_name: str,
    metric_names: tuple[str, ...],
    detail_names: tuple[str, ...],
    evaluate_document: EvaluateDocument,
) -> dict[str, Any]:
    result_path = args.result_path.resolve()
    output_dir = args.output_dir.resolve()
    sample_items = collect_sample_items(result_path, args.split)
    if not sample_items:
        raise FileNotFoundError(f"没有找到推理结果 JSON: {result_path}")

    rows: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    table_rows: list[list[str]] = []
    metric_sums = {name: 0.0 for name in metric_names}
    successful_model_returns = 0
    swanlab = init_swanlab(
        args,
        result_path,
        metric_names,
        task_name,
    )

    for step, (split, path, relative_path) in enumerate(sample_items, start=1):
        document: dict[str, Any] | None = None
        metrics = {name: 0.0 for name in metric_names}
        details = {name: 0 for name in detail_names}
        model_returned = False
        error_reason = ""
        try:
            document = load_json_object(path)
            run_info = get_run_info(document)
            model_returned = bool(
                isinstance(run_info, dict)
                and run_info.get("success") is True
                and isinstance(document.get("model-output"), dict)
            )
            if model_returned:
                successful_model_returns += 1
            elif isinstance(run_info, dict):
                error_reason = str(
                    run_info.get("error") or "model-output unavailable"
                )
            else:
                error_reason = "missing inference run metadata"
            metrics, details = evaluate_document(document)
        except Exception as error:  # noqa: BLE001 - 坏结果按零分记录。
            error_reason = f"{type(error).__name__}: {error}"

        json_name = (
            relative_path if split == "single" else f"{split}/{relative_path}"
        )
        table_rows.append(build_table_row(json_name, document))
        for name in metric_names:
            metric_sums[name] += metrics[name]
        log_metrics(
            swanlab,
            step,
            metric_names,
            metrics,
            metric_sums,
        )
        rows.append(
            {
                "split": split,
                "source_file": relative_path,
                "model_returned": model_returned,
                "error_reason": error_reason,
                **details,
                **{name: round(metrics[name], 8) for name in metric_names},
            }
        )
        if error_reason:
            errors.append(
                {
                    "split": split,
                    "source_file": relative_path,
                    "error": error_reason,
                }
            )
        if args.progress_interval > 0 and (
            step % args.progress_interval == 0 or step == len(sample_items)
        ):
            print(f"评价进度 {step}/{len(sample_items)}", flush=True)

    sample_count = len(rows)
    aggregate_metrics = {
        name: round(metric_sums[name] / sample_count, 8)
        for name in metric_names
    }
    summary = {
        "task": task_name,
        "result_path": str(result_path),
        "output_dir": str(output_dir),
        "splits": sorted({item[0] for item in sample_items}),
        "aggregation": "macro: evaluate each sample, then average",
        "sample_count": sample_count,
        "successful_model_returns": successful_model_returns,
        "failed_model_returns": sample_count - successful_model_returns,
        "metrics": aggregate_metrics,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(
        output_dir / "per_file_metrics.csv",
        [
            "split",
            "source_file",
            "model_returned",
            "error_reason",
            *detail_names,
            *metric_names,
        ],
        rows,
    )
    write_csv(
        output_dir / "evaluation_errors.csv",
        ["split", "source_file", "error"],
        errors,
    )
    (output_dir / "evaluation_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    log_table(swanlab, table_rows)
    finish_swanlab(swanlab)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary
