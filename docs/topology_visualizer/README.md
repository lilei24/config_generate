# 拓扑可视化

将原始拓扑和推理结果转换为无需服务端的交互式 HTML。

## 脚本索引

| 脚本 | 功能 |
|---|---|
| [generate_topology_visualizations.py](generate_topology_visualizations.md) | 为 `train`、`val`、`with_answer` 或 `without_answer` 中的拓扑 JSON 生成交互式 HTML。 |
| [visualize_node_failure_reroute_dataset.py](visualize_node_failure_reroute_dataset.md) | 可视化节点故障绕行任务，区分故障节点、失效链路和标准绕行路径。 |
| [visualize_node_failure_ap_impact_dataset.py](visualize_node_failure_ap_impact_dataset.md) | 可视化节点故障影响 AP 任务，区分故障节点、失效链路和答案中的失联 AP。 |

## 使用原则

1. 先阅读对应脚本文档中的功能和统计口径，再确认输入目录。
2. 使用 `--help` 核对服务器代码版本的实际参数。
3. 构建、推理和评估结果建议使用不同根目录，避免覆盖原始数据。
4. 批量运行前先用少量 JSON 验证输出结构和异常记录。

[返回文档总览](../README.md)
