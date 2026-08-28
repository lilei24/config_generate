# 故障影响AP节点

**对应脚本：** [`build_node_failure_ap_impact_dataset.py`](../../build_task_dataset_scripts/build_node_failure_ap_impact_dataset.py)

[返回任务构造索引](README.md)

## 任务目标

指定一个非 AP 故障节点和一个正常上游目标节点，查询哪些 AP 到该上游目标的路径受到影响。

## 业务价值

任务模拟设备下线后的接入影响面，评估 Agent 是否能够将节点故障传播到具体 AP，并识别路径变长和完全不可达两种影响结果。

## 上游目标选择

对每个 AP，先按照以下角色优先级寻找首个可达角色：

```text
CORE
Gateway+CORE
Gateway_vRR
Gateway
Firewall
AGG
ACC
```

在首个可达角色中，只保留距离该 AP 最近的节点；多个节点等距最近时全部保留。随后汇总各 AP 的最近候选，选择 AP 到候选目标的最短距离最小的节点作为本图指定上游目标，距离相同时按节点 ID 稳定选择，不随机选择目标。

## 构造过程

1. 筛选全部 `DEVICEROLE=AP` 节点并构建物理邻接表。
2. 为每个 AP 按角色优先级和最短距离建立正常上游候选。
3. 确定本图唯一指定上游目标节点。
4. 只保留正常情况下能够到达该指定目标的 AP，并记录各自最短距离。
5. 枚举所有非 AP 且不是指定目标的节点作为故障候选。
6. 模拟删除故障节点及其关联链路，重新计算每个 AP 到指定目标的距离。
7. 若故障后不可达，或最短距离大于故障前距离，则该 AP 记为受影响。
8. 不影响任何 AP 的故障候选被丢弃。
9. 按受影响 AP 数量划分 `small`（1 至 5）、`medium`（6 至 20）和 `large`（大于 20），默认每类随机选择一个候选。

## 新增任务字段

| 字段 | 含义 |
|---|---|
| `task_failed_node_id` | 模拟故障的非 AP 节点 ID |
| `task_target_node_id` | AP 正常情况下到达的指定上游目标 ID |
| `task_target_role_priority` | 上游角色优先级列表 |
| `task_question` | 查询故障影响哪些 AP 的问题 |
| `task_answer.impacted_ap_ids` | 路径变长或无法到达目标的全部 AP ID |
| `task_metadata.impact_rule` | `shortest_path_increased_or_target_unreachable` |

## 跳过条件

- 图中没有 AP 角色节点。
- 没有有效链路。
- AP 无法到达任何支持的上游角色。
- 无法确定指定上游目标。
- 没有任何非 AP 故障候选能够影响 AP。

## 参数

| 参数 | 默认值 | 作用 |
|---|---:|---|
| `--dataset-root` | `datasets` | 原始数据集根目录 |
| `--output-root` | `node_failure_ap_impact_dataset` | 输出目录 |
| `--splits` | `train val` | 数据划分 |
| `--seed` | `20260723` | 各影响等级候选抽样随机种子 |
| `--samples-per-graph` | `3` | 每图最多生成的影响等级样本数，范围 1 至 3 |
| `--progress-interval` | `50` | 进度打印间隔 |
| `--indent` | `2` | JSON 缩进空格数 |

