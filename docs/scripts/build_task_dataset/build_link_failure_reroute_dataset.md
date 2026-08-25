# build_link_failure_reroute_dataset.py

> 代码位置：[`scripts/build_task_dataset/build_link_failure_reroute_dataset.py`](../../../scripts/build_task_dataset/build_link_failure_reroute_dataset.py)

## 功能与业务价值

从原始拓扑构造单链路故障绕行任务数据集。

对每个 AP 按业务角色优先级选择最高可达层级中的最近目标，枚举正常最短
路径上的链路故障，并将候选划分为等价切换、绕行和失联三类。默认每张图
按照 1:1:1 的配额分别抽取等价切换、绕行和失联样本；只有至少存在一种
可切换或可绕行样本时，才允许附带失联样本。输出内容对应的 with_answer
和 without_answer 数据集。

**业务价值：** 模拟物理链路故障，覆盖等价切换、绕行和断连三类结果。

## 核心逻辑

1. 选择正常最短路径上的链路作为故障对象。
2. 删除该无向边后重算源目标连通性和全部最短路径。
3. 分别构造等价切换、增加跳数绕行和断连样本，并控制类别采样。

## 参数

| 参数 | 说明 |
|---|---|
| `-h, --help` | 显示当前脚本的完整命令帮助后退出。 |
| `--dataset-root DATASET_ROOT` | 原始数据集根目录，默认: datasets |
| `--output-root OUTPUT_ROOT` | 任务数据集输出目录，默认: link_failure_reroute_dataset |
| `--splits SPLITS [SPLITS ...]` | 处理的数据划分，默认: train val |
| `--seed SEED` | 固定随机种子，默认: 20260805 |
| `--equal-cost-samples-per-graph EQUAL_COST_SAMPLES_PER_GRAPH` | 每张图最多抽取的等价切换样本数，默认: 1 |
| `--detour-samples-per-graph DETOUR_SAMPLES_PER_GRAPH` | 每张图最多抽取的绕行样本数，默认: 1 |
| `--disconnected-samples-per-graph DISCONNECTED_SAMPLES_PER_GRAPH` | 每张图最多抽取的失联样本数，默认: 1 |
| `--progress-interval PROGRESS_INTERVAL` | 每处理 N 个文件打印进度，0 表示关闭，默认: 100 |
| `--indent INDENT` | 输出 JSON 的缩进空格数。 |

参数表以当前代码的 `--help` 为准。路径参数均相对于运行命令所在目录解析。

### 关键默认值

| 常量 | 当前值 |
|---|---|
| `DEFAULT_DATASET_ROOT` | `'datasets'` |
| `DEFAULT_OUTPUT_ROOT` | `'link_failure_reroute_dataset'` |
| `DEFAULT_RANDOM_SEED` | `20260805` |
| `DEFAULT_SPLITS` | `('train', 'val')` |
| `DEFAULT_PROGRESS_INTERVAL` | `100` |
| `DEFAULT_EQUAL_COST_SAMPLES_PER_GRAPH` | `1` |
| `DEFAULT_DETOUR_SAMPLES_PER_GRAPH` | `1` |
| `DEFAULT_DISCONNECTED_SAMPLES_PER_GRAPH` | `1` |
| `WITH_ANSWER_DIR` | `'with_answer'` |
| `WITHOUT_ANSWER_DIR` | `'without_answer'` |
| `STATS_FILE` | `'link_failure_reroute_stats.csv'` |
| `SUMMARY_FILE` | `'build_summary.json'` |
| `ISSUES_FILE` | `'build_issues.jsonl'` |
| `TARGET_ROLE_PRIORITY` | `(('core', 'CORE'), ('gateway_plus_core', 'Gateway+CORE'), ('gateway_vrr', 'Gateway_vRR'), ('gateway', 'Gateway'), ('firewall', 'Firewall'), ('aggregation', 'AGG'), ('access', 'ACC'))` |

## 运行方式

```bash
python scripts/build_task_dataset/build_link_failure_reroute_dataset.py --help
```

确认数据路径和输出路径后，可去掉 `--help` 并传入上表参数执行。

## 关键接口

| 接口 | 职责 |
|---|---|
| `LinkRecord (class)` | 核心内部接口 |
| `LinkFailureCandidate (class)` | 核心内部接口 |
| `iter_json_files (function)` | 核心内部接口 |
| `load_graph (function)` | 核心内部接口 |
| `get_node_role (function)` | 核心内部接口 |
| `collect_nodes (function)` | 核心内部接口 |
| `collect_links (function)` | 核心内部接口 |
| `build_adjacency (function)` | 按链路索引排除单条边，重复端点的其他物理链路仍然有效。 |
| `shortest_path_tree (function)` | 核心内部接口 |
| `restore_all_shortest_paths (function)` | 核心内部接口 |
| `all_shortest_paths (function)` | 核心内部接口 |
| `select_nearest_targets (function)` | 核心内部接口 |
| `path_edge_pairs (function)` | 核心内部接口 |
| `link_pair (function)` | 核心内部接口 |
| `collect_candidates (function)` | 核心内部接口 |
| `select_candidates (function)` | 核心内部接口 |
| 其他内部接口 | 另有 8 个辅助接口，详见源码。 |

## 输入、输出与口径

- 输入字段、候选筛选和异常状态以“核心逻辑”及源码校验条件为准。
- 构建结果通常同时包含 `with_answer` 与 `without_answer`，两者除答案字段外应保持一致。
- `build_summary.json` 和 issues/stats 文件用于解释跳过原因与最终样本数。
- 固定随机种子只有在输入文件集合与排序不变时才保证样本可复现。

[返回 任务数据集构建索引](README.md)
