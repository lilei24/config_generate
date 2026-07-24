#!/usr/bin/env python3
"""使用 OpenAI-compatible vLLM 批量推理节点故障绕行路径任务。"""

from task_batch_inference_common import (
    create_vllm_parser,
    run_vllm,
    validate_vllm_arguments,
)
from task_inference_specs import NODE_FAILURE_REROUTE_SPEC


def main() -> None:
    parser = create_vllm_parser(__doc__ or "", NODE_FAILURE_REROUTE_SPEC)
    args = parser.parse_args()
    validate_vllm_arguments(parser, args)
    run_vllm(args, NODE_FAILURE_REROUTE_SPEC)


if __name__ == "__main__":
    main()
