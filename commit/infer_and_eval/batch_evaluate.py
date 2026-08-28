#!/usr/bin/env python3
"""独立评估七类拓扑任务的推理结果，并上传 SwanLab。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from evaluation_common import (
    collect_result_files,
    evaluate_document,
    inference_success,
    load_json_object,
    metric_names,
    write_csv,
)
from task_specs import TASK_SPECS, get_task_spec


DETAIL_NAMES = (
    "predicted_count",
    "gold_count",
    "true_positive",
    "false_positive",
    "false_negative",
    "malformed_count",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", choices=sorted(TASK_SPECS), required=True)
    parser.add_argument(
        "--result-root",
        type=Path,
        default=None,
        help="推理结果根目录；默认使用任务注册表中的目录",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="本地评估结果目录；默认使用任务注册表中的目录",
    )
    parser.add_argument("--split", choices=("train", "val", "all"), default="val")
    parser.add_argument(
        "--error-policy",
        choices=("zero", "exclude"),
        default="zero",
        help=(
            "推理或评估失败样本的聚合策略：zero 按零分计入平均，"
            "exclude 从平均分母排除；默认: %(default)s"
        ),
    )
    parser.add_argument("--progress-interval", type=int, default=100)
    parser.add_argument("--swanlab-project", default="topology-agent-evaluation")
    parser.add_argument("--swanlab-experiment", default=None)
    parser.add_argument("--swanlab-mode", default="cloud")
    parser.add_argument("--disable-swanlab", action="store_true")
    args = parser.parse_args()
    if args.progress_interval < 0:
        parser.error("--progress-interval 不能小于 0")
    return args


def init_swanlab(
    args: argparse.Namespace,
    task_name: str,
    result_root: Path,
    names: tuple[str, ...],
) -> Any | None:
    if args.disable_swanlab:
        return None
    try:
        import swanlab
    except ImportError as error:
        raise RuntimeError(
            "缺少 swanlab 依赖，请执行 pip install swanlab，"
            "或使用 --disable-swanlab"
        ) from error
    experiment = args.swanlab_experiment or f"{task_name}-evaluation"
    swanlab.init(
        project=args.swanlab_project,
        experiment_name=experiment,
        mode=args.swanlab_mode,
        config={
            "task": task_name,
            "result_root": str(result_root),
            "split": args.split,
            "error_policy": args.error_policy,
            "aggregation": "running macro average",
            "metrics": list(names),
        },
    )
    return swanlab


def finish_swanlab(swanlab: Any | None) -> None:
    if swanlab is not None and callable(getattr(swanlab, "finish", None)):
        swanlab.finish()


def main() -> None:
    args = parse_args()
    spec = get_task_spec(args.task)
    result_root = (args.result_root or spec.result_root).resolve()
    output_dir = (args.output_dir or spec.evaluation_root).resolve()
    files = collect_result_files(result_root, args.split)
    if not files:
        raise FileNotFoundError("没有找到推理结果 JSON")

    names = metric_names(spec)
    sums = {name: 0.0 for name in names}
    rows: list[dict[str, Any]] = []
    error_rows: list[dict[str, Any]] = []
    averaging_count = 0
    successful_evaluations = 0
    swanlab = init_swanlab(args, spec.name, result_root, names)

    try:
        for step, (split, path, relative_path) in enumerate(files, start=1):
            metrics = {name: 0.0 for name in names}
            details = {name: 0 for name in DETAIL_NAMES}
            model_returned = False
            evaluation_success = False
            error_reason = ""
            try:
                document = load_json_object(path)
                model_returned, error_reason = inference_success(document)
                if model_returned:
                    result = evaluate_document(document, spec)
                    metrics.update(result.metrics)
                    details.update(result.details)
                    evaluation_success = True
                    successful_evaluations += 1
            except Exception as error:  # 坏文件按策略记零或排除。
                error_reason = f"{type(error).__name__}: {error}"

            included = evaluation_success or args.error_policy == "zero"
            if included:
                averaging_count += 1
                for name in names:
                    sums[name] += metrics[name]

            if swanlab is not None:
                payload: dict[str, float] = {}
                if evaluation_success or args.error_policy == "zero":
                    payload.update(
                        {f"sample/{name}": float(metrics[name]) for name in names}
                    )
                if averaging_count:
                    payload.update(
                        {
                            f"eval/{name}": float(sums[name] / averaging_count)
                            for name in names
                        }
                    )
                payload["eval/model_success_rate"] = successful_evaluations / step
                payload["eval/averaging_sample_count"] = float(averaging_count)
                swanlab.log(payload, step=step)

            rows.append(
                {
                    "split": split,
                    "source_file": relative_path,
                    "model_returned": model_returned,
                    "evaluation_success": evaluation_success,
                    "included_in_average": included,
                    "error_reason": error_reason,
                    **details,
                    **{name: round(metrics[name], 8) for name in names},
                }
            )
            if error_reason:
                error_rows.append(
                    {
                        "split": split,
                        "source_file": relative_path,
                        "error": error_reason,
                    }
                )
            if args.progress_interval and (
                step % args.progress_interval == 0 or step == len(files)
            ):
                print(
                    f"[{step}/{len(files)}] evaluated={successful_evaluations} "
                    f"average_denominator={averaging_count}",
                    flush=True,
                )
    finally:
        finish_swanlab(swanlab)

    aggregate = {
        name: round(sums[name] / averaging_count, 8) if averaging_count else None
        for name in names
    }
    summary = {
        "task": spec.name,
        "result_root": str(result_root),
        "output_dir": str(output_dir),
        "split": args.split,
        "error_policy": args.error_policy,
        "total_samples": len(files),
        "successful_evaluations": successful_evaluations,
        "failed_evaluations": len(files) - successful_evaluations,
        "averaging_sample_count": averaging_count,
        "model_success_rate": round(successful_evaluations / len(files), 8),
        "metrics": aggregate,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(
        output_dir / "per_sample_metrics.csv",
        [
            "split",
            "source_file",
            "model_returned",
            "evaluation_success",
            "included_in_average",
            "error_reason",
            *DETAIL_NAMES,
            *names,
        ],
        rows,
    )
    write_csv(
        output_dir / "evaluation_errors.csv",
        ["split", "source_file", "error"],
        error_rows,
    )
    (output_dir / "evaluation_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

