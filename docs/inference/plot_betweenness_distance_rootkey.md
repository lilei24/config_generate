# plot_betweenness_distance_rootkey.py

> 代码位置：[`inference/plot_betweenness_distance_rootkey.py`](../../inference/plot_betweenness_distance_rootkey.py)

## 功能与业务价值

**三维因素联合热力图。** 把 `betweenness × distance × root key` 聚合结果绘制为 combined heatmap 等图。

**业务价值：** 将大量稀疏组合压缩到一张带样本数标注的图中，便于比较配置类别的拓扑敏感性。

## 核心逻辑

1. 读取三层聚合 CSV 并应用 split/task/root key/最低样本数过滤。
2. 默认仅绘制 combined heatmap。
3. 按 root key 和距离组织行、以中介中心性分组为列，单元格显示指标。
4. 可选输出其他热力图、折线和柱状图。

## 代码实现说明

- 输入是三层聚合 CSV，每行代表一个 `betweenness group × distance × root key` 组合，并包含该组合有效样本数和指标。
- 默认 `combined-heatmap` 将 root key 与 distance 组合成纵轴行，中介中心性分组作为横轴列；单元格读取指定指标，并同时参考样本数决定是否显示。
- 中介中心性区间、实际距离和 root key 使用显式排序键，避免 CSV/Excel 把区间按字符串错误排序。没有数据的组合保留为空白，不误填 0。
- combined 图同时输出 PNG 和 PDF；其他可选模式包括独立热力图、按距离折线和柱状图。`min-files` 用于隐藏样本不足的格子。

## 参数

| 参数 | 说明 | 默认值或约束 |
|---|---|---|
| `csv` | Path to betweenness_distance_rootkey_metrics.csv. Default: metric-results/betweenness-distance-rootkey/betweenness_distance_rootkey_metrics.csv | 默认：`None` |
| `--output-dir` | Output directory for plots. Default: sibling of CSV / plots/. | 默认：`None` |
| `--metrics` | 逗号分隔的绘图指标名。 | 默认：`'field_path_f1,leaf_triple_f1,value_accuracy'` |
| `--root-key` | 仅绘制指定顶层配置 Key；可重复传入。 | 默认：`None` |
| `--split` | 单个数据划分，例如 `train` 或 `val`。 | 默认：`None` |
| `--task` | 单个任务目录过滤条件。 | 默认：`None` |
| `--min-files` | 每个绘图分组至少需要的有效样本数。 | 默认：`3` |
| `--plots` | 逗号分隔的图类型。 | 默认：`'combined-heatmap'` |



## 输入与输出

**主要输出：**

- combined heatmap 输出 PNG 与 PDF；其他图按选择写入输出目录。

**统计口径与异常：**

- 扫描文件数、模型错误数、解析/评估错误数和有效评估数应分开理解，指标分母以代码实际纳入的有效对象为准。
- 推理结果目录属于实验产物，不应覆盖 QA 数据源；改变预测字段名时需同步检查 `pred-keys`。


## 相关文档

- [analyze_betweenness_distance_rootkey.py](analyze_betweenness_distance_rootkey.md)

[返回 inference 脚本索引](README.md)
