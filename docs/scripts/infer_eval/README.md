# 批量推理与评估

统一执行 vLLM/OpenCode 推理、错误记录、指标计算和 SwanLab 观测。

## 脚本索引

| 脚本 | 功能 |
|---|---|
| [add_task_answers_to_results.py](add_task_answers_to_results.md) | 按相同相对路径将标准 task_answer 补充到推理结果 JSON。 |
| [analyze_shortest_path_inference_trend.py](analyze_shortest_path_inference_trend.md) | 按推理顺序分析最短路径任务指标及核心样本难度因素。 |
| [batch_infer_link_failure_reroute_vllm.py](batch_infer_link_failure_reroute_vllm.md) | 使用 OpenAI-compatible vLLM 批量推理链路故障绕行任务。 |
| [batch_infer_link_port_prediction_opencode.py](batch_infer_link_port_prediction_opencode.md) | 使用 OpenCode 批量推理链路端口预测任务。 |
| [batch_infer_link_port_prediction_vllm.py](batch_infer_link_port_prediction_vllm.md) | 使用 OpenAI-compatible vLLM 批量推理链路端口预测任务。 |
| [batch_infer_nearest_core_opencode.py](batch_infer_nearest_core_opencode.md) | 使用 OpenCode 批量推理 AP 到最近目标角色路径任务。 |
| [batch_infer_nearest_core_vllm.py](batch_infer_nearest_core_vllm.md) | 使用 OpenAI-compatible vLLM 批量推理 AP 到最近目标角色路径任务。 |
| [batch_infer_node_failure_ap_impact_opencode.py](batch_infer_node_failure_ap_impact_opencode.md) | 使用 OpenCode 批量推理节点故障 AP 影响面任务。 |
| [batch_infer_node_failure_ap_impact_vllm.py](batch_infer_node_failure_ap_impact_vllm.md) | 使用 OpenAI-compatible vLLM 批量推理节点故障 AP 影响面任务。 |
| [batch_infer_node_failure_reroute_opencode.py](batch_infer_node_failure_reroute_opencode.md) | 使用 OpenCode 批量推理节点故障绕行路径任务。 |
| [batch_infer_node_failure_reroute_vllm.py](batch_infer_node_failure_reroute_vllm.md) | 使用 OpenAI-compatible vLLM 批量推理节点故障绕行路径任务。 |
| [batch_infer_node_neighborhood_reachability_vllm.py](batch_infer_node_neighborhood_reachability_vllm.md) | 使用 OpenAI-compatible vLLM 批量推理节点邻居与可达性任务。 |
| [batch_infer_reachable_leaf_nodes_vllm.py](batch_infer_reachable_leaf_nodes_vllm.md) | 使用 OpenAI-compatible vLLM 批量推理可达叶子节点任务。 |
| [batch_infer_shortest_path_opencode.py](batch_infer_shortest_path_opencode.md) | 批量调用 OpenCode，完成两节点全部最短路径任务。 |
| [batch_infer_shortest_path_vllm.py](batch_infer_shortest_path_vllm.md) | 使用 OpenAI-compatible vLLM 服务批量执行两节点全部最短路径任务。 |
| [batch_infer_vlan_constrained_shortest_path_vllm.py](batch_infer_vlan_constrained_shortest_path_vllm.md) | 使用 OpenAI-compatible vLLM 批量推理 VLAN 约束最短路径任务。 |
| [evaluate_link_failure_reroute_results.py](evaluate_link_failure_reroute_results.md) | 评估单链路故障后的连通性和全部最短绕行路径。 |
| [evaluate_link_port_prediction_results.py](evaluate_link_port_prediction_results.md) | 评估链路 LEFTPORT、RIGHTPORT 预测结果。 |
| [evaluate_nearest_core_results.py](evaluate_nearest_core_results.md) | 评估 AP 到最近目标角色设备的全部最短路径推理结果。 |
| [evaluate_node_failure_ap_impact_results.py](evaluate_node_failure_ap_impact_results.md) | 评估指定节点故障后的失联 AP 集合推理结果。 |
| [evaluate_node_failure_reroute_results.py](evaluate_node_failure_reroute_results.md) | 评估节点故障后的全部最短绕行路径推理结果。 |
| [evaluate_node_neighborhood_reachability_results.py](evaluate_node_neighborhood_reachability_results.md) | 评估节点一阶邻居与全部可达节点集合推理结果。 |
| [evaluate_reachable_leaf_nodes_results.py](evaluate_reachable_leaf_nodes_results.md) | 评估可达叶子节点集合推理结果。 |
| [evaluate_shortest_path_results.py](evaluate_shortest_path_results.md) | 评价单个或一批最短路径推理结果，并将指标记录到 SwanLab。 |
| [evaluate_vlan_constrained_shortest_path_results.py](evaluate_vlan_constrained_shortest_path_results.md) | 评估指定 VLAN 下的交换机约束最短路径推理结果。 |
| [task_batch_inference_common.py](task_batch_inference_common.md) | 任务 2-5 批量推理脚本共用的 vLLM 与 OpenCode 调用框架。 |
| [task_evaluation_common.py](task_evaluation_common.md) | 任务评估脚本共用的批处理、SwanLab 记录和路径集合指标。 |
| [task_inference_specs.py](task_inference_specs.md) | 拓扑任务的数据路径、Prompt 和模型输出结构定义。 |
| [visualize_opencode_trace.py](visualize_opencode_trace.md) | 将 OpenCode stdout JSON 事件流转换为离线 HTML 轨迹查看器。 |

## 使用原则

1. 先阅读对应脚本文档中的功能和统计口径，再确认输入目录。
2. 使用 `--help` 核对服务器代码版本的实际参数。
3. 构建、推理和评估结果建议使用不同根目录，避免覆盖原始数据。
4. 批量运行前先用少量 JSON 验证输出结构和异常记录。

[返回文档总览](../../README.md)
