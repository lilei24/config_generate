# 任务数据集构建

将原始拓扑转换为可自动验证的图计算与网络业务任务。

## 脚本索引

| 脚本 | 功能 |
|---|---|
| [build_ap_pair_via_core_path_dataset.py](build_ap_pair_via_core_path_dataset.md) | 构造两个 AP 必须经过指定 CORE 的全部最短物理路径任务数据集。 |
| [build_device_type_statistics_dataset.py](build_device_type_statistics_dataset.md) | 构造按物理设备类型统计设备名称的任务数据集。 |
| [build_link_failure_reroute_dataset.py](build_link_failure_reroute_dataset.md) | 从原始拓扑构造单链路故障绕行任务数据集。 |
| [build_link_port_prediction_dataset.py](build_link_port_prediction_dataset.md) | 构造隐藏目标链路 LEFTPORT、RIGHTPORT 和 LABEL 的端口预测任务数据集。 |
| [build_uplink_node_path_dataset.py](build_uplink_node_path_dataset.md) | 构造“上行节点路径查询”任务数据集。 |
| [build_node_failure_ap_impact_dataset.py](build_node_failure_ap_impact_dataset.md) | 构造“指定非 AP 节点故障后哪些 AP 失联”的正向影响面任务数据集。 |
| [build_node_failure_reroute_dataset_from_raw.py](build_node_failure_reroute_dataset_from_raw.md) | 直接从原始拓扑构造单节点故障绕行任务数据集。 |
| [build_reachable_leaf_nodes_dataset.py](build_reachable_leaf_nodes_dataset.md) | 构造从单个目标节点出发查找全部可达叶子节点的任务数据集。 |
| [build_shortest_path_dataset.py](build_shortest_path_dataset.md) | 构造两个节点之间最短链路任务数据集。 |
| [build_vlan_constrained_shortest_path_dataset.py](build_vlan_constrained_shortest_path_dataset.md) | 构造指定 VLAN 下的交换机约束最短路径绕行任务数据集。 |

## 使用原则

1. 先阅读对应脚本文档中的功能和统计口径，再确认输入目录。
2. 使用 `--help` 核对服务器代码版本的实际参数。
3. 构建、推理和评估结果建议使用不同根目录，避免覆盖原始数据。
4. 批量运行前先用少量 JSON 验证输出结构和异常记录。

[返回文档总览](../../README.md)
