# 指定CORE约束的AP间最短路径查询

**对应脚本：** [`build_ap_pair_via_core_path_dataset.py`](../../build_task_dataset_scripts/build_ap_pair_via_core_path_dataset.py)

[返回任务构造索引](README.md)

## 任务目标

给定两个 AP 节点和一个指定 CORE 节点，查询两个 AP 之间必须经过该 CORE 的全部最短物理路径。

## 业务价值

任务验证 Agent 能否在普通最短路径基础上施加必经点约束，并区分自然经过核心与约束导致绕行两类业务场景，适用于核心归属、跨接入域通信和策略路径分析。

## AP 与 CORE 归属

每个 AP 先计算到全部 `DEVICEROLE=CORE` 节点的最短距离。只有一个 CORE 严格最近时，该 AP 才唯一归属于这个 CORE；多个 CORE 等距最近的 AP 被排除，避免答案中的归属关系含糊。

## 构造过程

1. 构建无向物理拓扑，严格筛选 AP 和 CORE 节点。
2. 对每个 CORE 执行最短距离计算，得到各 AP 到所有 CORE 的距离。
3. 仅保留具有唯一最近 CORE 的 AP，并按 CORE 对 AP 进行分组。
4. 在同一 CORE 分组内枚举两个不同 AP 与该 CORE 的组合。
5. 分别恢复 `AP1 → CORE` 和 `CORE → AP2` 的全部最短路径。
6. 组合两段路径，过滤包含重复节点的无效组合，并按完整节点序列去重。
7. 所有组合中跳数最小的路径构成“必须经过指定 CORE”的标准答案。
8. 将约束路径长度与 AP 间普通最短路径比较：约束路径更长为 `detour`，长度相同为 `natural`。
9. 默认每图最多选择两个 `detour` 和一个 `natural` 样本；候选不足时只输出实际存在的类型。

## 新增任务字段

| 字段 | 含义 |
|---|---|
| `task_source_ap_node_id` | 源 AP 节点 ID |
| `task_target_ap_node_id` | 目标 AP 节点 ID |
| `task_required_core_node_id` | 路径必须经过的 CORE 节点 ID |
| `task_question` | 指定 AP 对和必经 CORE 的约束路径问题 |
| `task_answer.path_length` | 经过指定 CORE 的最短跳数 |
| `task_answer.paths` | 经过指定 CORE 的全部最短路径 |

## 跳过条件

- 图中没有 CORE 或 AP 数量不足。
- 没有两个 AP 唯一归属于同一最近 CORE。
- AP 到 CORE 的路径不可达。
- 组合路径出现重复节点，无法形成简单路径。
- 标准答案路径数超过 `max-answer-paths`。

## 参数

| 参数 | 默认值 | 作用 |
|---|---:|---|
| `--dataset-root` | `datasets` | 原始数据集根目录 |
| `--output-root` | `ap_pair_via_core_path_dataset` | 输出目录 |
| `--splits` | `train val` | 数据划分 |
| `--seed` | `20260806` | 候选抽样随机种子 |
| `--detour-samples-per-graph` | `2` | 单图强制绕行样本上限 |
| `--natural-samples-per-graph` | `1` | 单图自然经过样本上限 |
| `--max-candidate-attempts-per-graph` | `500` | 单图最多检查的 AP 对与 CORE 组合数 |
| `--max-answer-paths` | `1000` | 标准答案路径数上限 |
| `--progress-interval` | `100` | 进度打印间隔 |

