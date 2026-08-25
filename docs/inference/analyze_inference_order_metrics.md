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

## 代码实现说明

- 脚本用与批量推理一致的任务顺序和文件路径字典序重建 step；没有使用文件系统返回顺序或随机打乱，因此可以对齐 SwanLab 横轴。
- 每个结果重新解析预测与答案并计算单样本指标。错误文件保留原始 step 和原因，但不进入有效指标均值。
- `window_*` 只对当前 `group-size` 范围内的有效样本求平均，用于发现局部阶段变化；`cumulative_*` 对从第一个文件到当前组结束为止的全部有效样本求平均，用于观察整体收敛趋势。
- 分组边界按处理文件序号形成，例如组大小 100 时为 1-100、101-200。组内有效数会单独输出，因此某组错误较多时不能只看 F1 曲线。

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


[返回 inference 脚本索引](README.md)
