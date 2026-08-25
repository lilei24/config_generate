# analyze_edge_counts.py

> 代码位置：[`scripts/analyze_edge_counts.py`](../../scripts/analyze_edge_counts.py)

## 功能与业务价值

Analyze only edge counts for train/val graph JSON files.

**业务价值：** 刻画物理连接规模及长尾，辅助识别复杂站点并评估图搜索成本。

## 核心逻辑

1. 逐文件校验顶层对象和 links 数组，空 links 作为有效的 0 条边。
2. 主图对 0-P95 重新细分并设置溢出桶，避免长尾压缩主体。
3. 另用二次幂分桶、对数 Y 轴、CDF 和分位数保留完整长尾信息。

## 参数

| 参数 | 说明 |
|---|---|
| `dataset_root` | Dataset root containing train/ and val/ directories. Default: datasets |
| `-h, --help` | 显示当前脚本的完整命令帮助后退出。 |
| `-o OUTPUT_DIR, --output-dir OUTPUT_DIR` | Directory for generated edge-count reports. Default: /tmp/edge_count_analysis |
| `--splits SPLITS [SPLITS ...]` | Split directory names to analyze. |
| `--bins BINS` | Approximate histogram bins when max edge count is above 100. |
| `--detail-percentile DETAIL_PERCENTILE` | Upper percentile shown in the detailed histogram. Default: 95. |

参数表以当前代码的 `--help` 为准。路径参数均相对于运行命令所在目录解析。

### 关键默认值

| 常量 | 当前值 |
|---|---|
| `DEFAULT_DATASET_ROOT` | `'datasets'` |
| `DEFAULT_OUTPUT_DIR` | `'/tmp/edge_count_analysis'` |

## 运行方式

```bash
python scripts/analyze_edge_counts.py --help
```

确认数据路径和输出路径后，可去掉 `--help` 并传入上表参数执行。

## 关键接口

| 接口 | 职责 |
|---|---|
| `EdgeCountRow (class)` | 核心内部接口 |
| `iter_json_files (function)` | 核心内部接口 |
| `count_edges (function)` | 统计原始 links 数组长度，不过滤重复链路、自环或无效端点。 |
| `number_summary (function)` | 核心内部接口 |
| `summarize_counts (function)` | 核心内部接口 |
| `percentile (function)` | 使用线性插值计算分位数，ratio 取值范围为 0 到 1。 |
| `detail_histogram_bins (function)` | 细分 0 到指定分位数，并将长尾样本放入独立溢出桶。 |
| `logarithmic_histogram_bins (function)` | 按 0、1、2-3、4-7 等二次幂区间保留完整长尾。 |
| `quantile_rows (function)` | 核心内部接口 |
| `cdf_points (function)` | 核心内部接口 |
| `write_csv (function)` | 核心内部接口 |
| `write_txt (function)` | 核心内部接口 |
| `write_histogram_csv (function)` | 核心内部接口 |
| `write_quantiles_csv (function)` | 核心内部接口 |
| `write_histogram_svg (function)` | 核心内部接口 |
| `write_cdf_svg (function)` | 核心内部接口 |
| 其他内部接口 | 另有 1 个辅助接口，详见源码。 |

## 输入、输出与口径

- 输入字段、候选筛选和异常状态以“核心逻辑”及源码校验条件为准。
- 统计脚本需区分扫描文件数、有效文件数和参与数值计算的样本数，避免分母混淆。
- 输出目录不会自动上传，也不应覆盖原始数据集。

[返回 通用数据分析与配置生成索引](README.md)
