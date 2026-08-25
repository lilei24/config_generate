# analyze_large_graph_edge_counts.py

> 代码位置：[`scripts/analyze_large_graph_edge_counts.py`](../../scripts/analyze_large_graph_edge_counts.py)

## 功能与业务价值

筛选节点数超过指定阈值的图，将节点数和 links 数量写入一个 CSV。

**业务价值：** 聚焦大规模站点，直接给出节点数与链路数，便于针对复杂拓扑抽样检查。

## 核心逻辑

1. 递归读取指定 split 下 JSON，先校验 nodes 数组。
2. 仅保留 node_count 严格大于阈值的文件。
3. 将 split、相对文件名、node_count 和原始 links 数量写入唯一 CSV。

## 参数

| 参数 | 说明 |
|---|---|
| `dataset_root` | 包含 train/ 和 val/ 的数据集根目录，默认: datasets |
| `-h, --help` | 显示当前脚本的完整命令帮助后退出。 |
| `-o OUTPUT_DIR, --output-dir OUTPUT_DIR` | CSV 输出目录，默认: /tmp/large_graph_edge_count_analysis |
| `--splits SPLITS [SPLITS ...]` | 需要分析的数据划分，默认: train val |
| `--min-node-count MIN_NODE_COUNT` | 只统计节点数严格大于该值的图，默认: 100 |

参数表以当前代码的 `--help` 为准。路径参数均相对于运行命令所在目录解析。

### 关键默认值

| 常量 | 当前值 |
|---|---|
| `DEFAULT_DATASET_ROOT` | `'datasets'` |
| `DEFAULT_OUTPUT_DIR` | `'/tmp/large_graph_edge_count_analysis'` |
| `DEFAULT_MIN_NODE_COUNT` | `100` |
| `OUTPUT_FILE` | `'large_graph_node_link_counts.csv'` |

## 运行方式

```bash
python scripts/analyze_large_graph_edge_counts.py --help
```

确认数据路径和输出路径后，可去掉 `--help` 并传入上表参数执行。

## 关键接口

| 接口 | 职责 |
|---|---|
| `iter_json_files (function)` | 核心内部接口 |
| `load_graph (function)` | 核心内部接口 |
| `analyze (function)` | 核心内部接口 |

## 输入、输出与口径

- 输入字段、候选筛选和异常状态以“核心逻辑”及源码校验条件为准。
- 统计脚本需区分扫描文件数、有效文件数和参与数值计算的样本数，避免分母混淆。
- 输出目录不会自动上传，也不应覆盖原始数据集。

[返回 通用数据分析与配置生成索引](README.md)
