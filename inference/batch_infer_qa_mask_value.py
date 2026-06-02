#!/usr/bin/env python3
"""Batch inference where target keys are given and only values are predicted."""

from __future__ import annotations

import json
from typing import Any, Dict, Tuple

import batch_infer_qa as base


VALUE_PLACEHOLDER = "<VALUE_TO_PREDICT>"


USER_PROMPT_TEMPLATE = """你是一个网络配置补全助手，给定一个网络拓扑上下文，其中包含：
1.deviceGroups: 设备组级别的信息和配置。
2.nodes: 节点级别的信息和配置。
3.links: 节点之间的连接关系
你的任务是根据上下文，为目标配置补全缺失的 value。
【重要说明】：
- 目标配置的所有 key 都已经在“目标配置 key 骨架”中给出，包括顶层 key 和所有嵌套 key；
- 你只需要预测每个 `<VALUE_TO_PREDICT>` 对应的 value；
- `<VALUE_TO_PREDICT>` 只是占位符，不是字符串值，最终输出中不能保留这个占位符；
- 请输出真实 JSON value，value 类型可以是 string、number、boolean、null、object 或 array；
- 如果应为布尔值，请输出 true/false，不要输出 "true"/"false"；
- 如果应为数字，请输出数字，不要输出字符串数字；
- 如果应为字符串，请输出合法 JSON 字符串；
- 不要新增、删除、重命名任何 key；
- 不要改变对象、数组和字段层级结构；
- 如果某个 value 难以确定，也必须保留对应 key，并根据上下文预测最合理的 value。
【推理规则】：
- 优先参考与目标节点直接相连的邻居节点中的语义相似配置；
- 不要输出解释、思考过程、额外文本；
- 不要输出 <think>、</think> 或任何思维链内容；
- 最终回答只输出补全 value 后的完整 JSON 对象本身，不要输出 Markdown 代码块，不要输出其他内容。
【输出格式案例1】：
```json
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
```
【输出格式案例2】:
```json
"vty-business" : {
    "vty-screen-length": 24,
    "vty-time-out": 10
}
```
【输入网络拓扑上下文】:
```json
{input_value}
```
【你需要补全的配置要求】:
```text
{question_value}
```
【目标配置 key 骨架】:
```json
{target_skeleton}
```
"""


def build_key_skeleton(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: build_key_skeleton(child) for key, child in value.items()}
    if isinstance(value, list):
        return [build_key_skeleton(item) for item in value]
    return VALUE_PLACEHOLDER


def build_user_prompt(sample: Dict[str, Any]) -> Tuple[str, Any]:
    question_value = sample["prompt"]
    input_value = json.dumps(sample["input"], indent=2, ensure_ascii=False)
    target_skeleton = json.dumps(build_key_skeleton(sample["output"]), indent=2, ensure_ascii=False)
    prompt = (
        USER_PROMPT_TEMPLATE.replace("{input_value}", input_value)
        .replace("{question_value}", question_value)
        .replace("{target_skeleton}", target_skeleton)
    )
    return prompt, sample["output"]


def run(args: Any) -> None:
    base.build_user_prompt = build_user_prompt
    base.run(args)


def parse_args() -> Any:
    return base.parse_args()


def main() -> None:
    run(parse_args())


if __name__ == "__main__":
    main()
