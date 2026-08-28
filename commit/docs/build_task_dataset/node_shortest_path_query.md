# 节点最短路径查询

**对应脚本：** [`build_shortest_path_dataset.py`](../../build_task_dataset_scripts/build_shortest_path_dataset.py)

[返回任务构造索引](README.md)

## 任务目标

给定两个节点 ID，查询它们之间的全部最短物理路径，同时输出路径上各节点对应的设备角色和设备名称。

## 业务价值

该任务是拓扑 Agent 的基础图计算任务，用于验证 Provider 数据读取、路径工具调用、节点语义对齐和自动评分链路。它也是故障绕行、约束路径和影响面分析的基础能力。

## 构造前提

- 图中至少存在两个有效节点。
- `links[].source` 和 `links[].target` 能够映射到节点 ID。
- 至少存在一组互相可达且不相同的源、目标节点。

## 构造过程

1. 递归读取指定 split 下的 JSON，提取节点 ID、设备名称和 `DEVICEROLE`。
2. 根据有效链路构建邻接表；`directed=false` 时将每条链路作为无向边。
3. 使用固定随机种子生成源、目标节点候选，每张图最多尝试 `max-attempts-per-graph` 组。
4. 对候选源节点执行 BFS，只有目标节点可达时才接受该节点对。
5. 记录所有最短路径前驱，而不是只记录单一父节点。
6. 根据前驱关系恢复源到目标的全部等长最短路径，并稳定排序。
7. 按每条节点 ID 路径的位置生成对应的角色序列和设备名称序列。
8. 从同一个完整样本派生 `with_answer` 和 `without_answer`，避免再次随机选择造成两份数据不一致。

## 新增任务字段

| 字段 | 含义 |
|---|---|
| `task_source_node_id` | 源节点 ID |
| `task_target_node_id` | 目标节点 ID |
| `task_question` | 要求返回全部最短路径、角色序列和设备名称序列 |
| `task_answer.path_length` | 最短链路跳数 |
| `task_answer.paths` | 全部最短节点 ID 路径 |
| `task_answer.path_role_sequences` | 与 `paths` 一一对应的角色序列 |
| `task_answer.path_device_names` | 与 `paths` 一一对应的设备名称序列 |

## 跳过条件

- JSON 无法读取或顶层不是对象。
- 节点数小于 2。
- 没有有效链路。
- 在最大尝试次数内未找到可达节点对。

## 参数

| 参数 | 默认值 | 作用 |
|---|---:|---|
| `--dataset-root` | `datasets` | 原始数据集根目录 |
| `--output-root` | `shortest_path_dataset` | 输出目录 |
| `--splits` | `train val` | 处理的数据划分 |
| `--seed` | `20260715` | 节点对选择随机种子 |
| `--max-attempts-per-graph` | `100` | 单图最多尝试的节点对数量 |
| `--progress-interval` | `100` | 进度打印间隔，`0` 表示关闭 |
| `--indent` | `2` | JSON 缩进空格数 |

