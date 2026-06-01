#!/usr/bin/env python3
"""Batch inference with per-sample SwanLab logging."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict, List

from batch_evaluate_qa import add_metric, empty_metric_accumulator, finalize_accumulator
from batch_infer_qa import (
    DEFAULT_API_KEY,
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    DEFAULT_OUTPUT_ROOT,
    DEFAULT_PROGRESS_INTERVAL,
    DEFAULT_QA_ROOT,
    DEFAULT_TEMPERATURE,
    append_jsonl,
    build_user_prompt,
    chat_completion,
    import_openai_client,
    iter_qa_files,
    load_qa,
    parse_model_output,
    print_progress,
    result_path,
    write_json,
)
from metric import evaluate_json
from swanlab_utils import (
    base_runtime_config,
    finish_swanlab,
    import_swanlab,
    make_table,
    metric_log_values,
    sample_table_headers,
    sample_table_row,
)


DEFAULT_SWANLAB_PROJECT = "config-generation"
DEFAULT_SWANLAB_EXPERIMENT = "qwen3-8b-inference"
DEFAULT_SWANLAB_MODE = "cloud"
DEFAULT_SAMPLE_TABLE_LOG_INTERVAL = 50


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def sample_metric(parsed_output: Any, answer: Any) -> Dict[str, Any]:
    try:
        return evaluate_json(parsed_output, answer, array_mode="wildcard")
    except Exception as exc:  # noqa: BLE001
        return {"error": "metric_failed: %s" % exc}


def log_sample(
    swanlab: Any,
    index: int,
    metrics: Dict[str, Any],
    error: str = "",
) -> None:
    metric_payload: Dict[str, Any] = {
        "sample/index": index,
        "sample/has_error": int(bool(error)),
    }
    if "error" in metrics:
        metric_payload["sample/metric_failed"] = 1
    else:
        metric_payload["sample/metric_failed"] = 0
        metric_payload.update(metric_log_values(metrics, prefix="sample"))
    swanlab.log(metric_payload, step=index)


def log_running_eval(swanlab: Any, index: int, accumulator: Dict[str, Any]) -> None:
    if accumulator["sample_count"] <= 0:
        return
    metrics = finalize_accumulator(accumulator)
    swanlab.log(metric_log_values(metrics, prefix="eval"), step=index)


def log_sample_table(swanlab: Any, rows: List[List[Any]], step: int) -> None:
    table = make_table(swanlab, sample_table_headers(), rows)
    swanlab.log({"sample/table": table}, step=step)


def run(args: argparse.Namespace) -> None:
    swanlab = import_swanlab()
    swanlab.init(
        project=args.swanlab_project,
        experiment_name=args.swanlab_experiment,
        mode=args.swanlab_mode,
        config=base_runtime_config(args),
    )

    OpenAI = import_openai_client()
    client = OpenAI(base_url=args.base_url, api_key=args.api_key)
    tasks = [task.strip() for task in args.tasks.split(",") if task.strip()]
    qa_files = list(iter_qa_files(args.qa_root, args.split, tasks))
    if args.limit:
        qa_files = qa_files[: args.limit]

    print("[infer-swanlab] start: %s files" % len(qa_files), flush=True)
    swanlab.log({"run/total_files": len(qa_files)}, step=0)
    started_at = time.time()
    failure_log = args.output_root / args.split / "failures.jsonl"
    if failure_log.exists():
        failure_log.unlink()

    success_count = 0
    error_count = 0
    eval_accumulator = empty_metric_accumulator()
    sample_rows: List[List[Any]] = []
    for index, (task_dir, path) in enumerate(qa_files, start=1):
        out_path = result_path(args.output_root, args.split, task_dir, args.qa_root, path)
        data, error = load_qa(path)
        answer_value: Any = ""
        metrics: Dict[str, Any] = {}

        if error:
            error_count += 1
            result = {"model-ouput": "", "answer": "", "error": error}
            append_jsonl(failure_log, {"file": str(path), "task": task_dir, "error": error})
            sample_rows.append(sample_table_row(index, path.name, "", answer_value, False, error, metrics))
            log_sample(
                swanlab=swanlab,
                index=index,
                metrics=metrics,
                error=error,
            )
        else:
            prompt, answer_value = build_user_prompt(data)
            try:
                raw_model_output = chat_completion(
                    client=client,
                    model=args.model,
                    prompt=prompt,
                    temperature=args.temperature,
                    disable_thinking=not args.enable_thinking,
                )
                parsed_output, parse_error = parse_model_output(raw_model_output)
                result = {
                    "model-ouput": parsed_output,
                    "answer": answer_value,
                }
                if parse_error:
                    result["model-output-parse-error"] = parse_error
                    result["model-output-raw"] = raw_model_output

                metrics = sample_metric(parsed_output, answer_value)
                success_count += 1
                model_returned = not bool(parse_error)
                sample_rows.append(
                    sample_table_row(
                        index,
                        path.name,
                        parsed_output if model_returned else raw_model_output,
                        answer_value,
                        model_returned,
                        "model-output-parse-error: %s" % parse_error if parse_error else "",
                        metrics if model_returned else {},
                    )
                )
                log_sample(
                    swanlab=swanlab,
                    index=index,
                    metrics=metrics,
                    error=parse_error,
                )
                if "error" not in metrics:
                    add_metric(eval_accumulator, metrics)
            except Exception as exc:  # noqa: BLE001
                error = str(exc)
                error_count += 1
                result = {
                    "model-ouput": "",
                    "answer": answer_value,
                    "error": error,
                }
                append_jsonl(failure_log, {"file": str(path), "task": task_dir, "error": error})
                sample_rows.append(sample_table_row(index, path.name, "", answer_value, False, error, metrics))
                log_sample(
                    swanlab=swanlab,
                    index=index,
                    metrics=metrics,
                    error=error,
                )

        write_json(out_path, result)
        swanlab.log(
            {
                "run/processed_files": index,
                "run/success_files": success_count,
                "run/error_files": error_count,
                "run/error_rate": error_count / index if index else 0.0,
            },
            step=index,
        )
        log_running_eval(swanlab, index, eval_accumulator)
        if args.sample_table_log_interval > 0 and (
            index % args.sample_table_log_interval == 0 or index == len(qa_files)
        ):
            log_sample_table(swanlab, sample_rows, step=index)
        if args.progress_interval > 0 and (index % args.progress_interval == 0 or index == len(qa_files)):
            print_progress(index, len(qa_files), started_at)

    print("[infer-swanlab] done. results: %s" % args.output_root, flush=True)
    finish_swanlab(swanlab)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Batch inference with per-sample SwanLab logging.")
    parser.add_argument("--qa-root", type=Path, default=DEFAULT_QA_ROOT, help="QA root directory. Default: 520QA")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT, help="Output root. Default: inference-results")
    parser.add_argument("--split", default="train", help="Dataset split to run. Default: train")
    parser.add_argument(
        "--tasks",
        default="device_config_qa,node_config_qa",
        help="Comma-separated task dirs under split. Default: device_config_qa,node_config_qa",
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="OpenAI-compatible base URL.")
    parser.add_argument("--api-key", default=DEFAULT_API_KEY, help="API key. vLLM often accepts any value.")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Served model name.")
    parser.add_argument("--temperature", type=float, default=DEFAULT_TEMPERATURE)
    parser.add_argument("--progress-interval", type=int, default=DEFAULT_PROGRESS_INTERVAL)
    parser.add_argument("--limit", type=int, default=0, help="Only run first N files. 0 means all.")
    parser.add_argument("--enable-thinking", action="store_true", help="Do not disable Qwen thinking in extra_body.")
    parser.add_argument("--swanlab-project", default=DEFAULT_SWANLAB_PROJECT)
    parser.add_argument("--swanlab-experiment", default=DEFAULT_SWANLAB_EXPERIMENT)
    parser.add_argument("--swanlab-mode", default=DEFAULT_SWANLAB_MODE)
    parser.add_argument(
        "--sample-table-log-interval",
        type=int,
        default=DEFAULT_SAMPLE_TABLE_LOG_INTERVAL,
        help="Log accumulated sample table every N files. 0 disables table logging.",
    )
    return parser.parse_args()


def main() -> None:
    run(parse_args())


if __name__ == "__main__":
    main()
