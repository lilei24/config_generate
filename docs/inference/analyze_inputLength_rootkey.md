# analyze_inputLength_rootkey.py

> 代码位置：[`inference/analyze_inputLength_rootkey.py`](../../inference/analyze_inputLength_rootkey.py)

## 功能与业务价值

**上下文长度与 Root Key 分析及热力图。** 估算 QA Input Token 数，按长度区间和答案顶层 Key 聚合生成指标，并直接输出热力图。

**业务价值：** 用于选择上下文窗口、识别长上下文退化，并判断不同配置类别对长度的敏感性。

## 核心逻辑

1. 稳定序列化 Input 并使用粗略 BPE 规则估算 Token。
2. 按可配置阈值形成有序长度区间。
3. 输出长度、root key 及二者交叉的指标；热力图单元显示指标和样本数。
4. 支持最小样本数过滤、指定绘图指标和图中 Info 文本。

## 代码实现说明

- 脚本从原 QA 读取 `input`，使用排序稳定的 JSON 文本和项目粗略 BPE 规则估算上下文 Token；Prompt 固定说明文字和模型输出 Token 不计入该数值。
- 阈值列表生成有序区间，例如 4096、8192 对应 `<4K`、`4K-8K` 等；边界和标签由同一函数产生，CSV 与热力图列顺序保持一致。
- 单样本同时记录 Input 字符数、粗略 Token、节点数、答案 root key 和生成指标。随后分别按长度、root key、`长度 × root key` 三种粒度聚合。
- 热力图横轴为长度区间，纵轴为 root key；颜色由 `plot-metric` 决定，单元格文字同时显示指标值和有效样本数。低于 `heatmap-min-files` 的格子不显示指标，`heatmap-info` 被绘制在图底部空白区。
- `--no-heatmap` 只关闭 SVG，不影响逐文件 CSV、三张聚合 CSV 和 summary 输出。

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
| `--input-length-thresholds` | 控制该脚本对应处理行为。 | 默认：`DEFAULT_INPUT_LENGTH_THRESHOLDS` |
| `--plot-metric` | Metric used in heatmap color. | 默认：`DEFAULT_PLOT_METRIC` |
| `--heatmap-min-files` | Minimum evaluated files per heatmap cell. | 默认：`1` |
| `--heatmap-info` | Free-form text rendered in the heatmap bottom whitespace. | 默认：`''` |
| `--no-heatmap` | 关闭热力图输出。 | 开关参数 |
| `--progress-interval` | 每处理多少个文件打印一次进度；非正数通常表示关闭周期打印。 | 默认：`DEFAULT_PROGRESS_INTERVAL` |
| `--limit` | 最多处理的文件数；`0` 表示不限制。 | 默认：`0` |


### 关键默认值

| 常量 | 当前代码表达式 |
|---|---|
| `DEFAULT_RESULT_ROOT` | `Path('inference-results')` |
| `DEFAULT_QA_ROOT` | `Path('520QA')` |
| `DEFAULT_OUTPUT_ROOT` | `Path('metric-results/input-length-rootkey')` |
| `DEFAULT_SPLITS` | `'val'` |
| `DEFAULT_TASKS` | `'node_config_qa'` |
| `DEFAULT_PRED_KEYS` | `'model-output,model_output,model-ouput'` |
| `DEFAULT_GOLD_KEY` | `'answer'` |
| `DEFAULT_PROGRESS_INTERVAL` | `500` |
| `DEFAULT_INPUT_LENGTH_THRESHOLDS` | `'4096,8192,16384,32768,65536,131072,262144,524288'` |
| `DEFAULT_PLOT_METRIC` | `'leaf_triple_f1'` |


## 输入与输出

**主要输出：**

- `per_file_input_length_rootkey.csv`
- `input_length_metrics.csv`、`input_length_rootkey_metrics.csv`、`top_level_key_input_length_metrics.csv`
- `input_length_rootkey_heatmap.svg`
- `summary.json`

**统计口径与异常：**

- 扫描文件数、模型错误数、解析/评估错误数和有效评估数应分开理解，指标分母以代码实际纳入的有效对象为准。
- 推理结果目录属于实验产物，不应覆盖 QA 数据源；改变预测字段名时需同步检查 `pred-keys`。


## 相关文档

- [analyze_qa_metric_factors.py](analyze_qa_metric_factors.md)
- [analyze_model_output_tokens.py](analyze_model_output_tokens.md)

[返回 inference 脚本索引](README.md)
