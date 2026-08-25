# prune_config_generation_qa.py

> 代码位置：[`scripts/prune_config_generation_qa.py`](../../scripts/prune_config_generation_qa.py)

## 功能与业务价值

对已生成的配置生成 QA 样本再次裁剪 input 图上下文。

这个脚本的输入是 build_config_generation_dataset_pruned.py 已经生成的 QA JSON，
不是原始 datasets 图文件。它不会重新选择 target node 或 target key，只使用
metadata.target 里已有的目标信息，然后只修改样本中的 input 字段。

默认目录结构：

输入：
  QA/train/node_config_qa/*.json
  QA/train/device_config_qa/*.json
  QA/val/node_config_qa/*.json
  QA/val/device_config_qa/*.json

输出：
  QA_post_pruned/train/node_config_qa/*.json
  QA_post_pruned/train/device_config_qa/*.json
  QA_post_pruned/val/node_config_qa/*.json
  QA_post_pruned/val/device_config_qa/*.json

**业务价值：** 对已有 QA 二次裁剪且保持目标不变，便于公平比较不同上下文规模。

## 核心逻辑

1. 读取 metadata.target 中既有目标，不重新随机选择。
2. 只对 input.nodes 按目标距离从远到近裁剪。
3. 保持 prompt、output、metadata 和目录结构不变，便于配对实验。

## 参数

| 参数 | 说明 |
|---|---|
| `qa_root` | Existing QA root containing split/task JSON files. Default: QA |
| `-h, --help` | 显示当前脚本的完整命令帮助后退出。 |
| `-o OUTPUT_DIR, --output-dir OUTPUT_DIR` | Output directory for post-pruned QA files. Default: QA_post_pruned |
| `--splits SPLITS [SPLITS ...]` | Split names to process. |
| `--task-dirs TASK_DIRS [TASK_DIRS ...]` | Task directories to process. |
| `--max-input-tokens MAX_INPUT_TOKENS` | Rough token limit for sample.input. Use 0 to disable pruning. Default: 100000 |
| `--progress-interval PROGRESS_INTERVAL` | Print progress every N QA files. Use 0 to disable. Default: 100 |

参数表以当前代码的 `--help` 为准。路径参数均相对于运行命令所在目录解析。

### 关键默认值

| 常量 | 当前值 |
|---|---|
| `DEFAULT_QA_ROOT` | `'QA'` |
| `DEFAULT_OUTPUT_DIR` | `'QA_post_pruned'` |
| `DEFAULT_MAX_INPUT_TOKENS` | `100000` |
| `DEFAULT_PROGRESS_INTERVAL` | `100` |
| `DEFAULT_SPLITS` | `['train', 'val']` |
| `DEFAULT_TASK_DIRS` | `['node_config_qa', 'device_config_qa']` |

## 运行方式

```bash
python scripts/prune_config_generation_qa.py --help
```

确认数据路径和输出路径后，可去掉 `--help` 并传入上表参数执行。

## 关键接口

| 接口 | 职责 |
|---|---|
| `PruneResult (class)` | 单个 QA 样本 input 的二次裁剪结果。 |
| `ProcessIssue (class)` | 处理 QA 样本时需要记录的问题。 |
| `stable_json_text (function)` | 把 JSON 值转成稳定文本，用于粗略 token 估算。 |
| `rough_bpe_token_count (function)` | 粗略估算 BPE token 数，与现有数据分析脚本保持接近口径。 |
| `graph_token_estimate (function)` | 估算 input 图上下文 token 数。 |
| `load_json (function)` | 读取单个 QA JSON。 |
| `write_json (function)` | 写格式化 JSON，并保留字段顺序，方便人工查看。 |
| `write_jsonl (function)` | 写 JSONL 问题文件。 |
| `node_id_at (function)` | 读取节点 id。 |
| `graph_nodes (function)` | 安全读取 nodes 列表。 |
| `valid_node_ids (function)` | 返回 input 图中的有效 node id。 |
| `build_adjacency (function)` | 根据 input.links 构造无向邻接表。 |
| `shortest_distances (function)` | 计算中心节点到其他节点的最短路，不连通节点距离为无穷。 |
| `farthest_removable_node_id (function)` | 选择距离中心最远的可删除节点，永远不删除中心节点。 |
| `remove_node_from_graph (function)` | 从 input.nodes 删除一个节点，并同步删除关联 links。 |
| `resolve_center_node_id (function)` | 从已有 metadata 中确定二次裁剪中心节点。 |
| 其他内部接口 | 另有 6 个辅助接口，详见源码。 |

## 输入、输出与口径

- 输入字段、候选筛选和异常状态以“核心逻辑”及源码校验条件为准。
- 统计脚本需区分扫描文件数、有效文件数和参与数值计算的样本数，避免分母混淆。
- 输出目录不会自动上传，也不应覆盖原始数据集。

[返回 通用数据分析与配置生成索引](README.md)
