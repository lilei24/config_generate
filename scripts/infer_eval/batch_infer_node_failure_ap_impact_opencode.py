#!/usr/bin/env python3
"""使用 OpenCode 批量推理节点故障 AP 影响面任务。"""

from task_batch_inference_common import (
    create_opencode_parser,
    run_opencode,
    validate_opencode_arguments,
)
from task_inference_specs import NODE_FAILURE_AP_IMPACT_SPEC


def main() -> None:
    parser = create_opencode_parser(
        __doc__ or "",
        NODE_FAILURE_AP_IMPACT_SPEC,
    )
    args = parser.parse_args()
    validate_opencode_arguments(parser, args)
    run_opencode(args, NODE_FAILURE_AP_IMPACT_SPEC)


if __name__ == "__main__":
    main()
