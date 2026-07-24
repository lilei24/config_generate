#!/usr/bin/env python3
"""使用 OpenCode 批量推理节点故障绕行路径任务。"""

from task_batch_inference_common import (
    create_opencode_parser,
    run_opencode,
    validate_opencode_arguments,
)
from task_inference_specs import NODE_FAILURE_REROUTE_SPEC


def main() -> None:
    parser = create_opencode_parser(__doc__ or "", NODE_FAILURE_REROUTE_SPEC)
    args = parser.parse_args()
    validate_opencode_arguments(parser, args)
    run_opencode(args, NODE_FAILURE_REROUTE_SPEC)


if __name__ == "__main__":
    main()
