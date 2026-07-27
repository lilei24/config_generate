#!/usr/bin/env python3
"""评价单个或一批最短路径推理结果，并将指标记录到 SwanLab。"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from task_evaluation_common import (
    DEFAULT_SWANLAB_COLOR_SEED,
    deterministic_experiment_color,
    experiment_color_key,
)


DEFAULT_RESULT_PATH = Path("vllm-results/shortest_path")
DEFAULT_OUTPUT_DIR = Path("vllm-results/shortest_path-evaluation")
DEFAULT_SPLIT = "val"
DEFAULT_PROGRESS_INTERVAL = 100
DEFAULT_SWANLAB_PROJECT = "topology-shortest-path"
DEFAULT_SWANLAB_EXPERIMENT = "shortest-path-evaluation"
DEFAULT_SWANLAB_MODE = "cloud"

METRIC_NAMES = (
    "path_length_accuracy",
    "path_valid_rate",
    "path_precision",
    "path_recall",
    "path_f1",
    "path_exact_match_rate",
    "role_accuracy",
    "device_name_accuracy",
)


@dataclass
class SampleMetrics:
    path_length_accuracy: float = 0.0
    path_valid_rate: float = 0.0
    path_precision: float = 0.0
    path_recall: float = 0.0
    path_f1: float = 0.0
    path_exact_match_rate: float = 0.0
    role_accuracy: float = 0.0
    device_name_accuracy: float = 0.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "result_path",
        nargs="?",
        type=Path,
        default=DEFAULT_RESULT_PATH,
        help=(
            "一个同时包含 task_answer 和 model-output 的结果 JSON；"
            "也可传入结果根目录进行批量评价，默认: %(default)s"
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="评价结果目录，默认: %(default)s",
    )
    parser.add_argument(
        "--split",
        choices=["train", "val", "all"],
        default=DEFAULT_SPLIT,
        help="评价的数据划分，默认: %(default)s",
    )
    parser.add_argument(
        "--progress-interval",
        type=int,
        default=DEFAULT_PROGRESS_INTERVAL,
        help="每处理 N 个文件打印进度，0 表示关闭，默认: %(default)s",
    )
    parser.add_argument(
        "--swanlab-project",
        default=DEFAULT_SWANLAB_PROJECT,
        help="SwanLab 项目名称，默认: %(default)s",
    )
    parser.add_argument(
        "--swanlab-experiment",
        default=DEFAULT_SWANLAB_EXPERIMENT,
        help="SwanLab 实验名称，默认: %(default)s",
    )
    parser.add_argument(
        "--swanlab-mode",
        default=DEFAULT_SWANLAB_MODE,
        help="SwanLab 运行模式，默认: %(default)s",
    )
    parser.add_argument(
        "--swanlab-color-seed",
        type=int,
        default=DEFAULT_SWANLAB_COLOR_SEED,
        help=(
            "根据实验名生成确定性颜色的固定随机种子，默认: %(default)s"
        ),
    )
    parser.add_argument(
        "--swanlab-color-key",
        default=None,
        help=(
            "实验颜色区分键；默认使用 result_path，不同模型可显式传入不同键"
        ),
    )
    parser.add_argument(
        "--disable-swanlab",
        action="store_true",
        help="只生成本地评价文件，不初始化和上传 SwanLab",
    )
    args = parser.parse_args()
    if args.progress_interval < 0:
        parser.error("--progress-interval 不能小于 0")
    return args


def import_swanlab() -> Any:
    try:
        import swanlab
    except ImportError as error:
        raise RuntimeError(
            "缺少 swanlab 依赖，请先执行: pip install swanlab；"
            "如只需本地评价可使用 --disable-swanlab"
        ) from error
    return swanlab


def load_json_object(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"JSON 顶层必须是对象，实际为 {type(data).__name__}")
    return data


def get_device(node: dict[str, Any]) -> dict[str, Any]:
    device = node.get("device")
    if not isinstance(device, dict):
        device = node.get("devices")
    return device if isinstance(device, dict) else {}


def build_node_metadata(
    document: dict[str, Any],
) -> tuple[set[str], dict[str, str], dict[str, str]]:
    node_ids: set[str] = set()
    role_by_id: dict[str, str] = {}
    name_by_id: dict[str, str] = {}
    nodes = document.get("nodes")
    if not isinstance(nodes, list):
        return node_ids, role_by_id, name_by_id

    for node in nodes:
        if not isinstance(node, dict) or node.get("id") is None:
            continue
        node_id = str(node["id"])
        if node_id in node_ids:
            continue
        node_ids.add(node_id)

        topology_node = node.get("topologyNode")
        role = topology_node.get("DEVICEROLE") if isinstance(topology_node, dict) else None
        role_by_id[node_id] = str(role) if role is not None else ""

        name = get_device(node).get("NAME")
        name_by_id[node_id] = str(name) if name is not None else node_id
    return node_ids, role_by_id, name_by_id


def build_adjacency(
    document: dict[str, Any], node_ids: set[str]
) -> dict[str, set[str]]:
    adjacency = {node_id: set() for node_id in node_ids}
    directed = bool(document.get("directed", False))
    links = document.get("links")
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
        if source_id not in node_ids or target_id not in node_ids:
            continue
        adjacency[source_id].add(target_id)
        if not directed:
            adjacency[target_id].add(source_id)
    return adjacency


def normalize_gold_paths(value: Any) -> set[tuple[str, ...]]:
    if not isinstance(value, list):
        return set()
    paths: set[tuple[str, ...]] = set()
    for path in value:
        if (
            isinstance(path, list)
            and path
            and all(isinstance(node_id, str) and node_id for node_id in path)
        ):
            paths.add(tuple(path))
    return paths


def normalize_predicted_paths(
    value: Any,
) -> tuple[list[Any], list[tuple[str, ...]], int]:
    if not isinstance(value, list):
        return [], [], 0
    normalized: list[tuple[str, ...]] = []
    malformed = 0
    for path in value:
        if (
            isinstance(path, list)
            and path
            and all(isinstance(node_id, str) and node_id for node_id in path)
        ):
            normalized.append(tuple(path))
        else:
            malformed += 1
    return value, normalized, malformed


def is_valid_shortest_path(
    path: tuple[str, ...],
    source_id: str | None,
    target_id: str | None,
    shortest_length: int | None,
    node_ids: set[str],
    adjacency: dict[str, set[str]],
) -> bool:
    if not path or source_id is None or target_id is None or shortest_length is None:
        return False
    if path[0] != source_id or path[-1] != target_id:
        return False
    if any(node_id not in node_ids for node_id in path):
        return False
    if len(set(path)) != len(path):
        return False
    if len(path) - 1 != shortest_length:
        return False
    return all(right in adjacency.get(left, set()) for left, right in zip(path, path[1:]))


def annotation_accuracy(
    raw_paths: Any,
    sequences: Any,
    expected_by_id: dict[str, str],
) -> float:
    if not isinstance(raw_paths, list) or not raw_paths:
        return 0.0
    if not isinstance(sequences, list) or len(sequences) != len(raw_paths):
        return 0.0

    total_positions = 0
    correct_positions = 0
    for path, sequence in zip(raw_paths, sequences):
        if not isinstance(path, list) or not isinstance(sequence, list):
            return 0.0
        if not path or len(sequence) != len(path):
            return 0.0
        total_positions += len(path)
        for node_id, predicted_value in zip(path, sequence):
            if (
                isinstance(node_id, str)
                and isinstance(predicted_value, str)
                and node_id in expected_by_id
                and predicted_value == expected_by_id[node_id]
            ):
                correct_positions += 1
    return correct_positions / total_positions if total_positions else 0.0


def evaluate_document(document: dict[str, Any]) -> tuple[SampleMetrics, dict[str, int]]:
    metrics = SampleMetrics()
    answer = document.get("task_answer")
    prediction = document.get("model-output")
    if not isinstance(answer, dict) or not isinstance(prediction, dict):
        return metrics, {
            "predicted_path_count": 0,
            "gold_path_count": 0,
            "true_positive": 0,
            "false_positive": 0,
            "false_negative": 0,
        }

    gold_length = answer.get("path_length")
    if isinstance(gold_length, bool) or not isinstance(gold_length, int):
        gold_length = None
    predicted_length = prediction.get("path_length")
    metrics.path_length_accuracy = float(
        gold_length is not None
        and not isinstance(predicted_length, bool)
        and isinstance(predicted_length, int)
        and predicted_length == gold_length
    )

    gold_paths = normalize_gold_paths(answer.get("paths"))
    raw_paths, normalized_paths, malformed_count = normalize_predicted_paths(
        prediction.get("paths")
    )
    predicted_path_set = set(normalized_paths)
    true_positive = len(predicted_path_set & gold_paths)
    false_positive = len(predicted_path_set - gold_paths) + malformed_count
    false_negative = len(gold_paths - predicted_path_set)

    precision_denominator = true_positive + false_positive
    recall_denominator = true_positive + false_negative
    metrics.path_precision = (
        true_positive / precision_denominator if precision_denominator else 0.0
    )
    metrics.path_recall = (
        true_positive / recall_denominator if recall_denominator else 0.0
    )
    if metrics.path_precision + metrics.path_recall:
        metrics.path_f1 = (
            2
            * metrics.path_precision
            * metrics.path_recall
            / (metrics.path_precision + metrics.path_recall)
        )

    node_ids, role_by_id, name_by_id = build_node_metadata(document)
    adjacency = build_adjacency(document, node_ids)
    source_value = document.get("task_source_node_id")
    target_value = document.get("task_target_node_id")
    source_id = str(source_value) if source_value is not None else None
    target_id = str(target_value) if target_value is not None else None
    valid_count = sum(
        is_valid_shortest_path(
            path,
            source_id,
            target_id,
            gold_length,
            node_ids,
            adjacency,
        )
        for path in normalized_paths
    )
    raw_path_count = len(raw_paths) if isinstance(raw_paths, list) else 0
    metrics.path_valid_rate = valid_count / raw_path_count if raw_path_count else 0.0

    duplicate_free = len(normalized_paths) == len(predicted_path_set)
    all_paths_well_formed = malformed_count == 0 and isinstance(
        prediction.get("paths"), list
    )
    metrics.path_exact_match_rate = float(
        metrics.path_length_accuracy == 1.0
        and all_paths_well_formed
        and duplicate_free
        and bool(gold_paths)
        and predicted_path_set == gold_paths
    )

    metrics.role_accuracy = annotation_accuracy(
        prediction.get("paths"),
        prediction.get("path_role_sequences"),
        role_by_id,
    )
    metrics.device_name_accuracy = annotation_accuracy(
        prediction.get("paths"),
        prediction.get("path_device_names"),
        name_by_id,
    )
    return metrics, {
        "predicted_path_count": raw_path_count,
        "gold_path_count": len(gold_paths),
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
    }


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def collect_sample_items(
    result_path: Path,
    split: str,
) -> list[tuple[str, Path, str]]:
    """返回 (split, 文件路径, 展示名称)，单文件和批量目录使用同一评价流程。"""

    if result_path.is_file():
        if result_path.suffix.lower() != ".json":
            raise ValueError(f"结果文件必须是 JSON: {result_path}")
        return [("single", result_path, result_path.name)]
    if not result_path.is_dir():
        raise FileNotFoundError(f"结果文件或目录不存在: {result_path}")

    selected_splits = ["train", "val"] if split == "all" else [split]
    existing_split_dirs = [
        (item, result_path / item)
        for item in selected_splits
        if (result_path / item).is_dir()
    ]
    items: list[tuple[str, Path, str]] = []
    if existing_split_dirs:
        missing_splits = [
            item for item in selected_splits if not (result_path / item).is_dir()
        ]
        if missing_splits:
            raise FileNotFoundError(
                "缺少推理结果划分目录: " + ", ".join(missing_splits)
            )
        for split_name, split_root in existing_split_dirs:
            for path in sorted(split_root.rglob("*.json")):
                if path.is_file():
                    items.append(
                        (split_name, path, str(path.relative_to(split_root)))
                    )
        return items

    # 允许直接传入 vllm-results/shortest_path/val 这样的划分目录。
    direct_split = split if split != "all" else result_path.name
    return [
        (direct_split, path, str(path.relative_to(result_path)))
        for path in sorted(result_path.rglob("*.json"))
        if path.is_file()
    ]


def init_swanlab(args: argparse.Namespace, result_path: Path) -> Any | None:
    if args.disable_swanlab:
        return None
    swanlab = import_swanlab()
    color_key = experiment_color_key(args, result_path)
    experiment_color = deterministic_experiment_color(
        args.swanlab_experiment,
        args.swanlab_color_seed,
        color_key,
    )
    swanlab.init(
        project=args.swanlab_project,
        experiment_name=args.swanlab_experiment,
        mode=args.swanlab_mode,
        color=experiment_color,
        config={
            "script": Path(sys.argv[0]).name,
            "result_path": str(result_path),
            "split": args.split,
            "aggregation": "running macro average",
            "metrics": list(METRIC_NAMES),
            "swanlab_experiment_color": experiment_color,
            "swanlab_color_seed": args.swanlab_color_seed,
            "swanlab_color_key": color_key,
        },
    )
    return swanlab


def log_swanlab_metrics(
    swanlab: Any | None,
    step: int,
    sample_metrics: dict[str, float],
    metric_sums: dict[str, float],
) -> None:
    if swanlab is None:
        return
    payload: dict[str, float] = {}
    for name in METRIC_NAMES:
        payload[f"sample/{name}"] = float(sample_metrics[name])
        payload[f"eval/{name}"] = float(metric_sums[name] / step)
    swanlab.log(payload, step=step)


def json_table_text(value: Any) -> str:
    if value is None:
        return ""
    return json.dumps(value, ensure_ascii=False, indent=2)


def build_sample_table_row(
    json_name: str,
    document: dict[str, Any] | None,
) -> list[str]:
    if document is None:
        return [json_name, "", "", ""]
    context = {
        key: value
        for key, value in document.items()
        if key not in {
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


def log_sample_table(swanlab: Any | None, table_rows: list[list[str]]) -> None:
    if swanlab is None:
        return
    echarts = getattr(swanlab, "echarts", None)
    table_class = getattr(echarts, "Table", None) if echarts is not None else None
    if table_class is None:
        raise RuntimeError(
            "当前 SwanLab 版本不支持 swanlab.echarts.Table，请升级 SwanLab"
        )
    table = table_class()
    table.add(
        ["json_name", "context", "answer", "model-output"],
        table_rows,
    )
    swanlab.log({"sample/details": table})


def finish_swanlab(swanlab: Any | None) -> None:
    if swanlab is None:
        return
    finish = getattr(swanlab, "finish", None)
    if callable(finish):
        finish()


def main() -> None:
    args = parse_args()
    result_path = args.result_path.resolve()
    output_dir = args.output_dir.resolve()
    sample_items = collect_sample_items(result_path, args.split)
    if not sample_items:
        raise FileNotFoundError(f"没有找到推理结果 JSON: {result_path}")

    rows: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    sample_table_rows: list[list[str]] = []
    metric_sums = {name: 0.0 for name in METRIC_NAMES}
    successful_model_returns = 0
    swanlab = init_swanlab(args, result_path)

    for index, (split, path, relative_path) in enumerate(sample_items, start=1):
        document: dict[str, Any] | None = None
        metrics = SampleMetrics()
        counts = {
            "predicted_path_count": 0,
            "gold_path_count": 0,
            "true_positive": 0,
            "false_positive": 0,
            "false_negative": 0,
        }
        model_returned = False
        error_reason = ""
        try:
            document = load_json_object(path)
            run_info = document.get("vllm-run")
            if not isinstance(run_info, dict):
                run_info = document.get("opencode-run")
            model_returned = bool(
                isinstance(run_info, dict)
                and run_info.get("success") is True
                and isinstance(document.get("model-output"), dict)
            )
            if model_returned:
                successful_model_returns += 1
            elif isinstance(run_info, dict):
                error_reason = str(run_info.get("error") or "model-output unavailable")
            else:
                error_reason = "missing inference run metadata"
            metrics, counts = evaluate_document(document)
        except Exception as error:  # noqa: BLE001 - 坏结果记零并继续。
            error_reason = f"{type(error).__name__}: {error}"

        json_name = (
            relative_path if split == "single" else f"{split}/{relative_path}"
        )
        sample_table_rows.append(build_sample_table_row(json_name, document))

        metric_values = asdict(metrics)
        for name in METRIC_NAMES:
            metric_sums[name] += metric_values[name]
        log_swanlab_metrics(
            swanlab,
            step=index,
            sample_metrics=metric_values,
            metric_sums=metric_sums,
        )
        row = {
            "split": split,
            "source_file": relative_path,
            "model_returned": model_returned,
            "error_reason": error_reason,
            **counts,
            **{name: round(metric_values[name], 8) for name in METRIC_NAMES},
        }
        rows.append(row)
        if error_reason:
            errors.append(
                {"split": split, "source_file": relative_path, "error": error_reason}
            )

        if args.progress_interval > 0 and (
            index % args.progress_interval == 0 or index == len(sample_items)
        ):
            print(f"评价进度 {index}/{len(sample_items)}", flush=True)

    sample_count = len(rows)
    aggregate_metrics = {
        name: round(metric_sums[name] / sample_count, 8) for name in METRIC_NAMES
    }
    summary = {
        "result_path": str(result_path),
        "output_dir": str(output_dir),
        "splits": sorted({item[0] for item in sample_items}),
        "aggregation": "macro: evaluate each sample, then average",
        "sample_count": sample_count,
        "successful_model_returns": successful_model_returns,
        "failed_model_returns": sample_count - successful_model_returns,
        "swanlab_experiment_color": deterministic_experiment_color(
            args.swanlab_experiment,
            args.swanlab_color_seed,
            experiment_color_key(args, result_path),
        ),
        "swanlab_color_seed": args.swanlab_color_seed,
        "swanlab_color_key": experiment_color_key(args, result_path),
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
            "predicted_path_count",
            "gold_path_count",
            "true_positive",
            "false_positive",
            "false_negative",
            *METRIC_NAMES,
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
    log_sample_table(swanlab, sample_table_rows)
    finish_swanlab(swanlab)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
