# plot_distance_rootkey.py

> 代码位置：[`inference/plot_distance_rootkey.py`](../../inference/plot_distance_rootkey.py)

## 功能与业务价值

**距离与 Root Key 指标绘图。** 把距离和 root key 联合分析 CSV 绘制为热力图及柱状图。

**业务价值：** 将多配置类别、多距离层级的表格结果转成便于模型对比和汇报的可视化。

## 核心逻辑

1. 读取 `distance_by_root_key_metrics.csv`。
2. 可筛选 split、task、root key 和最低样本数。
3. 按参数选择 heatmap、分面柱图和汇总柱图，并支持多个指标。

## 代码实现说明

- 输入 CSV 应由 `analyze_distance_by_root_key.py` 生成，至少包含 distance、root_key、样本数和所选指标列。脚本不重新读取 JSON 或计算模型指标。
- 过滤顺序为 split/task、指定 root key、最低有效文件数；过滤后的距离按 0、有限整数、inf 的业务顺序排列，而不是普通字符串排序。
- heatmap 将距离和 root key 组成矩阵；bar-grid 为每个 Key 生成分面；bar-all 汇总展示全部 Key。`metrics` 可一次指定多列，每个指标分别出图。
- 输出目录未指定时使用输入 CSV 同级绘图目录，图像采用固定 DPI 和紧凑边界，便于直接放入报告。

## 参数

| 参数 | 说明 | 默认值或约束 |
|---|---|---|
| `csv` | Path to distance_by_root_key_metrics.csv. Default: metric-results/distance-by-root-key/distance_by_root_key_metrics.csv | 默认：`None` |
| `--output-dir` | Output directory for plots. Default: sibling of CSV / plots/. | 默认：`None` |
| `--metrics` | 逗号分隔的绘图指标名。 | 默认：`'field_path_f1,leaf_triple_f1,value_accuracy'` |
| `--root-key` | 仅绘制指定顶层配置 Key；可重复传入。 | 默认：`None` |
| `--split` | 单个数据划分，例如 `train` 或 `val`。 | 默认：`None` |
| `--task` | 单个任务目录过滤条件。 | 默认：`None` |
| `--min-files` | 每个绘图分组至少需要的有效样本数。 | 默认：`3` |
| `--plots` | 逗号分隔的图类型。 | 默认：`'heatmap,bar-grid,bar-all'` |



## 输入与输出

**主要输出：**

- 在输入 CSV 同级或 `output-dir` 下生成 PNG 图。

**统计口径与异常：**

- 扫描文件数、模型错误数、解析/评估错误数和有效评估数应分开理解，指标分母以代码实际纳入的有效对象为准。
- 推理结果目录属于实验产物，不应覆盖 QA 数据源；改变预测字段名时需同步检查 `pred-keys`。


## 相关文档

- [analyze_distance_by_root_key.py](analyze_distance_by_root_key.md)

[返回 inference 脚本索引](README.md)
