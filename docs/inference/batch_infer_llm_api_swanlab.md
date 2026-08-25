# batch_infer_llm_api_swanlab.py

> 代码位置：[`inference/batch_infer_llm_api_swanlab.py`](../../inference/batch_infer_llm_api_swanlab.py)

## 功能与业务价值

**外部 LLM API 批量推理与 SwanLab 记录。** 面向项目外部 OpenAI-compatible API 执行配置生成，支持 system Prompt、Qwen thinking 开关和返回后等待。

**业务价值：** 在共享或限流 API 上复用本地 vLLM 实验口径，并通过请求间隔降低服务压力和限流风险。

## 核心逻辑

1. 用 system 与 user 两条 message 调用远端 Chat Completions。
2. 默认发送 `chat_template_kwargs.enable_thinking=false`；可显式关闭该额外参数以兼容不支持的服务。
3. 每次收到响应后按 `post-response-wait-seconds` 等待，再处理下一样本。
4. 逐样本解析、评估并写入本地结果，同时记录 SwanLab sample/eval 指标与表格。
5. 请求、读取和解析错误分别保留，便于统计外部服务可靠性。

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
| `--system-prompt` | 控制该脚本对应处理行为。 | 默认：`DEFAULT_SYSTEM_PROMPT` |
| `--progress-interval` | 每处理多少个文件打印一次进度；非正数通常表示关闭周期打印。 | 默认：`DEFAULT_PROGRESS_INTERVAL` |
| `--post-response-wait-seconds` | Wait N seconds after each processed sample before sending the next request. Default: 5. | 默认：`DEFAULT_POST_RESPONSE_WAIT_SECONDS` |
| `--limit` | 最多处理的文件数；`0` 表示不限制。 | 默认：`0` |
| `--no-disable-thinking-extra-body` | Do not send extra_body chat_template_kwargs.enable_thinking=false. | 开关参数 |
| `--swanlab-project` | SwanLab 项目名。 | 默认：`DEFAULT_SWANLAB_PROJECT` |
| `--swanlab-experiment` | SwanLab 实验名。 | 默认：`DEFAULT_SWANLAB_EXPERIMENT` |
| `--swanlab-mode` | SwanLab 运行模式，例如 `cloud` 或本地模式。 | 默认：`DEFAULT_SWANLAB_MODE` |
| `--eval-metric-mode` | 累计 eval 口径：`micro` 汇总计数后计算，`macro` 对有效样本指标求平均。 | 默认：`DEFAULT_EVAL_METRIC_MODE`；可选：`['micro', 'macro']` |
| `--sample-table-log-interval` | 每累计多少个样本重新上传一次样本表。 | 默认：`DEFAULT_SAMPLE_TABLE_LOG_INTERVAL` |

路径参数相对于执行命令时的当前工作目录解析；运行 `--help` 可查看代码中的即时说明。

### 关键默认值

| 常量 | 当前代码表达式 |
|---|---|
| `DEFAULT_BASE_URL` | `'http://10.246.114.119:9000/v1'` |
| `DEFAULT_API_KEY` | `'empty'` |
| `DEFAULT_MODEL` | `'Qwen-Qwen3_6-27B'` |
| `DEFAULT_TEMPERATURE` | `0.6` |
| `DEFAULT_OUTPUT_ROOT` | `Path('inference-qwen3_6-27b')` |
| `DEFAULT_SWANLAB_PROJECT` | `'config-generation'` |
| `DEFAULT_SWANLAB_EXPERIMENT` | `'qwen3_6-27b-api-inference'` |
| `DEFAULT_SWANLAB_MODE` | `'cloud'` |
| `DEFAULT_SYSTEM_PROMPT` | `'你是个智能助手'` |
| `DEFAULT_SAMPLE_TABLE_LOG_INTERVAL` | `50` |
| `DEFAULT_POST_RESPONSE_WAIT_SECONDS` | `5.0` |
| `DEFAULT_EVAL_METRIC_MODE` | `'micro'` |

## 运行方式

```bash
python inference/batch_infer_llm_api_swanlab.py --help
```

建议先用 `--limit` 小规模验证路径、服务和输出格式，再运行完整 split。

## 输入与输出

**主要输出：**

- `inference-qwen3_6-27b/<split>/<task>/**/*.json`（默认）：逐样本结果。
- SwanLab 记录配置、曲线和样本表。

**统计口径与异常：**

- 扫描文件数、模型错误数、解析/评估错误数和有效评估数应分开理解，指标分母以代码实际纳入的有效对象为准。
- 推理结果目录属于实验产物，不应覆盖 QA 数据源；改变预测字段名时需同步检查 `pred-keys`。

## 关键接口

| 接口 | 类型 | 职责 |
|---|---|---|
| `json_text` | function | 实现该脚本的核心处理步骤。 |
| `sample_metric` | function | 实现该脚本的核心处理步骤。 |
| `chat_completion` | function | 实现该脚本的核心处理步骤。 |
| `log_sample` | function | 实现该脚本的核心处理步骤。 |
| `log_running_eval` | function | 实现该脚本的核心处理步骤。 |
| `log_sample_table` | function | 实现该脚本的核心处理步骤。 |
| `run` | function | 实现该脚本的核心处理步骤。 |
| `parse_args` | function | 实现该脚本的核心处理步骤。 |
| `main` | function | 实现该脚本的核心处理步骤。 |

## 相关文档

- [batch_infer_qa.py](batch_infer_qa.md)
- [swanlab_utils.py](swanlab_utils.md)

[返回 inference 脚本索引](README.md)
