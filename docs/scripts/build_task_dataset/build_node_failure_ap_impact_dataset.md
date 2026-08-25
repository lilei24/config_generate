# build_node_failure_ap_impact_dataset.py

> 代码位置：[`scripts/build_task_dataset/build_node_failure_ap_impact_dataset.py`](../../../scripts/build_task_dataset/build_node_failure_ap_impact_dataset.py)

## 功能与业务价值

构造“指定非 AP 节点故障后哪些 AP 失联”的正向影响面任务数据集。

**业务价值：** 模拟非 AP 设备下线的接入影响面，评估失联 AP 识别能力。

## 核心逻辑

1. 为每个 AP 按角色优先级确定正常上游目标集合。
2. 枚举非 AP 故障节点并删除其关联边，判断各 AP 是否仍能到达正常目标。
3. 按影响 AP 数量划分 small、medium、large，每图默认各选择一个。

## 参数

| 参数 | 说明 |
|---|---|
| `-h, --help` | 显示当前脚本的完整命令帮助后退出。 |
| `--dataset-root DATASET_ROOT` | 原始数据集根目录，默认: datasets |
| `--output-root OUTPUT_ROOT` | 任务数据集输出根目录，默认: node_failure_ap_impact_dataset |
| `--splits SPLITS [SPLITS ...]` | 处理的数据划分，默认: train val |
| `--seed SEED` | 固定随机种子，默认: 20260723 |
| `--samples-per-graph SAMPLES_PER_GRAPH` | 每张图最多生成的故障任务数；按 small、medium、large 各选一个，最大有效值为 3，默认: 3 |
| `--progress-interval PROGRESS_INTERVAL` | 每处理 N 个文件打印进度，0 表示关闭，默认: 50 |
| `--indent INDENT` | 输出 JSON 的缩进空格数。 |

参数表以当前代码的 `--help` 为准。路径参数均相对于运行命令所在目录解析。

### 关键默认值

| 常量 | 当前值 |
|---|---|
| `DEFAULT_DATASET_ROOT` | `'datasets'` |
| `DEFAULT_OUTPUT_ROOT` | `'node_failure_ap_impact_dataset'` |
| `DEFAULT_RANDOM_SEED` | `20260723` |
| `DEFAULT_SPLITS` | `('train', 'val')` |
| `DEFAULT_PROGRESS_INTERVAL` | `50` |
| `DEFAULT_SAMPLES_PER_GRAPH` | `3` |
| `STATS_FILE` | `'node_failure_ap_impact_stats.csv'` |
| `SUMMARY_FILE` | `'build_summary.json'` |
| `ISSUE_FILE` | `'build_issues.jsonl'` |
| `TARGET_ROLE_PRIORITY` | `(('core', 'CORE'), ('gateway_plus_core', 'Gateway+CORE'), ('gateway_vrr', 'Gateway_vRR'), ('gateway', 'Gateway'), ('firewall', 'Firewall'), ('aggregation', 'AGG'), ('access', 'ACC'))` |

## 运行方式

```bash
python scripts/build_task_dataset/build_node_failure_ap_impact_dataset.py --help
```

确认数据路径和输出路径后，可去掉 `--help` 并传入上表参数执行。

## 关键接口

| 接口 | 职责 |
|---|---|
| `NodeInformation (class)` | 核心内部接口 |
| `BaselineTarget (class)` | 核心内部接口 |
| `ImpactCandidate (class)` | 核心内部接口 |
| `iter_json_files (function)` | 核心内部接口 |
| `load_json (function)` | 核心内部接口 |
| `get_device (function)` | 核心内部接口 |
| `scalar_text (function)` | 核心内部接口 |
| `get_node_information (function)` | 核心内部接口 |
| `build_adjacency (function)` | 核心内部接口 |
| `reachable_nodes (function)` | 核心内部接口 |
| `connected_components (function)` | 核心内部接口 |
| `select_baseline_target (function)` | 核心内部接口 |
| `build_ap_baselines (function)` | 核心内部接口 |
| `disconnected_aps_after_failure (function)` | 核心内部接口 |
| `classify_impact (function)` | 核心内部接口 |
| `collect_candidates (function)` | 核心内部接口 |
| 其他内部接口 | 另有 9 个辅助接口，详见源码。 |

## 输入、输出与口径

- 输入字段、候选筛选和异常状态以“核心逻辑”及源码校验条件为准。
- 构建结果通常同时包含 `with_answer` 与 `without_answer`，两者除答案字段外应保持一致。
- `build_summary.json` 和 issues/stats 文件用于解释跳过原因与最终样本数。
- 固定随机种子只有在输入文件集合与排序不变时才保证样本可复现。

[返回 任务数据集构建索引](README.md)
