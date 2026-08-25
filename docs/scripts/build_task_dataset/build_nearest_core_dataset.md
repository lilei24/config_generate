# build_nearest_core_dataset.py

> 代码位置：[`scripts/build_task_dataset/build_nearest_core_dataset.py`](../../../scripts/build_task_dataset/build_nearest_core_dataset.py)

## 功能与业务价值

构造“从 AP 查找最近上层目标设备”任务数据集。

输入数据集目录结构默认是：

datasets/
  train/*.json
  val/*.json

一次运行会生成两套内容一一对应的数据集：with_answer 保留标准答案，
without_answer 删除标准答案。每个输出 JSON 完整保留原始拓扑，并在顶层增加
任务源节点、自然语言问题和任务元数据。源节点严格选择 DEVICEROLE=AP 的节点。
目标角色按以下优先级回退：

1. CORE；
2. Gateway+CORE；
3. Gateway_vRR；
4. Gateway；
5. Firewall；
6. AGG；
7. ACC。

只有当前层级不存在任何可达 AP→目标组合时才回退到下一层级。选择目标层级后，
随机选择第一个能够到达该层级目标的 AP；如果多个目标距离相同，则保留到这些
目标的全部最短节点 ID 路径。答案只包含最短跳数和全部最短路径。

**业务价值：** 模拟 AP 查找最近上游网络角色的业务查询，覆盖核心、出口、安全边界和接入回退。

## 核心逻辑

1. 枚举 AP，并按单角色优先级逐级寻找该 AP 可达的上游目标。
2. 在首个可达角色层级内选择最近设备；并列目标及全部最短路径全部保留。
3. 生成有答案和隐藏答案两份结构一致的数据。

## 参数

| 参数 | 说明 |
|---|---|
| `-h, --help` | 显示当前脚本的完整命令帮助后退出。 |
| `--dataset-root DATASET_ROOT` | 原始数据集根目录，默认: datasets |
| `--output-root OUTPUT_ROOT` | 输出任务数据集根目录，默认: nearest_core_dataset |
| `--splits SPLITS [SPLITS ...]` | 需要处理的数据划分，默认: train val |
| `--seed SEED` | 随机种子，默认: 20260715 |
| `--progress-interval PROGRESS_INTERVAL` | 每处理多少个文件打印一次进度，默认: 100 |
| `--indent INDENT` | 输出 JSON 缩进，默认: 2 |

参数表以当前代码的 `--help` 为准。路径参数均相对于运行命令所在目录解析。

### 关键默认值

| 常量 | 当前值 |
|---|---|
| `DEFAULT_DATASET_ROOT` | `'datasets'` |
| `DEFAULT_OUTPUT_ROOT` | `'nearest_core_dataset'` |
| `DEFAULT_RANDOM_SEED` | `20260715` |
| `DEFAULT_SPLITS` | `('train', 'val')` |
| `DEFAULT_PROGRESS_INTERVAL` | `100` |
| `TARGET_ROLE_PRIORITY` | `(('core', 'CORE'), ('gateway_plus_core', 'Gateway+CORE'), ('gateway_vrr', 'Gateway_vRR'), ('gateway', 'Gateway'), ('firewall', 'Firewall'), ('aggregation', 'AGG'), ('access', 'ACC'))` |

## 运行方式

```bash
python scripts/build_task_dataset/build_nearest_core_dataset.py --help
```

确认数据路径和输出路径后，可去掉 `--help` 并传入上表参数执行。

## 关键接口

| 接口 | 职责 |
|---|---|
| `iter_json_files (function)` | 核心内部接口 |
| `load_json (function)` | 核心内部接口 |
| `get_node_role (function)` | 核心内部接口 |
| `get_node_information (function)` | 核心内部接口 |
| `build_adjacency (function)` | 根据 links 构造邻接表，directed=false 时按无向图处理。 |
| `shortest_path_tree (function)` | 用 BFS 计算源节点到所有可达节点的距离及最短路径前驱。 |
| `restore_all_shortest_paths (function)` | 根据 BFS 前驱关系恢复 source 到 target 的全部最短路径。 |
| `find_nearest_targets (function)` | 核心内部接口 |
| `choose_source_and_nearest_targets (function)` | 优先选择最高目标层级，再随机选择一个可达该层级的 AP。 |
| `build_answer (function)` | 核心内部接口 |
| `write_json (function)` | 核心内部接口 |
| `append_issue (function)` | 核心内部接口 |
| `process_file (function)` | 核心内部接口 |
| `write_stats_csv (function)` | 核心内部接口 |
| `build_dataset (function)` | 核心内部接口 |

## 输入、输出与口径

- 输入字段、候选筛选和异常状态以“核心逻辑”及源码校验条件为准。
- 构建结果通常同时包含 `with_answer` 与 `without_answer`，两者除答案字段外应保持一致。
- `build_summary.json` 和 issues/stats 文件用于解释跳过原因与最终样本数。
- 固定随机种子只有在输入文件集合与排序不变时才保证样本可复现。

[返回 任务数据集构建索引](README.md)
