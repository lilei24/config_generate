#!/usr/bin/env python3
"""SwanLab batch inference where target keys are given and only values are predicted."""

from __future__ import annotations

from typing import Any

import batch_infer_qa_swanlab as base
from batch_infer_qa_mask_value import build_user_prompt


def run(args: Any) -> None:
    base.build_user_prompt = build_user_prompt
    base.run(args)


def parse_args() -> Any:
    return base.parse_args()


def main() -> None:
    run(parse_args())


if __name__ == "__main__":
    main()
