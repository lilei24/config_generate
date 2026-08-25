# batch_evaluate_qa.py

> 代码位置：[`inference/batch_evaluate_qa.py`](../../inference/batch_evaluate_qa.py)

## 功能与业务价值

**离线批量评估与 Token 因素分析。** 对已保存推理结果进行统一离线评估，并关联原 QA Input 的粗略 Token 数和节点数。

**业务价值：** 无需重新调用模型即可复算指标、核对错误样本，并判断上下文长度是否影响模型表现。

## 核心逻辑

1. 按 split/task 找到推理结果，并兼容 `model-output`、`model_output`、历史 `model-ouput` 字段。
2. 区分模型调用错误、预测解析错误和评估错误；只有可正常评估样本进入指标累计。
3. 从 QA 根目录定位同名样本，估算 Input Token 并读取节点数量。
4. 输出逐文件指标、Token 分桶指标、错误汇总和总 summary；分桶聚合使用累计计数得到 micro 指标。

## 代码实现说明

### 结果关联与状态分类

- 程序从 `result-root/<split>/<task>` 递归读取结果，再用相对路径到 `qa-root/<split>/<task>` 定位原 QA。这样可以读取 Input 规模，同时不要求推理结果重复保存完整上下文。
- 预测字段按 `--pred-keys` 顺序查找，兼容当前 `model-output` 和历史拼写。结果中已有 `error` 时记为 model error；预测或答案不能转成合法 JSON、QA 无法关联等情况记为 eval error。
- 只有成功取得预测、答案并完成 `evaluate_json` 的文件增加 `evaluated_files`，模型错误和评估错误不会作为零分加入核心指标分母。

### 聚合与 Token 分桶

- 逐样本指标写入 JSONL，同时把 PRF 所需的 correct、pred total、gold total 累加到 overall 和 split/task 统计器，因此汇总的 PRF 是 micro 口径。
- QA Input 先稳定 JSON 序列化，再按统一粗略 BPE 规则估算 Token；节点数直接读取 `input.nodes` 长度。Token 估算用于相对分析，不等同于特定模型 tokenizer 的精确值。
- Token 阈值被转换为左闭右开区间，最后一个区间无上界。每个分桶只聚合其中成功评估样本，CSV 同时给出扫描数、有效数和各指标，便于核对分母。

### 产物关系

- `per_file_metrics.jsonl` 保存完整逐样本指标；`per_file_token_metrics.csv` 是便于 Excel 分析的扁平版本。
- `token_metric_bins.csv/svg` 展示长度区间与效果关系；`summary.json` 保存全局和 split/task 聚合；两类错误分别进入明细及原因计数。

## 参数

| 参数 | 说明 | 默认值或约束 |
|---|---|---|
| `--result-root` | 推理结果根目录，目录下按 split/task 保存逐样本 JSON。 | 默认：`DEFAULT_RESULT_ROOT` |
| `--qa-root` | QA 数据根目录，用于读取 prompt、input、output 或关联同名样本。 | 默认：`DEFAULT_QA_ROOT` |
| `--output-root` | 本脚本产物输出目录。 | 默认：`DEFAULT_OUTPUT_ROOT` |
| `--splits` | 逗号分隔的数据划分，例如 `train,val`。 | 默认：`DEFAULT_SPLITS` |
| `--tasks` | 逗号分隔的任务目录，例如 `node_config_qa,device_config_qa`。 | 默认：`DEFAULT_TASKS` |
| `--pred-keys` | 按优先级查找预测内容的字段名列表，兼容历史命名。 | 默认：`','.join(DEFAULT_PRED_KEYS)` |
| `--gold-key` | 结果 JSON 中监督答案字段名。 | 默认：`DEFAULT_GOLD_KEY` |
| `--array-mode` | JSON 数组路径口径：`wildcard` 统一为 `[]`，`index` 保留下标。 | 默认：`'wildcard'`；可选：`['wildcard', 'index']` |
| `--token-bins` | Comma-separated token bin upper bounds. Default: %(default)s | 默认：`DEFAULT_TOKEN_BINS` |
| `--progress-interval` | 每处理多少个文件打印一次进度；非正数通常表示关闭周期打印。 | 默认：`DEFAULT_PROGRESS_INTERVAL` |
| `--limit` | 最多处理的文件数；`0` 表示不限制。 | 默认：`0` |

路径参数相对于执行命令时的当前工作目录解析；运行 `--help` 可查看代码中的即时说明。

### 关键默认值

| 常量 | 当前代码表达式 |
|---|---|
| `DEFAULT_RESULT_ROOT` | `Path('inference-results')` |
| `DEFAULT_OUTPUT_ROOT` | `Path('metric-results/token-metric-analysis')` |
| `DEFAULT_QA_ROOT` | `Path('520QA')` |
| `DEFAULT_SPLITS` | `'train'` |
| `DEFAULT_TASKS` | `'node_config_qa'` |
| `DEFAULT_PRED_KEYS` | `('model-output', 'model_output', 'model-ouput')` |
| `DEFAULT_GOLD_KEY` | `'answer'` |
| `DEFAULT_PROGRESS_INTERVAL` | `500` |
| `DEFAULT_TOKEN_BINS` | `'4096,8192,16384,32768,65536,131072,262144,524288,1048576,2097152'` |

## 运行方式

```bash
python inference/batch_evaluate_qa.py --help
```

建议先用 `--limit` 小规模验证路径、服务和输出格式，再运行完整 split。

## 输入与输出

**主要输出：**

- `per_file_metrics.jsonl`
- `per_file_token_metrics.csv`
- `token_metric_bins.csv` 与 `token_metric_bins.svg`
- `eval_errors.jsonl`、`error_summary.csv`、`summary.json`

**统计口径与异常：**

- 扫描文件数、模型错误数、解析/评估错误数和有效评估数应分开理解，指标分母以代码实际纳入的有效对象为准。
- 推理结果目录属于实验产物，不应覆盖 QA 数据源；改变预测字段名时需同步检查 `pred-keys`。


## 相关文档

- [metric.py](metric.md)
- [batch_evaluate_qa_swanlab.py](batch_evaluate_qa_swanlab.md)

[返回 inference 脚本索引](README.md)
