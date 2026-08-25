# build_vlan_constrained_shortest_path_dataset.py

> 代码位置：[`scripts/build_task_dataset/build_vlan_constrained_shortest_path_dataset.py`](../../../scripts/build_task_dataset/build_vlan_constrained_shortest_path_dataset.py)

## 功能与业务价值

构造指定 VLAN 下的交换机约束最短路径绕行任务数据集。

**业务价值：** 构造端到端 VLAN 可通行的约束路径任务，连接接口配置理解与图搜索。

## 核心逻辑

1. 通过 LEFTPORT/source 与 RIGHTPORT/target 唯一匹配两端 lsw-interface。
2. 解析 all、逗号列表和连续范围，取两端 allow-through-vlan 的交集。
3. 按指定 VLAN 构造子图并计算最短路径，优先保留相对无约束路径发生绕行的候选。

## 参数

| 参数 | 说明 |
|---|---|
| `-h, --help` | 显示当前脚本的完整命令帮助后退出。 |
| `--dataset-root DATASET_ROOT` | 原始数据集根目录，默认: datasets |
| `--output-root OUTPUT_ROOT` | 任务数据集输出目录，默认: vlan_constrained_shortest_path_dataset |
| `--splits SPLITS [SPLITS ...]` | 处理的数据划分，默认: train val |
| `--max-answer-paths MAX_ANSWER_PATHS` | 答案路径数超过该值时跳过候选，默认: 1000 |
| `--max-range-size MAX_RANGE_SIZE` | 单个 VLAN 范围允许展开的最大数量，默认: 4096 |
| `--config-fields CONFIG_FIELDS [CONFIG_FIELDS ...]` | 需要扫描的节点配置字段，默认只扫描 configs |
| `--progress-interval PROGRESS_INTERVAL` | 每处理 N 个文件打印进度，0 表示关闭，默认: 100 |
| `--indent INDENT` | 输出 JSON 的缩进空格数。 |

参数表以当前代码的 `--help` 为准。路径参数均相对于运行命令所在目录解析。

### 关键默认值

| 常量 | 当前值 |
|---|---|
| `DEFAULT_DATASET_ROOT` | `'datasets'` |
| `DEFAULT_OUTPUT_ROOT` | `'vlan_constrained_shortest_path_dataset'` |
| `DEFAULT_SPLITS` | `('train', 'val')` |
| `DEFAULT_MAX_ANSWER_PATHS` | `1000` |
| `DEFAULT_MAX_RANGE_SIZE` | `4096` |
| `DEFAULT_PROGRESS_INTERVAL` | `100` |
| `DEFAULT_CONFIG_FIELDS` | `('configs',)` |
| `WITH_ANSWER_DIR` | `'with_answer'` |
| `WITHOUT_ANSWER_DIR` | `'without_answer'` |
| `STATS_FILE` | `'vlan_constrained_shortest_path_stats.csv'` |
| `SUMMARY_FILE` | `'build_summary.json'` |
| `ISSUES_FILE` | `'build_issues.jsonl'` |

## 运行方式

```bash
python scripts/build_task_dataset/build_vlan_constrained_shortest_path_dataset.py --help
```

确认数据路径和输出路径后，可去掉 `--help` 并传入上表参数执行。

## 关键接口

| 接口 | 职责 |
|---|---|
| `Candidate (class)` | 核心内部接口 |
| `iter_json_files (function)` | 核心内部接口 |
| `load_graph (function)` | 核心内部接口 |
| `object_items (function)` | 核心内部接口 |
| `scalar_text (function)` | 核心内部接口 |
| `node_device (function)` | 核心内部接口 |
| `is_lsw_node (function)` | 核心内部接口 |
| `collect_interface_matches (function)` | 核心内部接口 |
| `parse_vlan_value (function)` | 核心内部接口 |
| `intersect_support (function)` | 核心内部接口 |
| `union_support (function)` | 核心内部接口 |
| `add_edge (function)` | 核心内部接口 |
| `add_supported_edge (function)` | 核心内部接口 |
| `build_strict_graphs (function)` | 仅使用接口唯一匹配且 VLAN 完整可解析的 LSW 链路。 |
| `vlan_adjacency (function)` | 核心内部接口 |
| `shortest_path_tree (function)` | 核心内部接口 |
| 其他内部接口 | 另有 9 个辅助接口，详见源码。 |

## 输入、输出与口径

- 输入字段、候选筛选和异常状态以“核心逻辑”及源码校验条件为准。
- 构建结果通常同时包含 `with_answer` 与 `without_answer`，两者除答案字段外应保持一致。
- `build_summary.json` 和 issues/stats 文件用于解释跳过原因与最终样本数。
- 固定随机种子只有在输入文件集合与排序不变时才保证样本可复现。

[返回 任务数据集构建索引](README.md)
