# plot_betweenness_distance.py

> 代码位置：[`inference/plot_betweenness_distance.py`](../../inference/plot_betweenness_distance.py)

## 功能与业务价值

**中介中心性与距离指标绘图。** 读取逐文件中介中心性/距离结果，在 root key 维度聚合后绘制热力图和柱状图。

**业务价值：** 用于观察拓扑位置和参考距离的二维趋势，并控制最低样本数避免稀疏格误导。

## 核心逻辑

1. 读取 `per_file_betweenness_by_distance.csv`。
2. 支持筛选 root key、split、task 和指标。
3. 按 centrality group 与 distance 形成矩阵或柱状图。

## 代码实现说明

- 脚本读取逐文件 `per_file_betweenness_by_distance.csv`，因此可以先按 root key 筛选，再对相同中心性组和距离的样本重新求平均。
- 只保留状态正常且指标可转为数值的记录；split、task、root key 和 `min-files` 共同控制进入图表的数据。
- heatmap 以中介中心性组和距离构造二维矩阵；bar-grid 展示不同维度分面；bar-all 将筛选结果放在同一图比较。
- 该绘图阶段的均值是 CSV 行级数值聚合，不会重新构造 micro Counter；需要严格 micro 口径时应优先使用分析脚本输出的聚合 CSV。

## 参数

| 参数 | 说明 | 默认值或约束 |
|---|---|---|
| `csv` | Path to per_file_betweenness_by_distance.csv. Default: metric-results/betweenness-by-distance/per_file_betweenness_by_distance.csv | 默认：`None` |
| `--output-dir` | Output directory for plots. Default: sibling of CSV / plots/. | 默认：`None` |
| `--metrics` | 逗号分隔的绘图指标名。 | 默认：`'field_path_f1,leaf_triple_f1,value_accuracy'` |
| `--root-key` | 仅绘制指定顶层配置 Key；可重复传入。 | 默认：`None` |
| `--split` | 单个数据划分，例如 `train` 或 `val`。 | 默认：`None` |
| `--task` | 单个任务目录过滤条件。 | 默认：`None` |
| `--min-files` | 每个绘图分组至少需要的有效样本数。 | 默认：`3` |
| `--plots` | 逗号分隔的图类型。 | 默认：`'heatmap,bar-grid,bar-all'` |

路径参数相对于执行命令时的当前工作目录解析；运行 `--help` 可查看代码中的即时说明。

## 运行方式

```bash
python inference/plot_betweenness_distance.py --help
```

建议先用 `--limit` 小规模验证路径、服务和输出格式，再运行完整 split。

## 输入与输出

**主要输出：**

- 在目标输出目录生成 PNG 图。

**统计口径与异常：**

- 扫描文件数、模型错误数、解析/评估错误数和有效评估数应分开理解，指标分母以代码实际纳入的有效对象为准。
- 推理结果目录属于实验产物，不应覆盖 QA 数据源；改变预测字段名时需同步检查 `pred-keys`。


## 相关文档

- [analyze_betweenness_by_distance.py](analyze_betweenness_by_distance.md)

[返回 inference 脚本索引](README.md)
