# build_downstream_reachable_terminal_dataset.py

> 代码位置：[`scripts/build_task_dataset/build_downstream_reachable_terminal_dataset.py`](../../../scripts/build_task_dataset/build_downstream_reachable_terminal_dataset.py)

## 功能与业务价值

构造“指定 CORE 或 Firewall 的下游可达终端”任务数据集。任务问题给出一个核心上游节点 ID，答案只输出唯一归属于它的全部下游叶子节点 ID。

**业务价值：** 评估 Agent 对网络层级、终端叶子、同角色核心归属和无向最短路径距离的综合理解能力，可作为故障影响面、下游设备发现和业务域划分任务的基础数据。

## 核心逻辑

1. 递归读取 `datasets/train` 和 `datasets/val` 中的原始拓扑 JSON，物理链路统一转换为无向简单图。
2. 严格选择 `DEVICEROLE == CORE` 或 `DEVICEROLE == Firewall` 的节点作为核心上游候选。
3. 将度数为 1，且自身角色不是 CORE/Firewall 的节点作为终端叶子候选。
4. CORE 和 Firewall 分别建立独立归属体系：
   - CORE 叶子归属只比较到所有 CORE 的最短距离；
   - Firewall 叶子归属只比较到所有 Firewall 的最短距离；
   - 两种角色不进行跨角色距离竞争。
5. 叶子节点只归属于唯一最近的同角色核心上游节点；不可达、存在更近同角色节点或最近距离并列时，不归入当前答案。
6. 从至少拥有一个唯一归属叶子的上游候选中，使用固定随机种子选择一个节点，确保一张原图最多生成一个非空任务。
7. 问题中写入所选上游节点 ID 和角色，`task_answer` 只包含按字典序排列的 `downstream_leaf_node_ids`。
8. 同步生成 `with_answer` 和 `without_answer`，两者除 `task_answer` 外保持一致。

## 参数

| 参数 | 说明 |
|---|---|
| `--dataset-root` | 原始数据集根目录。默认：`datasets`。 |
| `--output-root` | 任务数据集输出目录。默认：`downstream_reachable_terminal_dataset`。 |
| `--splits` | 需要处理的数据划分。默认：`train val`。 |
| `--seed` | 选择核心上游节点使用的固定随机种子。默认：`20260826`。 |
| `--progress-interval` | 每处理多少个文件打印进度，`0` 表示关闭。默认：`100`。 |
| `--indent` | 输出 JSON 的缩进空格数。默认：`2`。 |

## 任务字段

| 字段 | 含义 |
|---|---|
| `task_upstream_node_id` | 问题中指定的 CORE 或 Firewall 节点 ID。 |
| `task_question` | 下游可达终端查询问题、归属规则和输出格式。 |
| `task_answer.downstream_leaf_node_ids` | 唯一归属于所选上游节点的全部终端叶子节点 ID。 |
| `task_metadata.upstream_role` | 所选上游节点的角色。 |
| `task_metadata.equal_distance_policy` | 等距归属策略，固定为 `exclude`。 |

## 输出与统计

输出目录包含：

- `with_answer/<split>/*.json`：包含标准答案。
- `without_answer/<split>/*.json`：隐藏标准答案，供推理使用。
- `downstream_reachable_terminal_stats.csv`：记录上游节点、角色、同角色节点数、叶子候选数、答案数量和最大下游距离。
- `build_summary.json`：记录生成数量、角色分布、跳过原因及等距/不可达叶子统计。
- `build_issues.jsonl`：逐文件记录无法构造任务的原因。

[返回 任务数据集构建索引](README.md)
