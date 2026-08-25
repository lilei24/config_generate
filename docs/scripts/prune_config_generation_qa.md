# prune_config_generation_qa.py

> 代码位置：[`scripts/prune_config_generation_qa.py`](../../scripts/prune_config_generation_qa.py)

## 功能与业务价值

该脚本对已经生成的配置 QA 做构造后二次裁剪。它读取样本中已有的 target metadata 来确定裁剪中心，只缩减 `input.nodes` 和相关 `input.links`，不重新选择目标配置，也不改变 `prompt` 或 `output`。

该方式适合在一份固定 QA 上生成不同上下文长度版本，使不同裁剪阈值的实验共享完全相同的预测目标和标准答案，从而保证模型对比公平。

## 核心逻辑

1. 按 split 和任务目录读取已有 QA JSON。
2. 校验样本对象及 `input` 图结构。
3. 从既有 metadata 解析裁剪中心节点。
4. 对超限 Input 逐个删除离中心最远的节点和关联链路。
5. 保留样本其他字段及顺序，仅替换 `input`。
6. 将二次裁剪信息写入 `metadata.post_context_pruning`。
7. 按原相对路径输出新 QA，并生成独立汇总和问题日志。

## 代码实现说明

### 裁剪中心解析

- node 配置样本优先使用 `metadata.target.node_id`，即需要生成配置的目标节点。这保证裁剪始终围绕任务目标保留最近上下文。
- deviceGroup 配置没有天然目标节点时，使用首次构造记录的 `metadata.context_pruning.center_node_id`。
- 如果 metadata 中没有可用中心，或中心已经不在当前 `input.nodes` 中，样本不会随机选择新中心；脚本保留原 Input，并在 issues 中记录跳过原因。

### 二次裁剪规则

- Token 估算、无向邻接表、BFS 距离和最远节点排序规则与 pruned 构造脚本一致。
- 不可达节点优先删除，随后删除距离中心最远节点；同距离时使用 nodes 中靠后的位置打破平局。中心节点不会被删除。
- 节点删除与 links 清理同步执行，`deviceGroups`、其他顶层字段以及剩余节点的完整内容不变。
- 输入已经低于阈值时不会删除节点，但仍会输出样本并记录 `pruned=false`，便于输出集和输入集保持文件对应关系。

### 样本不变量

- `prompt` 原样保留，预测要求不会变化。
- `output` 原样保留，因此答案、顶层 Key 和 Value 不会因二次裁剪改变。
- `metadata.target` 原样保留，不会重新随机选择 target node、deviceGroup 或配置 Key。
- 原 metadata 不是字典时会包入 `original_metadata`，然后增加 `post_context_pruning`，避免直接丢弃历史信息。

### 结果记录

`metadata.post_context_pruning` 包含中心来源、中心 node id、阈值、裁剪前后 Token 和节点数、删除数、裁剪状态、是否仍超限及跳过原因。汇总按 split/task 分层，便于分别观察 node 与 deviceGroup 样本的裁剪效果。

## 参数

| 参数 | 默认值 | 说明 |
|---|---|---|
| `qa_root` | `QA` | 已生成 QA 根目录。 |
| `-o, --output-dir` | `QA_post_pruned` | 二次裁剪数据集输出根目录。 |
| `--splits` | `train val` | 需要处理的数据划分。 |
| `--task-dirs` | `node_config_qa device_config_qa` | split 下需要处理的任务目录。 |
| `--max-input-tokens` | `100000` | `sample.input` 的粗略 Token 上限；`0` 禁用裁剪。 |
| `--progress-interval` | `100` | 每处理多少个 QA 文件打印一次进度。 |

## 输入与输出

**输入：** `QA/<split>/<task>/**/*.json`，样本需包含 `input`，并应具有可定位中心的 metadata。

**输出：**

- `QA_post_pruned/<split>/<task>/**/*.json`
- 每个样本中的 `metadata.post_context_pruning`
- `QA_post_pruned/post_prune_summary.json`
- `QA_post_pruned/post_prune_issues.jsonl`

[返回配置生成数据集构造脚本索引](README.md)
