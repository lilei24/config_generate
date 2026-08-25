# analyze_betweenness_distance_rootkey.py

> 代码位置：[`inference/analyze_betweenness_distance_rootkey.py`](../../inference/analyze_betweenness_distance_rootkey.py)

## 功能与业务价值

**中介中心性、距离与 Root Key 三维分析。** 按中介中心性、最近同名配置距离和答案顶层 Key 三层维度聚合生成指标。

**业务价值：** 在控制配置类别后分析拓扑位置和参考距离，适合为热力图和模型误差归因提供明细数据。

## 核心逻辑

1. 逐文件计算目标节点 centrality、同名配置距离和 root key。
2. 按三个维度组合分组并保留每格有效样本数。
3. 使用累计 Counter 计算组内 micro PRF 和其他汇总指标。

## 代码实现说明

- 该脚本在单样本阶段同时计算三个解释变量：目标节点归一化中介中心性分组、最近同名配置节点的 BFS 距离、答案顶层 Key。
- 图只使用 Input 当前保留的 nodes/links，因此结果反映实际提供给模型的拓扑，而不是裁剪前原始站点。
- 聚合键为 `split + task + betweenness_group + distance + root_key`。每个单元格累计有效样本的 Counter 原始计数，再计算字段路径和叶子三元组 micro PRF。
- 逐文件 CSV 用于确认目标节点、原始中心性、距离和 root key；三层聚合 CSV 是 combined heatmap 的直接输入。稀疏组合需要结合样本数过滤。

## 参数

| 参数 | 说明 | 默认值或约束 |
|---|---|---|
| `--result-root` | 推理结果根目录，目录下按 split/task 保存逐样本 JSON。 | 默认：`DEFAULT_RESULT_ROOT` |
| `--qa-root` | QA 数据根目录，用于读取 prompt、input、output 或关联同名样本。 | 默认：`DEFAULT_QA_ROOT` |
| `--output-root` | 本脚本产物输出目录。 | 默认：`DEFAULT_OUTPUT_ROOT` |
| `--splits` | 逗号分隔的数据划分，例如 `train,val`。 | 默认：`DEFAULT_SPLITS` |
| `--tasks` | 逗号分隔的任务目录，例如 `node_config_qa,device_config_qa`。 | 默认：`DEFAULT_TASKS` |
| `--pred-keys` | 按优先级查找预测内容的字段名列表，兼容历史命名。 | 默认：`DEFAULT_PRED_KEYS` |
| `--gold-key` | 结果 JSON 中监督答案字段名。 | 默认：`DEFAULT_GOLD_KEY` |
| `--array-mode` | JSON 数组路径口径：`wildcard` 统一为 `[]`，`index` 保留下标。 | 默认：`'wildcard'`；可选：`['wildcard', 'index']` |
| `--progress-interval` | 每处理多少个文件打印一次进度；非正数通常表示关闭周期打印。 | 默认：`DEFAULT_PROGRESS_INTERVAL` |
| `--limit` | 最多处理的文件数；`0` 表示不限制。 | 默认：`0` |


### 关键默认值

| 常量 | 当前代码表达式 |
|---|---|
| `DEFAULT_RESULT_ROOT` | `Path('inference-results')` |
| `DEFAULT_QA_ROOT` | `Path('520QA')` |
| `DEFAULT_OUTPUT_ROOT` | `Path('metric-results/betweenness-distance-rootkey')` |
| `DEFAULT_SPLITS` | `'val'` |
| `DEFAULT_TASKS` | `'node_config_qa'` |
| `DEFAULT_PRED_KEYS` | `'model-output,model_output,model-ouput'` |
| `DEFAULT_GOLD_KEY` | `'answer'` |
| `DEFAULT_PROGRESS_INTERVAL` | `500` |


## 输入与输出

**主要输出：**

- `per_file_betweenness_distance_rootkey.csv`
- `betweenness_distance_rootkey_metrics.csv`
- `summary.json`

**统计口径与异常：**

- 扫描文件数、模型错误数、解析/评估错误数和有效评估数应分开理解，指标分母以代码实际纳入的有效对象为准。
- 推理结果目录属于实验产物，不应覆盖 QA 数据源；改变预测字段名时需同步检查 `pred-keys`。


## 相关文档

- [plot_betweenness_distance_rootkey.py](plot_betweenness_distance_rootkey.md)

[返回 inference 脚本索引](README.md)
