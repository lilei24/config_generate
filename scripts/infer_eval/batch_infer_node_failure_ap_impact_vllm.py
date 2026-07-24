#!/usr/bin/env python3
"""使用 OpenAI-compatible vLLM 批量推理节点故障 AP 影响面任务。"""

from task_batch_inference_common import (
    create_vllm_parser,
    run_vllm,
    validate_vllm_arguments,
)
from task_inference_specs import NODE_FAILURE_AP_IMPACT_SPEC


def main() -> None:
    parser = create_vllm_parser(
        __doc__ or "",
        NODE_FAILURE_AP_IMPACT_SPEC,
    )
    args = parser.parse_args()
    validate_vllm_arguments(parser, args)
    run_vllm(args, NODE_FAILURE_AP_IMPACT_SPEC)


if __name__ == "__main__":
    main()
