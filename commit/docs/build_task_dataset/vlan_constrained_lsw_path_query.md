# vlan约束的交换机路径查询

**对应脚本：** [`build_vlan_constrained_shortest_path_dataset.py`](../../build_task_dataset_scripts/build_vlan_constrained_shortest_path_dataset.py)

[返回任务构造索引](README.md)

## 任务目标

给定两个 LSW 节点和一个 VLAN，查询路径中每条链路两端连接端口均允许该 VLAN 通行时的全部最短路径。

## 业务价值

任务将交换机接口配置理解与图搜索结合，能够检验模型是否真正使用链路两端端口的 VLAN 放行配置，而不是只在无约束物理拓扑上寻找最短路径。

## VLAN 链路约束

- 只使用物理类型为 `LSW` 的节点。
- `links[].link.LEFTPORT` 对应 `source` 节点接口。
- `links[].link.RIGHTPORT` 对应 `target` 节点接口。
- 端口名称与 `lsw-interfaces-business.lsw-interface[].interface-name` 唯一匹配。
- `allow-through-vlan=all` 表示允许全部 VLAN。
- 逗号列表表示多个离散 VLAN，例如 `1,3,8`。
- 连续范围会展开，例如 `1-5` 表示 VLAN 1、2、3、4、5。
- 一条链路允许的 VLAN 集合为两端接口允许集合的交集。

## 构造过程

1. 筛选 LSW 节点并读取其 `configs` 中的交换机接口配置。
2. 过滤自环、端点缺失、非 LSW 链路、端口名称缺失和接口无法唯一匹配的链路。
3. 分别解析链路两端接口的 `allow-through-vlan`，构造严格有效的基础 LSW 图。
4. 收集数据中显式出现的 VLAN ID；无法完整解析的端口不用于约束链路。
5. 对每个 VLAN，只保留两端端口都允许该 VLAN 的链路，得到 VLAN 约束子图。
6. 枚举约束子图中的可达 LSW 节点对，计算全部等长最短路径。
7. 比较约束路径与严格基础图中的无约束最短路径，只保留 VLAN 约束路径更长的绕行候选。
8. 每张图若存在多个候选，选择 VLAN 约束路径最长的一个；平局按 VLAN、源和目标 ID 稳定选择。

## 新增任务字段

| 字段 | 含义 |
|---|---|
| `task_source_node_id` | 源 LSW 节点 ID |
| `task_target_node_id` | 目标 LSW 节点 ID |
| `task_vlan_id` | 路径必须端到端允许的 VLAN ID |
| `task_question` | 指定节点对和 VLAN 的约束最短路径问题 |
| `task_answer.path_length` | VLAN 约束下的最短跳数 |
| `task_answer.paths` | VLAN 约束下的全部最短路径 |

`task_vlan_id` 是任务条件，不要求模型在 `task_answer` 中重复输出。

## 跳过条件

- 没有至少两个 LSW 节点。
- 没有端口双端唯一匹配的 LSW 链路。
- 没有显式可解析的 VLAN ID。
- 任意 VLAN 下均不存在可达节点对。
- 不存在约束路径长于无约束路径的候选。
- 标准答案路径数超过限制。

## 参数

| 参数 | 默认值 | 作用 |
|---|---:|---|
| `--dataset-root` | `datasets` | 原始数据集根目录 |
| `--output-root` | `vlan_constrained_shortest_path_dataset` | 输出目录 |
| `--splits` | `train val` | 数据划分 |
| `--max-answer-paths` | `1000` | 标准答案路径数上限 |
| `--max-range-size` | `4096` | 单个 VLAN 范围最大展开数量 |
| `--config-fields` | `configs` | 扫描的节点配置字段 |
| `--progress-interval` | `100` | 进度打印间隔 |
| `--indent` | `2` | JSON 缩进空格数 |
