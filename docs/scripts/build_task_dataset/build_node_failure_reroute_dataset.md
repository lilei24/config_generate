# build_node_failure_reroute_dataset.py

> 代码位置：[`scripts/build_task_dataset/build_node_failure_reroute_dataset.py`](../../../scripts/build_task_dataset/build_node_failure_reroute_dataset.py)

## 功能与业务价值

直接从原始拓扑构造单节点故障绕行任务数据集。

与依赖最近目标单样本的构建器不同，本脚本遍历每张图中的全部 AP。对每个 AP
独立按照以下目标角色优先级选择其最高可达层级：

1. CORE；
2. Gateway+CORE；
3. Gateway_vRR；
4. Gateway；
5. Firewall；
6. AGG；
7. ACC。

在选定层级中查找最近目标及全部最短路径，枚举路径中间节点故障，并只保留故障
后仍可到达原目标的候选。优先输出跳数增加的 detour，其次输出等长路径切换。

**业务价值：** 模拟设备故障后的路径恢复，评估 Agent 的连通性重算与替代路径发现能力。

## 核心逻辑

1. 为每个 AP 确定最高可达目标角色及正常最短路径。
2. 枚举路径中间节点故障，删除节点及关联边后重新计算同一源目标。
3. 优先采样跳数增加的 detour，其次采样等代价切换。

## 参数

| 参数 | 说明 |
|---|---|
| `-h, --help` | 显示当前脚本的完整命令帮助后退出。 |
| `--dataset-root DATASET_ROOT` | 原始数据集根目录，默认: datasets |
| `--output-root OUTPUT_ROOT` | 输出任务数据集根目录，默认: node_failure_reroute_dataset_from_raw |
| `--splits SPLITS [SPLITS ...]` | 需要处理的数据划分，默认: train val |
| `--seed SEED` | 随机种子，默认: 20260715 |
| `--samples-per-graph SAMPLES_PER_GRAPH` | 每张图最多生成的去重样本数，默认: 3 |
| `--min-baseline-path-node-count MIN_BASELINE_PATH_NODE_COUNT` | 基线路径最少节点数，必须不小于 3，默认: 3 |
| `--progress-interval PROGRESS_INTERVAL` | 每处理多少个文件打印一次进度，默认: 100 |
| `--indent INDENT` | 输出 JSON 缩进，默认: 2 |

参数表以当前代码的 `--help` 为准。路径参数均相对于运行命令所在目录解析。

### 关键默认值

| 常量 | 当前值 |
|---|---|
| `DEFAULT_DATASET_ROOT` | `'datasets'` |
| `DEFAULT_OUTPUT_ROOT` | `'node_failure_reroute_dataset_from_raw'` |
| `DEFAULT_RANDOM_SEED` | `20260715` |
| `DEFAULT_SPLITS` | `('train', 'val')` |
| `DEFAULT_PROGRESS_INTERVAL` | `100` |
| `DEFAULT_MIN_BASELINE_PATH_NODE_COUNT` | `3` |
| `DEFAULT_SAMPLES_PER_GRAPH` | `3` |
| `TARGET_ROLE_PRIORITY` | `(('core', 'CORE'), ('gateway_plus_core', 'Gateway+CORE'), ('gateway_vrr', 'Gateway_vRR'), ('gateway', 'Gateway'), ('firewall', 'Firewall'), ('aggregation', 'AGG'), ('access', 'ACC'))` |

## 运行方式

```bash
python scripts/build_task_dataset/build_node_failure_reroute_dataset.py --help
```

确认数据路径和输出路径后，可去掉 `--help` 并传入上表参数执行。

## 关键接口

| 接口 | 职责 |
|---|---|
| `NodeInformation (class)` | 核心内部接口 |
| `RerouteCandidate (class)` | 核心内部接口 |
| `iter_json_files (function)` | 核心内部接口 |
| `load_json (function)` | 核心内部接口 |
| `get_node_role (function)` | 核心内部接口 |
| `get_node_information (function)` | 核心内部接口 |
| `build_adjacency (function)` | 核心内部接口 |
| `remove_node_from_adjacency (function)` | 核心内部接口 |
| `shortest_path_tree (function)` | 核心内部接口 |
| `restore_all_shortest_paths (function)` | 核心内部接口 |
| `all_shortest_node_paths (function)` | 核心内部接口 |
| `select_nearest_targets_for_ap (function)` | 为单个 AP 选择其最高可达目标层级和该层级内的最近目标。 |
| `collect_reroute_candidates (function)` | 核心内部接口 |
| `select_candidates (function)` | 核心内部接口 |
| `output_relative_path (function)` | 核心内部接口 |
| `remove_previous_graph_outputs (function)` | 删除同一原图上次生成的编号样本，避免减少样本数后残留旧文件。 |
| 其他内部接口 | 另有 6 个辅助接口，详见源码。 |

## 输入、输出与口径

- 输入字段、候选筛选和异常状态以“核心逻辑”及源码校验条件为准。
- 构建结果通常同时包含 `with_answer` 与 `without_answer`，两者除答案字段外应保持一致。
- `build_summary.json` 和 issues/stats 文件用于解释跳过原因与最终样本数。
- 固定随机种子只有在输入文件集合与排序不变时才保证样本可复现。

[返回 任务数据集构建索引](README.md)
