#!/usr/bin/env python3
"""Run config QA inference with an OpenAI-compatible chat server."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from inference.openai_compatible_client import OpenAICompatibleClient, first_message_content
from inference.prompt import DEFAULT_SYSTEM_PROMPT, build_messages, extract_json_value


DEFAULT_CONFIG = Path("config/inference_config.yaml")
TASK_DIRS = {
    "node": "node_config_qa",
    "device": "device_config_qa",
}


def parse_scalar(value: str) -> Any:
    value = value.strip()
    if not value:
        return ""
    if value[0] in {"'", '"'} and value[-1:] == value[0]:
        return value[1:-1]
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in {"null", "none"}:
        return None
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def load_config(path: Path) -> Dict[str, Any]:
    """Load a simple flat YAML or JSON config without third-party dependencies."""

    if path.suffix.lower() == ".json":
        return json.loads(path.read_text(encoding="utf-8"))

    config: Dict[str, Any] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "#" in line:
            line = line.split("#", 1)[0].rstrip()
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        config[key.strip()] = parse_scalar(value)
    return config


def iter_qa_files(qa_root: Path, splits: Iterable[str], tasks: Iterable[str]) -> Iterable[Tuple[str, str, Path]]:
    for split in splits:
        for task in tasks:
            task_dir = TASK_DIRS[task]
            root = qa_root / split / task_dir
            if not root.exists():
                continue
            for path in sorted(root.rglob("*.json")):
                if path.is_file():
                    yield split, task, path


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_one(
    client: OpenAICompatibleClient,
    sample_path: Path,
    model: str,
    system_prompt: str,
    input_json_indent: Optional[int],
    request_params: Dict[str, Any],
    include_gold: bool,
) -> Dict[str, Any]:
    sample = json.loads(sample_path.read_text(encoding="utf-8"))
    messages = build_messages(sample, system_prompt=system_prompt, input_json_indent=input_json_indent)
    started_at = time.time()
    response = client.chat_completion(model=model, messages=messages, **request_params)
    latency = time.time() - started_at
    response_text = first_message_content(response)

    parsed_json = None
    parse_error = ""
    try:
        parsed_json = extract_json_value(response_text)
    except Exception as exc:  # noqa: BLE001 - record invalid model JSON for later inspection.
        parse_error = str(exc)

    result: Dict[str, Any] = {
        "source_file": str(sample_path),
        "metadata": sample.get("metadata", {}),
        "request": {
            "model": model,
            "messages": messages,
            "params": request_params,
        },
        "response_text": response_text,
        "parsed_json": parsed_json,
        "parse_error": parse_error,
        "latency_seconds": round(latency, 4),
        "raw_response": response,
    }
    if include_gold:
        result["gold_output"] = sample.get("output")
    return result


def build_request_params(config: Dict[str, Any]) -> Dict[str, Any]:
    params: Dict[str, Any] = {
        "temperature": float(config.get("temperature", 0)),
        "top_p": float(config.get("top_p", 1)),
    }
    max_tokens = config.get("max_tokens")
    if max_tokens is not None:
        params["max_tokens"] = int(max_tokens)
    response_format = config.get("response_format")
    if response_format == "json_object":
        params["response_format"] = {"type": "json_object"}
    return params


def parse_csv_arg(value: Optional[str], default: List[str]) -> List[str]:
    if not value:
        return default
    return [item.strip() for item in value.split(",") if item.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run QA config generation inference via OpenAI-compatible API.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="Flat YAML or JSON config path.")
    parser.add_argument("--qa-root", type=Path, default=None, help="Override QA root directory.")
    parser.add_argument("--output-dir", type=Path, default=None, help="Override output directory.")
    parser.add_argument("--splits", default=None, help="Comma-separated splits, e.g. train,val.")
    parser.add_argument("--tasks", default=None, help="Comma-separated tasks: node,device.")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of samples to run.")
    parser.add_argument("--dry-run", action="store_true", help="Build requests but do not call the server.")
    args = parser.parse_args()

    config = load_config(args.config)
    qa_root = args.qa_root or Path(str(config.get("qa_root", "QA")))
    output_dir = args.output_dir or Path(str(config.get("output_dir", "inference_outputs")))
    splits = parse_csv_arg(args.splits, parse_csv_arg(str(config.get("splits", "train,val")), ["train", "val"]))
    tasks = parse_csv_arg(args.tasks, parse_csv_arg(str(config.get("tasks", "node,device")), ["node", "device"]))
    model = str(config.get("model", ""))
    if not model:
        raise ValueError("model is required in config")

    system_prompt = str(config.get("system_prompt", DEFAULT_SYSTEM_PROMPT))
    input_json_indent_value = config.get("input_json_indent", 2)
    input_json_indent = None if input_json_indent_value in {None, "compact"} else int(input_json_indent_value)
    include_gold = bool(config.get("include_gold", False))

    files = list(iter_qa_files(qa_root, splits, tasks))
    if args.limit is not None:
        files = files[: args.limit]

    request_params = build_request_params(config)
    client = OpenAICompatibleClient(
        base_url=str(config.get("base_url", "http://localhost:8000/v1")),
        api_key=str(config.get("api_key", "EMPTY")),
        timeout=float(config.get("timeout", 120)),
    )

    print("Running inference for %s samples with model=%s" % (len(files), model), flush=True)
    for index, (split, task, sample_path) in enumerate(files, start=1):
        rel_name = sample_path.name
        result_path = output_dir / split / TASK_DIRS[task] / rel_name
        if args.dry_run:
            sample = json.loads(sample_path.read_text(encoding="utf-8"))
            result = {
                "source_file": str(sample_path),
                "request": {
                    "model": model,
                    "messages": build_messages(sample, system_prompt, input_json_indent),
                    "params": request_params,
                },
                "dry_run": True,
            }
        else:
            try:
                result = run_one(client, sample_path, model, system_prompt, input_json_indent, request_params, include_gold)
            except Exception as exc:  # noqa: BLE001 - write per-sample failures and continue.
                result = {"source_file": str(sample_path), "error": str(exc)}
        write_json(result_path, result)
        print("[%s/%s] wrote %s" % (index, len(files), result_path), flush=True)


if __name__ == "__main__":
    main()
