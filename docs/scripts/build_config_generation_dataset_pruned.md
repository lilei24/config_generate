# build_config_generation_dataset_pruned.py

> 代码位置：[`scripts/build_config_generation_dataset_pruned.py`](../../scripts/build_config_generation_dataset_pruned.py)

## 功能与业务价值

从图 JSON 数据集构造配置生成任务的 QA 样本，并裁剪过长上下文。

当前任务粒度是预测一个 config 对象里的一个顶层 key：

- node 配置来自 ``nodes[].configs[]``，同时兼容历史样例里的 ``nodes[].config[]``。
- deviceGroup 配置来自 ``deviceGroups[].configs[]``。
- 一个训练样本只遮挡一个顶层 key，目标输出也只包含该 key 对应的配置对象。

脚本把“选择哪个 key”与“怎样遮挡 key”拆成独立策略，后续可以在不改主流程
的前提下新增前部 key、后部 key 选择策略，或者新增占位符类遮挡策略。

当图上下文过长时，本脚本会先随机选择一个中心节点，再逐个删除距离中心最远
的节点，直到估算 token 数低于阈值，之后再构造 node/deviceGroup QA。

**业务价值：** 在构建样本时按目标节点距离裁剪大图，控制上下文长度并保留近邻信息。

## 核心逻辑

1. 先选择目标节点和目标配置，再估算完整样本 token。
2. 超过阈值时按到目标节点的最短距离从远到近删除完整节点。
3. 裁剪完成后分别生成 node_config_qa 和 device_config_qa。

## 参数

| 参数 | 说明 |
|---|---|
| `dataset_root` | Dataset root containing train/ and val/ directories. Default: datasets |
| `-h, --help` | 显示当前脚本的完整命令帮助后退出。 |
| `-o OUTPUT_DIR, --output-dir OUTPUT_DIR` | Directory for generated QA data. Default: QA |
| `--splits SPLITS [SPLITS ...]` | Split directory names to build. |
| `--seed SEED` | Seed for deterministic target selection. |
| `--selector {random}` | Target key selector. New selection policies can be registered in TARGET_SELECTORS. |
| `--mask-strategy {remove_random_key}` | How the selected config key is hidden from input. |
| `--progress-interval PROGRESS_INTERVAL` | Print progress every N source JSON files. Use 0 to disable. Default: 100 |
| `--max-input-tokens MAX_INPUT_TOKENS` | Rough token limit for graph context before QA construction. Use 0 to disable pruning. Default: 100000 |

参数表以当前代码的 `--help` 为准。路径参数均相对于运行命令所在目录解析。

### 关键默认值

| 常量 | 当前值 |
|---|---|
| `DEFAULT_DATASET_ROOT` | `'datasets'` |
| `DEFAULT_OUTPUT_DIR` | `'QA'` |
| `DEFAULT_RANDOM_SEED` | `20260522` |
| `DEFAULT_PROGRESS_INTERVAL` | `100` |
| `DEFAULT_MAX_INPUT_TOKENS` | `100000` |

## 运行方式

```bash
python scripts/build_config_generation_dataset_pruned.py --help
```

确认数据路径和输出路径后，可去掉 `--help` 并传入上表参数执行。

## 关键接口

| 接口 | 职责 |
|---|---|
| `ConfigTarget (class)` | 一个可被预测的配置顶层 key 的定位信息。 |
| `BuildIssue (class)` | 构造数据集时需要落盘记录的源文件问题。 |
| `PruneResult (class)` | 单张图的上下文裁剪结果。 |
| `stable_json_text (function)` | 把图上下文转成稳定 JSON 文本，并保留原字段顺序。 |
| `rough_bpe_token_count (function)` | 粗略估算 BPE token 数。 |
| `graph_token_estimate (function)` | 估算当前图上下文 token 数。 |
| `iter_json_files (function)` | 按 split 递归枚举 JSON 文件。 |
| `list_split_json_files (function)` | 列出单个 split 下的 JSON 文件，便于提前知道进度总数。 |
| `load_graph (function)` | 读取一张图。 |
| `node_id_at (function)` | 读取 node id；没有 id 的异常节点不能作为中心点或图距离节点。 |
| `graph_nodes (function)` | 安全读取 nodes 列表。 |
| `choose_random_center_node_id (function)` | 从当前图中随机选择一个中心节点。 |
| `build_adjacency (function)` | 根据 links 构造无向邻接表。 |
| `shortest_distances (function)` | 计算中心节点到每个节点的最短路距离；不可达节点距离为无穷。 |
| `farthest_removable_node_id (function)` | 选择当前图里离中心点最远的可删除节点。 |
| `remove_node_from_graph (function)` | 从图中删除一个节点对象，并删除所有连接到该节点的 link。 |
| 其他内部接口 | 另有 20 个辅助接口，详见源码。 |

## 输入、输出与口径

- 输入字段、候选筛选和异常状态以“核心逻辑”及源码校验条件为准。
- 统计脚本需区分扫描文件数、有效文件数和参与数值计算的样本数，避免分母混淆。
- 输出目录不会自动上传，也不应覆盖原始数据集。

[返回 通用数据分析与配置生成索引](README.md)
