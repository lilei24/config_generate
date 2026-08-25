# VLAN 专项分析

围绕交换机接口、VLAN 集合关系和 VLAN 约束路径开展数据验证。

## 脚本索引

| 脚本 | 功能 |
|---|---|
| [analyze_cloud_ap_interface_vlan_union.py](analyze_cloud_ap_interface_vlan_union.md) | 分析 cloud-ap-interface 中 process VLAN 是否等于 sw 与 trunk VLAN 的并集。 |
| [analyze_devicevlan_business_type_distribution.py](analyze_devicevlan_business_type_distribution.md) | 统计 devicevlan-business 四类配置所在节点的物理设备类型分布。 |
| [analyze_lsw_allow_vlan_path_distribution.py](analyze_lsw_allow_vlan_path_distribution.md) | 统计双端接口均含 allow-through-vlan 的 LSW 链路路径分布。 |
| [analyze_lsw_gvlan_union.py](analyze_lsw_gvlan_union.md) | 分析节点 lsw-gvlan-business 是否等于接口 VLAN 配置的并集。 |
| [analyze_lsw_link_interfaces.py](analyze_lsw_link_interfaces.md) | 匹配直连交换机链路两端的 LSW 接口配置。 |
| [analyze_lsw_vlan_constrained_path_distribution.py](analyze_lsw_vlan_constrained_path_distribution.md) | 统计至少有一个 VLAN 可端到端通过的 LSW 最短路径分布。 |
| [validate_vlan_task_unconstrained_paths.py](validate_vlan_task_unconstrained_paths.md) | 验证 VLAN 约束路径任务在忽略 VLAN 时的 LSW 最短路径。 |
| [visualize_vlan_inference_results.py](visualize_vlan_inference_results.md) | 将 VLAN 约束路径推理结果生成为可交互的静态 HTML。 |

## 使用原则

1. 先阅读对应脚本文档中的功能和统计口径，再确认输入目录。
2. 使用 `--help` 核对服务器代码版本的实际参数。
3. 构建、推理和评估结果建议使用不同根目录，避免覆盖原始数据。
4. 批量运行前先用少量 JSON 验证输出结构和异常记录。

[返回文档总览](../../README.md)
