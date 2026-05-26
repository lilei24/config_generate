#!/usr/bin/env python3
"""Batch inference for QA config completion files with a vLLM/OpenAI server."""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


DEFAULT_QA_ROOT = Path("520QA")
DEFAULT_OUTPUT_ROOT = Path("inference-results")
DEFAULT_BASE_URL = "http://localhost:8000/v1"
DEFAULT_API_KEY = "empty"
DEFAULT_MODEL = "qwen3-8b"
DEFAULT_TEMPERATURE = 0.2
DEFAULT_PROGRESS_INTERVAL = 50


USER_PROMPT_TEMPLATE = """你是一个网络配置补全助手，给定一个网络拓扑上下文，其中包含：
1.deviceGroups: 设备组级别的信息和配置。
2.nodes: 节点级别的信息和配置。
3.links: 节点之间的连接关系
你的任务是根据上下文，为目标设备补全缺失的配置对象。
【推理规则】：
- 优先参考与目标节点直接相连的邻居节点中的语义相似配置；
- 不要输出解释、思考过程、额外文本；
- 不要输出 <think>、</think> 或任何思维链内容；
- 只输出目标配置的JSON, 不要输出其他内容。
【输出格式案例1】：
"ap-ssids": {
    "global-https-redirect-enable": false,
    "globalWeChatEnable": false,
    "ssids": [
        {
            "dot11r": {
                "reassociate-timeout-time": 1,
                "private": "disable",
                "enable": false
            },
            "vlan-entrys": {
                "vlan-entry": [
                    {
                        "priority": 0,
                        "vlan-id": 2
                    }
                ]
            }
        }
    ]
}
【输出格式案例2】:
"vty-business" : {
    "vty-screen-length": 24,
    "vty-time-out": 10
}
【输入网络拓扑上下文】:
{input_value}
【你需要补全的配置要求】:
{question_value}
"""


def import_openai_client() -> Any:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("Missing dependency: pip install openai") from exc
    return OpenAI


def iter_qa_files(qa_root: Path, split: str, tasks: Iterable[str]) -> Iterable[Tuple[str, Path]]:
    for task_dir in tasks:
        root = qa_root / split / task_dir
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.json")):
            if path.is_file():
                yield task_dir, path


def load_qa(path: Path) -> Tuple[Optional[Dict[str, Any]], str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return None, "bad_json: %s" % exc
    if not isinstance(data, dict):
        return None, "sample_not_object"
    for key in ("prompt", "input", "output"):
        if key not in data:
            return None, "missing_key: %s" % key
    return data, ""


def build_user_prompt(sample: Dict[str, Any]) -> Tuple[str, str]:
    question_value = sample["prompt"]
    input_value = json.dumps(sample["input"], indent=2, ensure_ascii=False)
    answer_value = json.dumps(sample["output"], indent=2, ensure_ascii=False)
    # 模板中包含 JSON 示例的大括号，不能用 str.format。
    prompt = USER_PROMPT_TEMPLATE.replace("{input_value}", input_value).replace("{question_value}", question_value)
    return prompt, answer_value


def strip_think(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    return text.strip()


def chat_completion(
    client: Any,
    model: str,
    prompt: str,
    temperature: float,
    disable_thinking: bool,
) -> str:
    kwargs: Dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
    }
    if disable_thinking:
        kwargs["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}
    completion = client.chat.completions.create(**kwargs)
    return strip_think(completion.choices[0].message.content or "")


def result_path(output_root: Path, split: str, task_dir: str, qa_root: Path, input_path: Path) -> Path:
    rel = input_path.relative_to(qa_root / split / task_dir)
    return output_root / split / task_dir / rel


def write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def append_jsonl(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(data, ensure_ascii=False) + "\n")


def print_progress(done: int, total: int, started_at: float) -> None:
    elapsed = max(0.001, time.time() - started_at)
    speed = done / elapsed
    remain = max(0, total - done)
    eta = remain / speed if speed > 0 else 0
    percent = done / total * 100 if total else 100
    print(
        "[infer] %s/%s files (%.2f%%), elapsed %.1fs, %.2f files/s, eta %.1fs"
        % (done, total, percent, elapsed, speed, eta),
        flush=True,
    )


def run(args: argparse.Namespace) -> None:
    OpenAI = import_openai_client()
    client = OpenAI(base_url=args.base_url, api_key=args.api_key)
    tasks = [task.strip() for task in args.tasks.split(",") if task.strip()]
    qa_files = list(iter_qa_files(args.qa_root, args.split, tasks))
    if args.limit:
        qa_files = qa_files[: args.limit]

    print("[infer] start: %s files" % len(qa_files), flush=True)
    started_at = time.time()
    failure_log = args.output_root / args.split / "failures.jsonl"
    if failure_log.exists() and not args.append_failures:
        failure_log.unlink()

    for index, (task_dir, path) in enumerate(qa_files, start=1):
        out_path = result_path(args.output_root, args.split, task_dir, args.qa_root, path)
        data, error = load_qa(path)
        answer_value = ""
        if error:
            result = {"model-ouput": "", "answer": "", "error": error}
            append_jsonl(failure_log, {"file": str(path), "task": task_dir, "error": error})
        else:
            prompt, answer_value = build_user_prompt(data)
            try:
                model_output = chat_completion(
                    client=client,
                    model=args.model,
                    prompt=prompt,
                    temperature=args.temperature,
                    disable_thinking=not args.enable_thinking,
                )
                result = {
                    "model-ouput": model_output,
                    "answer": answer_value,
                }
            except Exception as exc:  # noqa: BLE001
                error = str(exc)
                result = {
                    "model-ouput": "",
                    "answer": answer_value,
                    "error": error,
                }
                append_jsonl(failure_log, {"file": str(path), "task": task_dir, "error": error})

        write_json(out_path, result)
        if args.progress_interval > 0 and (index % args.progress_interval == 0 or index == len(qa_files)):
            print_progress(index, len(qa_files), started_at)

    print("[infer] done. results: %s" % args.output_root, flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Batch inference for QA config completion JSON files.")
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
    parser.add_argument("--append-failures", action="store_true", help="Append to existing failures.jsonl.")
    return parser.parse_args()


def main() -> None:
    run(parse_args())


if __name__ == "__main__":
    main()
