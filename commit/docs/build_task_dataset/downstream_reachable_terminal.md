# 可达下游终端节点

**对应脚本：** [`build_downstream_reachable_terminal_dataset.py`](../../build_task_dataset_scripts/build_downstream_reachable_terminal_dataset.py)

[返回任务构造索引](README.md)

## 任务目标

给定一个 `CORE` 或 `Firewall` 上游节点，查询唯一归属于它的全部下游终端节点 ID。

## 业务价值

任务用于评估 Agent 对核心节点、终端叶子、同角色上游竞争和最短距离归属的理解，可作为下游设备发现、故障影响面和网络域划分的基础数据。

## 终端与归属定义

终端候选必须同时满足：

- 在无向物理拓扑中的度数为 1。
- `device.TYPE` 为 `AP` 或 `LSW`。
- `DEVICEROLE` 不是 `CORE` 或 `Firewall`。

归属计算按角色独立进行：

- 所选节点为 CORE 时，只比较终端到所有 CORE 的距离。
- 所选节点为 Firewall 时，只比较终端到所有 Firewall 的距离。
- CORE 和 Firewall 不进行跨角色距离竞争。

## 构造过程

1. 将有效物理链路转换为无向简单图，并统计每个节点的度数。
2. 严格筛选 `DEVICEROLE=CORE` 和 `DEVICEROLE=Firewall` 的上游候选。
3. 按终端定义筛选度数为 1 的 AP/LSW 节点。
4. 对每个上游节点执行 BFS，得到它到全部可达终端的距离。
5. 对每个终端比较其到所有同角色上游节点的距离。
6. 只有存在唯一最近同角色上游时才建立归属；不可达和最短距离并列均排除。
7. 移除没有任何归属终端的上游节点。
8. 使用固定随机种子从剩余上游节点中选择一个，一张原图最多生成一个非空任务。
9. 按节点 ID 字典序输出全部归属终端。

## 新增任务字段

| 字段 | 含义 |
|---|---|
| `task_upstream_node_id` | 问题中指定的 CORE 或 Firewall 节点 ID |
| `task_question` | 查询该节点全部下游终端的问题 |
| `task_answer.downstream_terminal_node_ids` | 唯一归属于该上游的 AP/LSW 终端 ID |
| `task_metadata.upstream_role` | 所选上游角色 |
| `task_metadata.assignment_policy` | `unique_nearest_same_role_upstream` |

## 跳过条件

- 没有 CORE 或 Firewall 节点。
- 没有满足类型和角色限制的度数为 1 终端。
- 所有终端均不可达、距离并列或无法唯一归属。
- 没有任何上游节点拥有非空下游终端集合。

## 参数

| 参数 | 默认值 | 作用 |
|---|---:|---|
| `--dataset-root` | `datasets` | 原始数据集根目录 |
| `--output-root` | `downstream_reachable_terminal_dataset` | 输出目录 |
| `--splits` | `train val` | 数据划分 |
| `--seed` | `20260826` | 上游节点选择随机种子 |
| `--progress-interval` | `100` | 进度打印间隔 |
| `--indent` | `2` | JSON 缩进空格数 |

