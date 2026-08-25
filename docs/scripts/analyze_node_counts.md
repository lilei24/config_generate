# analyze_node_counts.py

> 代码位置：[`scripts/analyze_node_counts.py`](../../scripts/analyze_node_counts.py)

## 功能与业务价值

Analyze only node counts for train/val graph JSON files.

**业务价值：** 刻画站点规模分布，辅助判断上下文长度、图算法复杂度和大图异常。

## 核心逻辑

1. 按 split 递归读取 JSON，并将坏 JSON、缺失字段和类型异常分开计数。
2. 依据模块定义的统计口径提取字段或构造无向图，完成逐文件计算。
3. 聚合全局及分组结果，输出 CSV/JSON/SVG 等可复核产物并打印进度。

## 参数

| 参数 | 说明 |
|---|---|
| `dataset_root` | Dataset root containing train/ and val/ directories. Default: datasets |
| `-h, --help` | 显示当前脚本的完整命令帮助后退出。 |
| `-o OUTPUT_DIR, --output-dir OUTPUT_DIR` | Directory for generated node-count reports. Default: /tmp/node_count_analysis |
| `--splits SPLITS [SPLITS ...]` | Split directory names to analyze. |
| `--bins BINS` | Approximate histogram bins when max node count is above 100. |

参数表以当前代码的 `--help` 为准。路径参数均相对于运行命令所在目录解析。

### 关键默认值

| 常量 | 当前值 |
|---|---|
| `DEFAULT_DATASET_ROOT` | `'datasets'` |
| `DEFAULT_OUTPUT_DIR` | `'/tmp/node_count_analysis'` |

## 运行方式

```bash
python scripts/analyze_node_counts.py --help
```

确认数据路径和输出路径后，可去掉 `--help` 并传入上表参数执行。

## 关键接口

| 接口 | 职责 |
|---|---|
| `NodeCountRow (class)` | 核心内部接口 |
| `iter_json_files (function)` | 核心内部接口 |
| `count_nodes (function)` | 核心内部接口 |
| `summarize_counts (function)` | 核心内部接口 |
| `number_summary (function)` | 核心内部接口 |
| `histogram_bins (function)` | 核心内部接口 |
| `write_csv (function)` | 核心内部接口 |
| `write_txt (function)` | 核心内部接口 |
| `write_histogram_csv (function)` | 核心内部接口 |
| `write_histogram_svg (function)` | 核心内部接口 |
| `analyze (function)` | 核心内部接口 |

## 输入、输出与口径

- 输入字段、候选筛选和异常状态以“核心逻辑”及源码校验条件为准。
- 统计脚本需区分扫描文件数、有效文件数和参与数值计算的样本数，避免分母混淆。
- 输出目录不会自动上传，也不应覆盖原始数据集。

[返回 通用数据分析与配置生成索引](README.md)
