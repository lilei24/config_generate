"""Small SwanLab helpers shared by inference and evaluation scripts."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List, Optional


def import_swanlab() -> Any:
    try:
        import swanlab
    except ImportError as exc:
        raise RuntimeError("Missing dependency: pip install swanlab") from exc
    return swanlab


def current_git_commit(repo_root: Optional[Path] = None) -> str:
    root = repo_root or Path.cwd()
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:  # noqa: BLE001
        return ""
    return result.stdout.strip()


def base_runtime_config(args: Any) -> Dict[str, Any]:
    return {
        "python": sys.version.split()[0],
        "git_commit": current_git_commit(),
        "script": Path(sys.argv[0]).name,
        **{
            key: str(value) if isinstance(value, Path) else value
            for key, value in vars(args).items()
            if key not in {"swanlab_project", "swanlab_experiment", "swanlab_mode"}
        },
    }


def metric_log_values(metrics: Dict[str, Any], prefix: str = "") -> Dict[str, Any]:
    field_path = metrics.get("field_path", {})
    leaf_triple = metrics.get("leaf_triple", {})
    value_accuracy = metrics.get("value_accuracy", {})
    hm = metrics.get("hallucination_missing", {})
    base = ("%s/" % prefix.strip("/")) if prefix else ""
    return {
        base + "field_path/precision": field_path.get("precision", 0.0),
        base + "field_path/recall": field_path.get("recall", 0.0),
        base + "field_path/f1": field_path.get("f1", 0.0),
        base + "leaf_triple/precision": leaf_triple.get("precision", 0.0),
        base + "leaf_triple/recall": leaf_triple.get("recall", 0.0),
        base + "leaf_triple/f1": leaf_triple.get("f1", 0.0),
        base + "value_accuracy/accuracy": value_accuracy.get("accuracy", 0.0),
        base + "hallucination_missing/hallucinated_rate": hm.get("hallucinated_rate", 0.0),
        base + "hallucination_missing/missing_rate": hm.get("missing_rate", 0.0),
    }


def macro_metric_log_values(metrics_list: List[Dict[str, Any]], prefix: str = "") -> Dict[str, Any]:
    if not metrics_list:
        return {}
    rows = [metric_log_values(metrics, prefix=prefix) for metrics in metrics_list]
    keys = sorted({key for row in rows for key in row})
    return {
        key: mean(float(row.get(key, 0.0)) for row in rows)
        for key in keys
    }


def running_eval_log_values(
    accumulator: Dict[str, Any],
    metrics_list: List[Dict[str, Any]],
    mode: str,
    prefix: str = "eval",
) -> Dict[str, Any]:
    if mode == "macro":
        return macro_metric_log_values(metrics_list, prefix=prefix)
    if mode != "micro":
        raise ValueError("Unsupported eval metric mode: %s" % mode)

    from batch_evaluate_qa import finalize_accumulator

    return metric_log_values(finalize_accumulator(accumulator), prefix=prefix)


def sample_table_headers() -> list[str]:
    return [
        "step",
        "sample_filename",
        "prompt",
        "input",
        "model-output",
        "answer",
        "model_returned",
        "error_reason",
        "field_path_precision",
        "field_path_recall",
        "field_path_f1",
        "leaf_triple_precision",
        "leaf_triple_recall",
        "leaf_triple_f1",
        "value_accuracy",
        "hallucinated_rate",
        "missing_rate",
    ]


def sample_table_row(
    step: int,
    sample_filename: str,
    prompt: Any,
    input_value: Any,
    model_output: Any,
    answer: Any,
    model_returned: bool,
    error_reason: str,
    metrics: Dict[str, Any],
) -> list[Any]:
    field_path = metrics.get("field_path", {}) if "error" not in metrics else {}
    leaf_triple = metrics.get("leaf_triple", {}) if "error" not in metrics else {}
    value_accuracy = metrics.get("value_accuracy", {}) if "error" not in metrics else {}
    hm = metrics.get("hallucination_missing", {}) if "error" not in metrics else {}
    return [
        step,
        sample_filename,
        json_dumps(prompt),
        json_dumps(input_value),
        json_dumps(model_output),
        json_dumps(answer),
        bool(model_returned),
        error_reason,
        field_path.get("precision", ""),
        field_path.get("recall", ""),
        field_path.get("f1", ""),
        leaf_triple.get("precision", ""),
        leaf_triple.get("recall", ""),
        leaf_triple.get("f1", ""),
        value_accuracy.get("accuracy", ""),
        hm.get("hallucinated_rate", ""),
        hm.get("missing_rate", ""),
    ]


def json_dumps(value: Any) -> str:
    import json

    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, indent=2)


def make_table(swanlab: Any, headers: list[str], rows: list[list[Any]]) -> Any:
    echarts = getattr(swanlab, "echarts", None)
    table_cls = getattr(echarts, "Table", None) if echarts is not None else None
    if table_cls is None:
        raise RuntimeError("Current SwanLab package does not provide swanlab.echarts.Table.")
    table = table_cls()
    table.add(headers, rows)
    return table


def finish_swanlab(swanlab: Any) -> None:
    finish = getattr(swanlab, "finish", None)
    if callable(finish):
        finish()
