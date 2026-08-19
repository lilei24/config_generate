#!/usr/bin/env python3
"""使用 OpenAI-compatible vLLM 批量推理可达叶子节点任务。"""

from task_batch_inference_common import (
    create_vllm_parser,
    run_vllm,
    validate_vllm_arguments,
)
from task_inference_specs import REACHABLE_LEAF_NODES_SPEC


def main() -> None:
    parser = create_vllm_parser(__doc__ or "", REACHABLE_LEAF_NODES_SPEC)
    args = parser.parse_args()
    validate_vllm_arguments(parser, args)
    run_vllm(args, REACHABLE_LEAF_NODES_SPEC)


if __name__ == "__main__":
    main()
