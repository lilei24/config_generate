"""Small SwanLab helpers shared by inference and evaluation scripts."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional


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


def finish_swanlab(swanlab: Any) -> None:
    finish = getattr(swanlab, "finish", None)
    if callable(finish):
        finish()
