# analyze_model_output_tokens.py

> 代码位置：[`inference/analyze_model_output_tokens.py`](../../inference/analyze_model_output_tokens.py)

## 功能与业务价值

**模型输出 Token 分布分析。** 统计已保存 `model-output` 的粗略 Token 数、分位数、阈值覆盖率和直方图。

**业务价值：** 帮助估算生成长度、吞吐和成本，并识别异常冗长或包含思考过程的回答。

## 核心逻辑

1. 按 split/task 扫描结果并识别兼容预测字段。
2. 将结构化预测稳定序列化后使用项目统一的粗略 BPE 估算。
3. 分别统计成功、错误、缺失预测和不同值类型。
4. 输出逐文件、汇总、分位数、上下文阈值、直方图 CSV/JSON/SVG。

## 代码实现说明

- 结果文件按 split/task 递归扫描，并按 `pred-keys` 顺序读取预测。结构化 dict/list 会稳定序列化，字符串直接作为模型文本，保证 Token 统计对象与实际输出含义一致。
- 粗略 BPE 规则按中英文、数字、标点等字符片段估算，不加载具体模型 tokenizer，优势是速度快且无模型依赖；结果适合比较分布，不适合作为服务硬截断的唯一依据。
- 每个文件记录预测字段名、值类型、字符数、Token 数和状态。结果已有 error、缺少预测字段或值类型异常时单独计数，不进入正常 Token 数值分布。
- 分位数表反映 P50/P90/P95/P99 等位置；阈值表计算输出不超过 4K 至 2M 各阈值的样本比例；直方图 CSV 和 SVG 使用相同分箱边界。

## 参数

| 参数 | 说明 | 默认值或约束 |
|---|---|---|
| `--result-root` | 推理结果根目录，目录下按 split/task 保存逐样本 JSON。 | 默认：`DEFAULT_RESULT_ROOT` |
| `--output-root` | 本脚本产物输出目录。 | 默认：`DEFAULT_OUTPUT_ROOT` |
| `--splits` | 逗号分隔的数据划分，例如 `train,val`。 | 默认：`DEFAULT_SPLITS` |
| `--tasks` | 逗号分隔的任务目录，例如 `node_config_qa,device_config_qa`。 | 默认：`DEFAULT_TASKS` |
| `--pred-keys` | 按优先级查找预测内容的字段名列表，兼容历史命名。 | 默认：`','.join(DEFAULT_PRED_KEYS)` |
| `--thresholds` | Comma-separated token thresholds. | 默认：`DEFAULT_THRESHOLDS` |
| `--histogram-bins` | 控制该脚本对应处理行为。 | 默认：`DEFAULT_HISTOGRAM_BINS` |
| `--progress-interval` | 每处理多少个文件打印一次进度；非正数通常表示关闭周期打印。 | 默认：`DEFAULT_PROGRESS_INTERVAL` |
| `--limit` | 最多处理的文件数；`0` 表示不限制。 | 默认：`0` |

路径参数相对于执行命令时的当前工作目录解析；运行 `--help` 可查看代码中的即时说明。

### 关键默认值

| 常量 | 当前代码表达式 |
|---|---|
| `DEFAULT_RESULT_ROOT` | `Path('inference-results')` |
| `DEFAULT_OUTPUT_ROOT` | `Path('model-output-token-analysis')` |
| `DEFAULT_SPLITS` | `'train'` |
| `DEFAULT_TASKS` | `'node_config_qa'` |
| `DEFAULT_PRED_KEYS` | `('model-output', 'model_output', 'model-ouput')` |
| `DEFAULT_PROGRESS_INTERVAL` | `500` |
| `DEFAULT_THRESHOLDS` | `'4096,8192,16384,32768,65536,131072,262144,524288,1048576,2097152'` |
| `DEFAULT_HISTOGRAM_BINS` | `40` |

## 运行方式

```bash
python inference/analyze_model_output_tokens.py --help
```

建议先用 `--limit` 小规模验证路径、服务和输出格式，再运行完整 split。

## 输入与输出

**主要输出：**

- `model_output_token_counts.csv`
- `model_output_token_summary.csv/json`
- `model_output_token_quantiles.csv`
- `model_output_token_context_thresholds.csv`
- `model_output_token_histogram.csv/svg`

**统计口径与异常：**

- 扫描文件数、模型错误数、解析/评估错误数和有效评估数应分开理解，指标分母以代码实际纳入的有效对象为准。
- 推理结果目录属于实验产物，不应覆盖 QA 数据源；改变预测字段名时需同步检查 `pred-keys`。


[返回 inference 脚本索引](README.md)
