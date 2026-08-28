# 上行节点路径查询

**对应脚本：** [`build_uplink_node_path_dataset.py`](../../build_task_dataset_scripts/build_uplink_node_path_dataset.py)

[返回任务构造索引](README.md)

## 任务目标

从一个 AP 节点出发，查询最高优先级可达角色中距离最近的设备，并输出到全部等距最近设备的全部最短物理路径。

## 业务价值

任务模拟接入设备查找核心、出口、安全边界或汇聚接入节点的上行路径，能够检验 Agent 对网络角色、角色优先级、最近目标和多路径的联合理解。

## 上行角色优先级

```text
CORE
Gateway+CORE
Gateway_vRR
Gateway
Firewall
AGG
ACC
```

每一级只有一种精确角色。只要任意 AP 能够到达当前层级，就不会回退到更低层级。

## 构造过程

1. 严格筛选 `DEVICEROLE=AP` 的源节点候选。
2. 构建物理邻接表，并对 AP 执行 BFS，计算到所有可达节点的距离和最短路径前驱。
3. 从优先级最高的角色开始检查当前图是否存在 AP 到该角色节点的可达组合。
4. 在首个可用角色层级内选择一个可达 AP。
5. 比较该 AP 到该角色所有节点的距离，只保留全局最小距离对应的目标设备。
6. 多个目标距离相同则全部保留，并恢复到这些目标的全部等长最短路径。
7. 同步写出有答案和隐藏答案版本。

## 新增任务字段

| 字段 | 含义 |
|---|---|
| `task_source_node_id` | 所选 AP 节点 ID |
| `task_question` | 指定源 AP 和目标角色的查询问题 |
| `task_answer.path_length` | 到最近目标的最短跳数 |
| `task_answer.paths` | 到全部等距最近目标的全部最短路径 |
| `task_metadata.target_role` | 本图最终选择的精确目标角色 |
| `task_metadata.target_priority_rank` | 目标角色优先级序号 |

## 跳过条件

- 图中不存在 AP 角色节点。
- 没有有效链路。
- 所有 AP 均无法到达支持的上行角色。
- 无法恢复有效最短路径。

## 参数

| 参数 | 默认值 | 作用 |
|---|---:|---|
| `--dataset-root` | `datasets` | 原始数据集根目录 |
| `--output-root` | `uplink_node_path_dataset` | 输出目录 |
| `--splits` | `train val` | 数据划分 |
| `--seed` | `20260715` | AP 选择随机种子 |
| `--progress-interval` | `100` | 进度打印间隔 |
| `--indent` | `2` | JSON 缩进空格数 |

