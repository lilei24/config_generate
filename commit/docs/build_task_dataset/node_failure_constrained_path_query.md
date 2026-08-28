# 节点故障约束路径查询

**对应脚本：** [`build_node_failure_reroute_dataset.py`](../../build_task_dataset_scripts/build_node_failure_reroute_dataset.py)

[返回任务构造索引](README.md)

## 任务目标

指定一个源节点、目标节点和故障中间节点，要求从拓扑中排除故障节点及其关联链路后，查询源到目标的全部最短物理路径。

## 业务价值

任务模拟设备下线后的路径恢复，评估 Agent 能否正确应用节点故障约束、重算连通性并发现等价切换或更长绕行路径。

## 目标角色优先级

每个 AP 独立按以下顺序寻找最高可达上行角色：

```text
CORE
Gateway+CORE
Gateway_vRR
Gateway
Firewall
AGG
ACC
```

找到首个可达角色后，不再使用更低优先级角色；在该角色中选择最近目标。

## 构造过程

1. 构建原始物理邻接表，筛选全部 `DEVICEROLE=AP` 的源节点。
2. 对每个 AP 独立寻找最高优先级可达角色，并在该角色中计算最近目标和全部正常最短路径。
3. 只保留节点数不少于 `min-baseline-path-node-count` 的基线路径，保证路径内部存在可选故障节点。
4. 枚举基线路径中除源、目标外的全部中间节点作为故障候选。
5. 从邻接表中删除故障节点及其所有关联边，重新计算同一源、目标之间的全部最短路径。
6. 故障后不可达的组合不进入该数据集；仍可达的组合按源、目标和故障节点去重。
7. 若故障后最短跳数增加，候选类型为 `detour`；若跳数不变但使用替代路径，类型为 `equal_cost_failover`。
8. 每张图优先选择 `detour`，再补充 `equal_cost_failover`，最多输出 `samples-per-graph` 个不同组合。

## 新增任务字段

| 字段 | 含义 |
|---|---|
| `task_source_node_id` | 源 AP 节点 ID |
| `task_target_node_id` | 原正常上行目标节点 ID |
| `task_failed_node_id` | 模拟故障的中间节点 ID |
| `task_question` | 要求排除故障节点后查询全部最短路径 |
| `task_answer.path_length` | 故障约束下的最短跳数 |
| `task_answer.paths` | 不经过故障节点的全部最短路径 |
| `task_metadata.target_role` | 目标节点角色 |

## 跳过条件

- 图中不存在 AP 或有效链路。
- AP 无法到达任何支持的上行角色。
- 正常最短路径节点数不足，无法选择中间故障节点。
- 删除中间节点后所有候选均不可达。
- 候选重复或无法恢复有效最短路径。

## 参数

| 参数 | 默认值 | 作用 |
|---|---:|---|
| `--dataset-root` | `datasets` | 原始数据集根目录 |
| `--output-root` | `node_failure_reroute_dataset_from_raw` | 输出目录，可显式指定为 `node_failure_reroute_dataset` |
| `--splits` | `train val` | 数据划分 |
| `--seed` | `20260715` | 候选抽样随机种子 |
| `--samples-per-graph` | `3` | 每图最多生成的去重样本数 |
| `--min-baseline-path-node-count` | `3` | 基线路径最少节点数 |
| `--progress-interval` | `100` | 进度打印间隔 |
| `--indent` | `2` | JSON 缩进空格数 |

