# batch_infer_qa_swanlab.py

> 代码位置：[`inference/batch_infer_qa_swanlab.py`](../../inference/batch_infer_qa_swanlab.py)

## 功能与业务价值

**带 SwanLab 记录的批量推理。** 在标准 OpenAI-compatible 推理流程中计算单样本指标，并向 SwanLab 记录 sample 曲线、运行中 eval 均值和样本表格。

**业务价值：** 让模型版本、参数、逐样本质量和累计效果进入同一实验，支持可复现实验比较和异常定位。

## 核心逻辑

1. 复用标准 QA Prompt、模型调用和本地结果文件格式。
2. 模型结果可解析时立即调用 `metric.evaluate_json` 计算九项核心数值。
3. `sample/*` 记录当前样本；`eval/*` 按 `micro` 或 `macro` 模式记录截至当前 step 的累计指标。
4. 按配置间隔上传包含文件名、Prompt、Input、预测、答案、返回状态和单样本指标的 SwanLab 表格。
5. 解析失败视为模型返回失败，保留错误原因，但不将无效结构加入正常评估累计。

## 参数

| 参数 | 说明 | 默认值或约束 |
|---|---|---|
| `--qa-root` | QA 数据根目录，用于读取 prompt、input、output 或关联同名样本。 | 默认：`DEFAULT_QA_ROOT` |
| `--output-root` | 本脚本产物输出目录。 | 默认：`DEFAULT_OUTPUT_ROOT` |
| `--split` | 单个数据划分，例如 `train` 或 `val`。 | 默认：`'train'` |
| `--tasks` | 逗号分隔的任务目录，例如 `node_config_qa,device_config_qa`。 | 默认：`'device_config_qa,node_config_qa'` |
| `--base-url` | OpenAI-compatible Chat Completions 服务地址。 | 默认：`DEFAULT_BASE_URL` |
| `--api-key` | API 密钥；本地 vLLM 通常可使用占位值。 | 默认：`DEFAULT_API_KEY` |
| `--model` | 服务端暴露的模型名称，必须与部署配置一致。 | 默认：`DEFAULT_MODEL` |
| `--temperature` | 采样温度。 | 默认：`DEFAULT_TEMPERATURE` |
| `--progress-interval` | 每处理多少个文件打印一次进度；非正数通常表示关闭周期打印。 | 默认：`DEFAULT_PROGRESS_INTERVAL` |
| `--limit` | 最多处理的文件数；`0` 表示不限制。 | 默认：`0` |
| `--enable-thinking` | 启用 Qwen thinking；默认关闭 thinking。 | 开关参数 |
| `--swanlab-project` | SwanLab 项目名。 | 默认：`DEFAULT_SWANLAB_PROJECT` |
| `--swanlab-experiment` | SwanLab 实验名。 | 默认：`DEFAULT_SWANLAB_EXPERIMENT` |
| `--swanlab-mode` | SwanLab 运行模式，例如 `cloud` 或本地模式。 | 默认：`DEFAULT_SWANLAB_MODE` |
| `--eval-metric-mode` | 累计 eval 口径：`micro` 汇总计数后计算，`macro` 对有效样本指标求平均。 | 默认：`DEFAULT_EVAL_METRIC_MODE`；可选：`['micro', 'macro']` |
| `--sample-table-log-interval` | 每累计多少个样本重新上传一次样本表。 | 默认：`DEFAULT_SAMPLE_TABLE_LOG_INTERVAL` |

路径参数相对于执行命令时的当前工作目录解析；运行 `--help` 可查看代码中的即时说明。

### 关键默认值

| 常量 | 当前代码表达式 |
|---|---|
| `DEFAULT_SWANLAB_PROJECT` | `'config-generation'` |
| `DEFAULT_SWANLAB_EXPERIMENT` | `'qwen3-8b-inference'` |
| `DEFAULT_SWANLAB_MODE` | `'cloud'` |
| `DEFAULT_SAMPLE_TABLE_LOG_INTERVAL` | `50` |
| `DEFAULT_EVAL_METRIC_MODE` | `'micro'` |

## 运行方式

```bash
python inference/batch_infer_qa_swanlab.py --help
```

建议先用 `--limit` 小规模验证路径、服务和输出格式，再运行完整 split。

## 输入与输出

**主要输出：**

- 本地 JSON 与失败日志同标准推理。
- SwanLab 实验包含运行参数、sample/eval 曲线和周期性样本表。

**统计口径与异常：**

- 扫描文件数、模型错误数、解析/评估错误数和有效评估数应分开理解，指标分母以代码实际纳入的有效对象为准。
- 推理结果目录属于实验产物，不应覆盖 QA 数据源；改变预测字段名时需同步检查 `pred-keys`。

## 关键接口

| 接口 | 类型 | 职责 |
|---|---|---|
| `json_text` | function | 实现该脚本的核心处理步骤。 |
| `sample_metric` | function | 实现该脚本的核心处理步骤。 |
| `log_sample` | function | 实现该脚本的核心处理步骤。 |
| `log_running_eval` | function | 实现该脚本的核心处理步骤。 |
| `log_sample_table` | function | 实现该脚本的核心处理步骤。 |
| `run` | function | 实现该脚本的核心处理步骤。 |
| `parse_args` | function | 实现该脚本的核心处理步骤。 |
| `main` | function | 实现该脚本的核心处理步骤。 |

## 相关文档

- [batch_infer_qa.py](batch_infer_qa.md)
- [swanlab_utils.py](swanlab_utils.md)
- [metric.py](metric.md)

[返回 inference 脚本索引](README.md)
