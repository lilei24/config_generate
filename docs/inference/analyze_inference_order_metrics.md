# analyze_inference_order_metrics.py

> 代码位置：[`inference/analyze_inference_order_metrics.py`](../../inference/analyze_inference_order_metrics.py)

## 功能与业务价值

**推理顺序指标趋势分析。** 按实际文件推理顺序每 N 个样本分组，比较窗口指标与累计指标。

**业务价值：** 用于定位指标先降后升、服务状态漂移或数据顺序造成的阶段性表现变化。

## 核心逻辑

1. 按 split/task 和文件名字典序重建推理顺序。
2. 逐文件复算核心指标并保留错误。
3. 每 `group-size` 样本计算窗口平均，同时计算从首样本到当前组的累计平均。
4. 输出趋势 CSV、错误表、summary 和 SVG。

## 参数

| 参数 | 说明 | 默认值或约束 |
|---|---|---|
| `--result-root` | 推理结果根目录，目录下按 split/task 保存逐样本 JSON。 | 默认：`DEFAULT_RESULT_ROOT` |
| `--output-root` | 本脚本产物输出目录。 | 默认：`DEFAULT_OUTPUT_ROOT` |
| `--splits` | 逗号分隔的数据划分，例如 `train,val`。 | 默认：`DEFAULT_SPLITS` |
| `--tasks` | 逗号分隔的任务目录，例如 `node_config_qa,device_config_qa`。 | 默认：`DEFAULT_TASKS` |
| `--group-size` | 按推理顺序分组时每组样本数。 | 默认：`DEFAULT_GROUP_SIZE` |
| `--pred-keys` | 按优先级查找预测内容的字段名列表，兼容历史命名。 | 默认：`','.join(DEFAULT_PRED_KEYS)` |
| `--gold-key` | 结果 JSON 中监督答案字段名。 | 默认：`DEFAULT_GOLD_KEY` |
| `--array-mode` | JSON 数组路径口径：`wildcard` 统一为 `[]`，`index` 保留下标。 | 默认：`'wildcard'`；可选：`['wildcard', 'index']` |
| `--progress-interval` | 每处理多少个文件打印一次进度；非正数通常表示关闭周期打印。 | 默认：`DEFAULT_PROGRESS_INTERVAL` |
| `--limit` | 最多处理的文件数；`0` 表示不限制。 | 默认：`0` |

路径参数相对于执行命令时的当前工作目录解析；运行 `--help` 可查看代码中的即时说明。

### 关键默认值

| 常量 | 当前代码表达式 |
|---|---|
| `DEFAULT_OUTPUT_ROOT` | `Path('metric-results/inference-order-analysis')` |
| `DEFAULT_SPLITS` | `'val'` |
| `DEFAULT_TASKS` | `'node_config_qa'` |
| `DEFAULT_GROUP_SIZE` | `100` |

## 运行方式

```bash
python inference/analyze_inference_order_metrics.py --help
```

建议先用 `--limit` 小规模验证路径、服务和输出格式，再运行完整 split。

## 输入与输出

**主要输出：**

- `per_file_inference_order_metrics.csv`
- `inference_order_group_metrics.csv`
- `inference_order_metric_trend.svg`
- `inference_order_errors.csv`、`summary.json`

**统计口径与异常：**

- 扫描文件数、模型错误数、解析/评估错误数和有效评估数应分开理解，指标分母以代码实际纳入的有效对象为准。
- 推理结果目录属于实验产物，不应覆盖 QA 数据源；改变预测字段名时需同步检查 `pred-keys`。

## 关键接口

| 接口 | 类型 | 职责 |
|---|---|---|
| `parse_csv_values` | function | 实现该脚本的核心处理步骤。 |
| `write_csv` | function | 实现该脚本的核心处理步骤。 |
| `write_json` | function | 实现该脚本的核心处理步骤。 |
| `metric_values_for_prefix` | function | 实现该脚本的核心处理步骤。 |
| `mean_metric_values` | function | 实现该脚本的核心处理步骤。 |
| `ordered_result_files` | function | 实现该脚本的核心处理步骤。 |
| `collect_file_rows` | function | 实现该脚本的核心处理步骤。 |
| `group_rows` | function | 实现该脚本的核心处理步骤。 |
| `error_rows` | function | 实现该脚本的核心处理步骤。 |
| `write_metric_svg` | function | 实现该脚本的核心处理步骤。 |
| `run` | function | 实现该脚本的核心处理步骤。 |
| `parse_args` | function | 实现该脚本的核心处理步骤。 |

[返回 inference 脚本索引](README.md)
