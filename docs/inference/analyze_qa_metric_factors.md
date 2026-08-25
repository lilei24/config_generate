# analyze_qa_metric_factors.py

> 代码位置：[`inference/analyze_qa_metric_factors.py`](../../inference/analyze_qa_metric_factors.py)

## 功能与业务价值

**QA 上下文因素与指标分析。** 从每个样本内部提取顶层 Key、答案 Path 在 Input 中的出现次数、节点数、1/2/3 跳邻居数和可见配置 Key 数，并分析其与指标的关系。

**业务价值：** 用于判断结构参考、拓扑规模、局部邻域和上下文干扰如何影响配置生成质量。

## 核心逻辑

1. 关联推理结果与同名 QA，定位 metadata 中的目标节点。
2. 逐样本统计答案 Path 在该样本 Input 全文中的出现次数。
3. 统计节点数、包含累计近邻的 1/2/3-hop 数，以及目标节点和所有节点可见顶层 Key 数。
4. 按可配置边界分桶，并额外按答案顶层 Key 细分聚合。
5. 所有分桶同时输出样本数和核心生成指标。

## 代码实现说明

- 推理结果先与同 split/task/相对路径的 QA 对齐。答案顶层 Key 来自 `answer`，目标节点优先从 `metadata.target.node_id` 获取，Input 负责提供保留后的 nodes、links 和 configs/config。
- 答案 Path 出现次数是“当前样本内”统计：先展开该样本答案的每条字段路径，再扫描同一样本 Input 的全部路径 Counter，记录每条答案 Path 在 Input 中出现多少次，而不是跨数据集做全局词频。
- 目标节点可见顶层 Key 数只统计其未隐藏配置；所有节点可见 Key 数则遍历 `input.nodes` 累加。二者可继续按答案 top-level key 细分，区分结构参考不足与上下文干扰。
- 邻居数在 Input 无向图上从目标节点 BFS：1-hop 是距离不超过 1 的其他节点，2-hop 包含 1-hop，3-hop 包含前两层。节点总数直接取有效 node 对象数量。
- 数值因素按命令行边界形成有序区间；每个分组使用成功评估样本累计指标，并保留 total/evaluated/error 数，避免把稀疏组的偶然高分当成稳定结论。

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
| `--path-occurrence-bins` | 控制该脚本对应处理行为。 | 默认：`DEFAULT_PATH_OCCURRENCE_BINS` |
| `--node-count-bins` | 控制该脚本对应处理行为。 | 默认：`DEFAULT_NODE_COUNT_BINS` |
| `--neighbor-count-bins` | 控制该脚本对应处理行为。 | 默认：`DEFAULT_NEIGHBOR_COUNT_BINS` |
| `--top-key-count-bins` | 控制该脚本对应处理行为。 | 默认：`DEFAULT_TOP_KEY_COUNT_BINS` |
| `--progress-interval` | 每处理多少个文件打印一次进度；非正数通常表示关闭周期打印。 | 默认：`DEFAULT_PROGRESS_INTERVAL` |
| `--limit` | 最多处理的文件数；`0` 表示不限制。 | 默认：`0` |

路径参数相对于执行命令时的当前工作目录解析；运行 `--help` 可查看代码中的即时说明。

### 关键默认值

| 常量 | 当前代码表达式 |
|---|---|
| `DEFAULT_RESULT_ROOT` | `Path('inference-results')` |
| `DEFAULT_QA_ROOT` | `Path('520QA')` |
| `DEFAULT_OUTPUT_ROOT` | `Path('metric-results/qa-factor-analysis')` |
| `DEFAULT_SPLITS` | `'train'` |
| `DEFAULT_TASKS` | `'node_config_qa'` |
| `DEFAULT_PRED_KEYS` | `'model-output,model_output,model-ouput'` |
| `DEFAULT_GOLD_KEY` | `'answer'` |
| `DEFAULT_PROGRESS_INTERVAL` | `500` |
| `DEFAULT_PATH_OCCURRENCE_BINS` | `'0,1,2,5,10,20,50,100,200,500,1000'` |
| `DEFAULT_NODE_COUNT_BINS` | `'0,1,2,5,10,20,50,100,200,500,1000'` |
| `DEFAULT_NEIGHBOR_COUNT_BINS` | `'0,1,2,3,5,10,20,50,100,200'` |
| `DEFAULT_TOP_KEY_COUNT_BINS` | `'0,1,2,5,10,20,50,100,200,500,1000,2000'` |

## 运行方式

```bash
python inference/analyze_qa_metric_factors.py --help
```

建议先用 `--limit` 小规模验证路径、服务和输出格式，再运行完整 split。

## 输入与输出

**主要输出：**

- `per_file_factor_metrics.csv`、`answer_path_input_occurrences.csv`
- `top_level_key_metrics.csv`、`answer_path_occurrence_metrics.csv`、`node_count_metrics.csv`
- `target_1hop/2hop/3hop_neighbor_count_metrics.csv`
- 三个按顶层 Key 细分的因素 CSV 及对应 SVG
- `summary.json`

**统计口径与异常：**

- 扫描文件数、模型错误数、解析/评估错误数和有效评估数应分开理解，指标分母以代码实际纳入的有效对象为准。
- 推理结果目录属于实验产物，不应覆盖 QA 数据源；改变预测字段名时需同步检查 `pred-keys`。


[返回 inference 脚本索引](README.md)
