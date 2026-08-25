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

## 关键接口

| 接口 | 类型 | 职责 |
|---|---|---|
| `parse_csv_values` | function | 实现该脚本的核心处理步骤。 |
| `parse_int_csv` | function | 实现该脚本的核心处理步骤。 |
| `iter_result_files` | function | 实现该脚本的核心处理步骤。 |
| `qa_path_for_result` | function | 实现该脚本的核心处理步骤。 |
| `normalize_json_value` | function | 实现该脚本的核心处理步骤。 |
| `answer_value` | function | 实现该脚本的核心处理步骤。 |
| `collect_field_paths` | function | Collect field paths as key tuples; array positions use the [] marker. |
| `path_text` | function | 实现该脚本的核心处理步骤。 |
| `path_endswith` | function | 实现该脚本的核心处理步骤。 |
| `answer_path_occurrences` | function | 实现该脚本的核心处理步骤。 |
| `top_level_keys` | function | 实现该脚本的核心处理步骤。 |
| `config_items` | function | 实现该脚本的核心处理步骤。 |
| `visible_top_key_count` | function | 实现该脚本的核心处理步骤。 |
| `target_hop_neighbor_counts` | function | 统计目标节点最短路径距离不超过 1、2、3 的累计节点数量。 |
| `node_factor_values` | function | 实现该脚本的核心处理步骤。 |
| `empty_metric_values` | function | 实现该脚本的核心处理步骤。 |
| `bin_label` | function | 实现该脚本的核心处理步骤。 |
| `collect_rows` | function | 实现该脚本的核心处理步骤。 |
| `group_rows` | function | 实现该脚本的核心处理步骤。 |
| `group_rows_by_top_level_key` | function | 实现该脚本的核心处理步骤。 |
| `exact_grouper` | function | 实现该脚本的核心处理步骤。 |
| `numeric_bin_grouper` | function | 实现该脚本的核心处理步骤。 |
| `write_csv` | function | 实现该脚本的核心处理步骤。 |
| `write_json` | function | 实现该脚本的核心处理步骤。 |
| `write_metric_svg` | function | 实现该脚本的核心处理步骤。 |
| `strip_internal_fields` | function | 实现该脚本的核心处理步骤。 |
| `remove_deprecated_outputs` | function | 实现该脚本的核心处理步骤。 |
| `run` | function | 实现该脚本的核心处理步骤。 |
| `parse_args` | function | 实现该脚本的核心处理步骤。 |

[返回 inference 脚本索引](README.md)
