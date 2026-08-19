#!/usr/bin/env python3
"""拓扑任务的数据路径、Prompt 和模型输出结构定义。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from task_batch_inference_common import (
    TaskInferenceSpec,
    validate_ap_impact_answer,
    validate_link_failure_answer,
    validate_link_port_answer,
    validate_neighborhood_reachability_answer,
    validate_path_answer,
    validate_reachable_leaf_nodes_answer,
)


SYSTEM_PROMPT = """你是网络物理拓扑分析助手。请严格根据给定拓扑计算答案，不得猜测不存在的节点或链路。不要输出解释、Markdown 代码块或思考过程，只输出一个合法 JSON 对象。"""

PATH_OUTPUT_EXAMPLE = """{
  "path_length": 3,
  "paths": [
    ["NODE_A", "NODE_B", "NODE_C", "NODE_D"]
  ]
}"""

AP_IMPACT_OUTPUT_EXAMPLE = """{
  "disconnected_ap_ids": ["AP_NODE_1", "AP_NODE_2"]
}"""

LINK_PORT_SYSTEM_PROMPT = """你是网络链路端口补全助手。请严格依据给定的已遮挡拓扑、链路两端设备信息和其他链路端口规律预测目标端口。不得虚构额外字段，不要输出解释、Markdown 代码块或思考过程，只输出一个合法 JSON 对象。"""

LINK_PORT_OUTPUT_EXAMPLE = """{
  "LEFTPORT": "预测的source侧端口字符串",
  "RIGHTPORT": "预测的target侧端口字符串"
}"""

LINK_FAILURE_OUTPUT_EXAMPLES = """输出格式示例 1（故障后仍然连通）：
{
  "connected": true,
  "path_length": 3,
  "paths": [
    ["NODE_A", "NODE_B", "NODE_C", "NODE_D"]
  ]
}

输出格式示例 2（故障后不连通）：
{
  "connected": false,
  "path_length": null,
  "paths": []
}"""

NEIGHBORHOOD_REACHABILITY_OUTPUT_EXAMPLE = """{
  "one_hop_neighbor_node_ids": ["NODE_B"],
  "reachable_node_ids": ["NODE_B", "NODE_C", "NODE_D"]
}"""

REACHABLE_LEAF_NODES_OUTPUT_EXAMPLE = """{
  "reachable_leaf_node_ids": ["NODE_A", "NODE_C", "NODE_D"]
}"""


def compact_json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def required_string(
    sample: dict[str, Any],
    field_name: str,
) -> str:
    value = sample.get(field_name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"样本缺少有效的 {field_name}")
    return value


def task_metadata(sample: dict[str, Any]) -> dict[str, Any]:
    metadata = sample.get("task_metadata")
    return metadata if isinstance(metadata, dict) else {}


def build_nearest_vllm_prompt(sample: dict[str, Any]) -> str:
    return f"""请完成输入 JSON 中 task_question 描述的最近目标角色路径任务。

要求：
1. path_length 是最短链路跳数，即路径节点数减一。
2. 找到指定角色下距离源 AP 最近的全部目标设备。
3. 如果存在多条等长最短路径，必须全部输出。
4. paths 使用节点 ID，并按照源 AP 到目标设备的方向排列。
5. 只输出以下结构的 JSON 对象：
{PATH_OUTPUT_EXAMPLE}

【完整任务 JSON】
{compact_json(sample)}
"""


def build_nearest_opencode_prompt(
    site: str,
    sample: dict[str, Any],
) -> str:
    source_id = required_string(sample, "task_source_node_id")
    target_role = task_metadata(sample).get("target_role")
    if not isinstance(target_role, str) or not target_role:
        raise ValueError("样本缺少有效的 task_metadata.target_role")
    return f"""你是网络物理拓扑分析 Agent。

请根据站点名称调用拓扑数据 Provider，并使用 topograph_understand 的图计算能力。
不得根据节点 ID 或设备名称猜测答案。

站点名称：{site}
源 AP 节点 ID：{source_id}
目标设备角色：{target_role}

任务：找到该 AP 到 DEVICEROLE={target_role} 的最近设备，并返回到所有等距最近
目标设备的全部最短物理路径。

要求：
1. path_length 是最短链路跳数，即路径节点数减一。
2. paths 使用节点 ID，并从源 AP 指向目标设备。
3. 多个等距最近设备和多条等长最短路径必须全部输出。
4. 只输出 JSON，不输出解释、代码块或思考过程。

输出格式：
{PATH_OUTPUT_EXAMPLE}"""


def build_reroute_vllm_prompt(sample: dict[str, Any]) -> str:
    return f"""请完成输入 JSON 中 task_question 描述的节点故障绕行任务。

要求：
1. 计算时必须将 task_failed_node_id 及其关联链路从拓扑中删除。
2. path_length 是故障后最短链路跳数，即路径节点数减一。
3. 如果存在多条等长最短路径，必须全部输出。
4. paths 使用节点 ID，从 task_source_node_id 指向 task_target_node_id。
5. 任何预测路径都不得经过故障节点。
6. 只输出以下结构的 JSON 对象：
{PATH_OUTPUT_EXAMPLE}

【完整任务 JSON】
{compact_json(sample)}
"""


def build_reroute_opencode_prompt(
    site: str,
    sample: dict[str, Any],
) -> str:
    source_id = required_string(sample, "task_source_node_id")
    target_id = required_string(sample, "task_target_node_id")
    failed_id = required_string(sample, "task_failed_node_id")
    return f"""你是网络物理拓扑故障绕行分析 Agent。

请根据站点名称调用拓扑数据 Provider，并使用 topograph_understand 的图计算能力。

站点名称：{site}
源节点 ID：{source_id}
目标节点 ID：{target_id}
故障节点 ID：{failed_id}

任务：从拓扑中排除故障节点及其关联链路，查找源节点到目标节点当前可用的全部
最短物理路径。

要求：
1. 路径不得经过故障节点。
2. path_length 是故障后的最短链路跳数。
3. 多条等长最短路径必须全部输出。
4. paths 使用节点 ID，并从源节点指向目标节点。
5. 只输出 JSON，不输出解释、代码块或思考过程。

输出格式：
{PATH_OUTPUT_EXAMPLE}"""


def build_link_failure_vllm_prompt(sample: dict[str, Any]) -> str:
    source_id = required_string(sample, "task_source_node_id")
    target_id = required_string(sample, "task_target_node_id")
    failed_link = sample.get("task_failed_link")
    if not isinstance(failed_link, dict):
        raise ValueError("样本缺少有效的 task_failed_link")
    link_index = failed_link.get("link_index")
    if isinstance(link_index, bool) or not isinstance(link_index, int):
        raise ValueError("task_failed_link.link_index 必须是整数")
    return f"""请完成输入 JSON 中 task_question 描述的链路故障绕行任务。

源节点 ID：{source_id}
目标节点 ID：{target_id}
故障链路索引：{link_index}

要求：
1. 计算时只排除 links[{link_index}] 指定的物理链路，保留链路两端节点及其他链路。
2. 如果同一对节点之间存在其他链路，不得将它们一并删除。
3. connected 表示故障后源节点能否到达目标节点。
4. 连通时，path_length 是故障后的最短链路跳数，并输出全部等长最短路径。
5. 失联时，connected 为 false、path_length 为 null、paths 为空数组。
6. paths 使用节点 ID，从源节点指向目标节点，且不得经过故障链路。
7. 只输出包含 connected、path_length、paths 的 JSON 对象，不输出解释、代码块或思考过程。

{LINK_FAILURE_OUTPUT_EXAMPLES}

【完整任务 JSON】
{compact_json(sample)}
"""


def build_link_failure_opencode_prompt(
    site: str,
    sample: dict[str, Any],
) -> str:
    # 当前只提供 vLLM 入口；保留同规格构造器便于后续接入 OpenCode。
    return build_link_failure_vllm_prompt(sample).replace(
        "【完整任务 JSON】",
        f"站点标识：{site}\n\n【完整任务 JSON】",
        1,
    )


def build_neighborhood_reachability_vllm_prompt(
    sample: dict[str, Any],
) -> str:
    target_node_id = required_string(sample, "task_target_node_id")
    return f"""请完成输入 JSON 中 task_question 描述的节点邻居与可达性任务。

目标节点 ID：{target_node_id}

要求：
1. 将 links 表示的物理链路按无向图处理，不使用 source/target 判断方向。
2. one_hop_neighbor_node_ids 只包含与目标节点直接相连的节点。
3. reachable_node_ids 包含经过一条或多条链路可达的全部节点。
4. 两个列表都不得包含目标节点自身，也不得包含重复节点 ID。
5. 不同连通分量中的节点不能输出。
6. 节点必须使用 nodes[].id，并按字典序排列。
7. 只输出以下结构的 JSON 对象，不输出解释、代码块或思考过程：
{NEIGHBORHOOD_REACHABILITY_OUTPUT_EXAMPLE}

【完整任务 JSON】
{compact_json(sample)}
"""


def build_neighborhood_reachability_opencode_prompt(
    site: str,
    sample: dict[str, Any],
) -> str:
    return build_neighborhood_reachability_vllm_prompt(sample).replace(
        "【完整任务 JSON】",
        f"站点标识：{site}\n\n【完整任务 JSON】",
        1,
    )


def build_reachable_leaf_nodes_vllm_prompt(
    sample: dict[str, Any],
) -> str:
    target_node_id = required_string(sample, "task_target_node_id")
    return f"""请完成输入 JSON 中 task_question 描述的可达叶子节点查找任务。

目标节点 ID：{target_node_id}

要求：
1. 将 links 表示的物理链路按无向图处理，不使用 source/target 判断方向。
2. 叶子节点是无向简单图中唯一邻居数量等于 1 的节点。
3. 同一对节点之间的重复链路只算一个邻居关系。
4. 只输出目标节点所在连通分量中可达的叶子节点。
5. 结果不得包含目标节点自身，也不得包含重复节点 ID。
6. 节点必须使用 nodes[].id，并按字典序排列。
7. 只输出以下结构的 JSON 对象，不输出解释、代码块或思考过程：
{REACHABLE_LEAF_NODES_OUTPUT_EXAMPLE}

【完整任务 JSON】
{compact_json(sample)}
"""


def build_reachable_leaf_nodes_opencode_prompt(
    site: str,
    sample: dict[str, Any],
) -> str:
    return build_reachable_leaf_nodes_vllm_prompt(sample).replace(
        "【完整任务 JSON】",
        f"站点标识：{site}\n\n【完整任务 JSON】",
        1,
    )


def build_impact_vllm_prompt(sample: dict[str, Any]) -> str:
    return f"""请完成输入 JSON 中 task_question 描述的节点故障 AP 影响面任务。

要求：
1. 严格使用 task_target_role_priority 确定每个 AP 正常情况下的最高优先级上游目标。
2. 同一最高优先级下所有正常可达节点都是该 AP 的上游目标。
3. 删除 task_failed_node_id 及其关联链路后重新判断连通性。
4. AP 无法到达任何原正常上游目标时才判定为失联。
5. 只返回失联 AP 的节点 ID，不得返回设备名称或非 AP 节点。
6. 只输出以下结构的 JSON 对象：
{AP_IMPACT_OUTPUT_EXAMPLE}

【完整任务 JSON】
{compact_json(sample)}
"""


def build_impact_opencode_prompt(
    site: str,
    sample: dict[str, Any],
) -> str:
    failed_id = required_string(sample, "task_failed_node_id")
    priorities = sample.get("task_target_role_priority")
    if (
        not isinstance(priorities, list)
        or not priorities
        or not all(isinstance(role, str) and role for role in priorities)
    ):
        raise ValueError("样本缺少有效的 task_target_role_priority")
    priority_text = " > ".join(priorities)
    return f"""你是网络拓扑故障影响面分析 Agent。

请根据站点名称调用拓扑数据 Provider，并使用 topograph_understand 的连通性和
路径计算能力完成分析。

站点名称：{site}
故障节点 ID：{failed_id}
上游角色优先级：{priority_text}

正常情况下，每个 AP 的上游目标定义为：按照上述优先级，选择该 AP 能够到达的
第一个角色；该角色下所有正常可达节点都属于它的上游目标。

现在删除故障节点及其关联链路。如果某个 AP 无法再到达任何一个原正常上游目标，
则该 AP 失联；即使还能到达更低优先级设备，也仍然视为失联。

请返回所有失联 AP 的节点 ID。只输出 JSON，不输出解释、代码块或思考过程。

输出格式：
{AP_IMPACT_OUTPUT_EXAMPLE}"""


def target_link_index(sample: dict[str, Any]) -> int:
    value = sample.get("task_target_link_index")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("样本缺少有效的 task_target_link_index")
    return value


def build_link_port_vllm_prompt(sample: dict[str, Any]) -> str:
    source_id = required_string(sample, "task_source_node_id")
    target_id = required_string(sample, "task_target_node_id")
    link_index = target_link_index(sample)
    return f"""请完成输入 JSON 中 task_question 描述的链路端口补全任务。

目标链路索引：{link_index}
source 节点 ID：{source_id}
target 节点 ID：{target_id}

要求：
1. LEFTPORT 对应 source 侧端口，RIGHTPORT 对应 target 侧端口。
2. 目标链路的 LEFTPORT、RIGHTPORT 和 LABEL 已删除，不得假设 LABEL 仍然存在。
3. 优先参考两端设备类型、型号、角色以及其他链路的端口命名和分配规律。
4. 端口值必须保持预测的完整原始字符串格式。
5. 只输出以下结构的 JSON，不输出解释、代码块或思考过程：
{LINK_PORT_OUTPUT_EXAMPLE}

【完整遮挡任务 JSON】
{compact_json(sample)}
"""


def build_link_port_opencode_prompt(
    site: str,
    sample: dict[str, Any],
) -> str:
    source_id = required_string(sample, "task_source_node_id")
    target_id = required_string(sample, "task_target_node_id")
    link_index = target_link_index(sample)
    return f"""你是网络链路端口补全 Agent。

站点标识：{site}
目标链路索引：{link_index}
source 节点 ID：{source_id}
target 节点 ID：{target_id}

本 Prompt 已提供完整的遮挡任务 JSON。禁止调用原始站点拓扑 Provider，因为原始数据中的目标端口和 LABEL 属于标准答案，会造成答案泄漏。

请根据目标链路两端设备信息、其他链路端口和全站点端口命名规律补全端口。

要求：
1. LEFTPORT 对应 source 侧端口，RIGHTPORT 对应 target 侧端口。
2. 端口值必须保持完整字符串格式。
3. 只输出 JSON，不输出解释、代码块或思考过程。

输出格式：
{LINK_PORT_OUTPUT_EXAMPLE}

【完整遮挡任务 JSON】
{compact_json(sample)}
"""


NEAREST_CORE_SPEC = TaskInferenceSpec(
    task_name="nearest_reachable_role_path",
    default_dataset_root=Path("nearest_core_dataset"),
    default_vllm_output_root=Path("vllm-results/nearest_core"),
    default_opencode_output_root=Path("opencode-results/nearest_core"),
    default_model="qwen3-8b",
    system_prompt=SYSTEM_PROMPT,
    build_vllm_prompt=build_nearest_vllm_prompt,
    build_opencode_prompt=build_nearest_opencode_prompt,
    validate_answer=validate_path_answer,
)

NODE_FAILURE_REROUTE_SPEC = TaskInferenceSpec(
    task_name="node_failure_reroute",
    default_dataset_root=Path("node_failure_reroute_dataset_from_raw"),
    default_vllm_output_root=Path("vllm-results/node_failure_reroute"),
    default_opencode_output_root=Path("opencode-results/node_failure_reroute"),
    default_model="qwen3-8b",
    system_prompt=SYSTEM_PROMPT,
    build_vllm_prompt=build_reroute_vllm_prompt,
    build_opencode_prompt=build_reroute_opencode_prompt,
    validate_answer=validate_path_answer,
)

LINK_FAILURE_REROUTE_SPEC = TaskInferenceSpec(
    task_name="link_failure_reroute",
    default_dataset_root=Path("link_failure_reroute_dataset"),
    default_vllm_output_root=Path("vllm-results/link_failure_reroute"),
    default_opencode_output_root=Path("opencode-results/link_failure_reroute"),
    default_model="qwen3-8b",
    system_prompt=SYSTEM_PROMPT,
    build_vllm_prompt=build_link_failure_vllm_prompt,
    build_opencode_prompt=build_link_failure_opencode_prompt,
    validate_answer=validate_link_failure_answer,
)

NODE_NEIGHBORHOOD_REACHABILITY_SPEC = TaskInferenceSpec(
    task_name="node_neighborhood_and_reachability",
    default_dataset_root=Path("node_neighborhood_reachability_dataset"),
    default_vllm_output_root=Path("vllm-results/node_neighborhood_reachability"),
    default_opencode_output_root=Path(
        "opencode-results/node_neighborhood_reachability"
    ),
    default_model="qwen3-8b",
    system_prompt=SYSTEM_PROMPT,
    build_vllm_prompt=build_neighborhood_reachability_vllm_prompt,
    build_opencode_prompt=build_neighborhood_reachability_opencode_prompt,
    validate_answer=validate_neighborhood_reachability_answer,
)

REACHABLE_LEAF_NODES_SPEC = TaskInferenceSpec(
    task_name="reachable_leaf_nodes",
    default_dataset_root=Path("node_neighborhood_reachability_dataset"),
    default_vllm_output_root=Path("vllm-results/reachable_leaf_nodes"),
    default_opencode_output_root=Path("opencode-results/reachable_leaf_nodes"),
    default_model="qwen3-8b",
    system_prompt=SYSTEM_PROMPT,
    build_vllm_prompt=build_reachable_leaf_nodes_vllm_prompt,
    build_opencode_prompt=build_reachable_leaf_nodes_opencode_prompt,
    validate_answer=validate_reachable_leaf_nodes_answer,
)

NODE_FAILURE_AP_IMPACT_SPEC = TaskInferenceSpec(
    task_name="node_failure_ap_impact",
    default_dataset_root=Path("node_failure_ap_impact_dataset"),
    default_vllm_output_root=Path("vllm-results/node_failure_ap_impact"),
    default_opencode_output_root=Path("opencode-results/node_failure_ap_impact"),
    default_model="qwen3-8b",
    system_prompt=SYSTEM_PROMPT,
    build_vllm_prompt=build_impact_vllm_prompt,
    build_opencode_prompt=build_impact_opencode_prompt,
    validate_answer=validate_ap_impact_answer,
)

LINK_PORT_PREDICTION_SPEC = TaskInferenceSpec(
    task_name="link_port_prediction",
    default_dataset_root=Path("link_port_prediction_dataset"),
    default_vllm_output_root=Path("vllm-results/link_port_prediction"),
    default_opencode_output_root=Path("opencode-results/link_port_prediction"),
    default_model="qwen3-8b",
    system_prompt=LINK_PORT_SYSTEM_PROMPT,
    build_vllm_prompt=build_link_port_vllm_prompt,
    build_opencode_prompt=build_link_port_opencode_prompt,
    validate_answer=validate_link_port_answer,
)
