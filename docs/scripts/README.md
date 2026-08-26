# 通用数据分析与配置生成

负责原始拓扑质量分析、配置生成 QA 构建以及模型辅助业务分析。

## 脚本索引

| 脚本 | 功能 |
|---|---|
| [analyze_dataset.py](analyze_dataset.md) | Analyze graph JSON datasets for node config generation. |
| [analyze_device_model_distribution.py](analyze_device_model_distribution.md) | 统计拓扑数据集中所有节点的物理设备 MODEL 分布。 |
| [analyze_device_role_combinations.py](analyze_device_role_combinations.md) | 排除指定角色共现文件后，统计剩余文件的 DEVICEROLE 组合分布。 |
| [analyze_device_role_cooccurrence.py](analyze_device_role_cooccurrence.md) | 统计多个 DEVICEROLE 在同一个拓扑 JSON 中同时出现的文件数。 |
| [analyze_edge_counts.py](analyze_edge_counts.md) | Analyze only edge counts for train/val graph JSON files. |
| [analyze_graph_max_finite_shortest_path.py](analyze_graph_max_finite_shortest_path.md) | 统计原始数据集中每张图的最大有限最短路长度。 |
| [analyze_graphs_without_ap_role.py](analyze_graphs_without_ap_role.md) | 统计原始拓扑数据中不包含 DEVICEROLE=AP 节点的 JSON 文件。 |
| [analyze_large_graph_edge_counts.py](analyze_large_graph_edge_counts.md) | 筛选节点数超过指定阈值的图，将节点数和 links 数量写入一个 CSV。 |
| [analyze_leaf_node_role_distribution.py](analyze_leaf_node_role_distribution.md) | 统计原始拓扑数据中叶子节点的 DEVICEROLE 分布。 |
| [analyze_nearest_core_path_length.py](analyze_nearest_core_path_length.md) | 统计“上行节点路径查询”任务数据集中的最短路径长度。 |
| [analyze_node_counts.py](analyze_node_counts.md) | Analyze only node counts for train/val graph JSON files. |
| [analyze_node_name_uniqueness.py](analyze_node_name_uniqueness.md) | 分析原始拓扑数据中 devices.NAME 能否唯一标识节点。 |
| [analyze_qa_tokens.py](analyze_qa_tokens.md) | 统计 QA 样本 input 的 token 分布，并生成柱状图。 |
| [analyze_top_level_key_centrality.py](analyze_top_level_key_centrality.md) | Analyze top-level key distributions over node centrality. |
| [analyze_vlan_config_locations.py](analyze_vlan_config_locations.md) | 按正则查找 node/deviceGroup 配置中的 VLAN Key，并输出源码行号和配置层级。 |
| [analyze_vlan_schema.py](analyze_vlan_schema.md) | 发现原始拓扑数据中所有 key 名包含 vlan 的 JSON Schema 路径。 |
| [batch_analyze_network_business_vllm.py](batch_analyze_network_business_vllm.md) | 调用 OpenAI-compatible vLLM 服务批量生成通信网络业务分析与 HTML 报告。 |
| [batch_analyze_vlan_vllm.py](batch_analyze_vlan_vllm.md) | 使用 OpenAI-compatible vLLM 服务逐文件分析原始拓扑中的 VLAN 情况。 |
| [batch_infer_shortest_path_opencode.py](batch_infer_shortest_path_opencode.md) | 兼容入口：请优先使用 scripts/infer_eval 下的新版脚本。 |
| [build_config_generation_dataset.py](build_config_generation_dataset.md) | 从图 JSON 数据集构造配置生成任务的 QA 样本。 |
| [build_config_generation_dataset_pruned.py](build_config_generation_dataset_pruned.md) | 从图 JSON 数据集构造配置生成任务的 QA 样本，并裁剪过长上下文。 |
| [prune_config_generation_qa.py](prune_config_generation_qa.md) | 对已生成的配置生成 QA 样本再次裁剪 input 图上下文。 |

## 使用原则

1. 先阅读对应脚本文档中的功能和统计口径，再确认输入目录。
2. 使用 `--help` 核对服务器代码版本的实际参数。
3. 构建、推理和评估结果建议使用不同根目录，避免覆盖原始数据。
4. 批量运行前先用少量 JSON 验证输出结构和异常记录。

[返回文档总览](../README.md)
