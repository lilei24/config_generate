#!/usr/bin/env python3
"""使用 OpenAI-compatible vLLM 批量推理 VLAN 约束最短路径任务。"""

from task_batch_inference_common import (
    create_vllm_parser,
    run_vllm,
    validate_vllm_arguments,
)
from task_inference_specs import VLAN_CONSTRAINED_SHORTEST_PATH_SPEC


def main() -> None:
    parser = create_vllm_parser(
        __doc__ or "",
        VLAN_CONSTRAINED_SHORTEST_PATH_SPEC,
    )
    args = parser.parse_args()
    validate_vllm_arguments(parser, args)
    run_vllm(args, VLAN_CONSTRAINED_SHORTEST_PATH_SPEC)


if __name__ == "__main__":
    main()
