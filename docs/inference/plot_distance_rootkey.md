# plot_distance_rootkey.py

> 代码位置：[`inference/plot_distance_rootkey.py`](../../inference/plot_distance_rootkey.py)

## 功能与业务价值

**距离与 Root Key 指标绘图。** 把距离和 root key 联合分析 CSV 绘制为热力图及柱状图。

**业务价值：** 将多配置类别、多距离层级的表格结果转成便于模型对比和汇报的可视化。

## 核心逻辑

1. 读取 `distance_by_root_key_metrics.csv`。
2. 可筛选 split、task、root key 和最低样本数。
3. 按参数选择 heatmap、分面柱图和汇总柱图，并支持多个指标。

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

路径参数相对于执行命令时的当前工作目录解析；运行 `--help` 可查看代码中的即时说明。

## 运行方式

```bash
python inference/plot_distance_rootkey.py --help
```

建议先用 `--limit` 小规模验证路径、服务和输出格式，再运行完整 split。

## 输入与输出

**主要输出：**

- 在输入 CSV 同级或 `output-dir` 下生成 PNG 图。

**统计口径与异常：**

- 扫描文件数、模型错误数、解析/评估错误数和有效评估数应分开理解，指标分母以代码实际纳入的有效对象为准。
- 推理结果目录属于实验产物，不应覆盖 QA 数据源；改变预测字段名时需同步检查 `pred-keys`。

## 关键接口

| 接口 | 类型 | 职责 |
|---|---|---|
| `load_data` | function | 实现该脚本的核心处理步骤。 |
| `plot_heatmap` | function | 实现该脚本的核心处理步骤。 |
| `plot_bar_grid` | function | 实现该脚本的核心处理步骤。 |
| `plot_bar_all` | function | 实现该脚本的核心处理步骤。 |
| `parse_args` | function | 实现该脚本的核心处理步骤。 |
| `main` | function | 实现该脚本的核心处理步骤。 |

## 相关文档

- [analyze_distance_by_root_key.py](analyze_distance_by_root_key.md)

[返回 inference 脚本索引](README.md)
