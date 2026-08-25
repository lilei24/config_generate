# batch_infer_llm_api_swanlab_mask_value.py

> 代码位置：[`inference/batch_infer_llm_api_swanlab_mask_value.py`](../../inference/batch_infer_llm_api_swanlab_mask_value.py)

## 功能与业务价值

**外部 API 的仅预测 Value 推理。** 将 Value 掩码任务接入外部 LLM API 与 SwanLab 实验流程。

**业务价值：** 用于在远端大模型上验证结构约束能否提升值预测质量，同时保持与本地服务一致的评价口径。

## 核心逻辑

1. 构造完整嵌套 Key 骨架并隐藏叶子值。
2. 复用外部 API 的 system message、thinking 控制、请求等待和 SwanLab 日志。
3. 命令行参数与 `batch_infer_llm_api_swanlab.py` 一致。

## 代码实现说明

- 当前文件组合两个已有能力：由 `batch_infer_qa_mask_value.py` 提供 Key 骨架 Prompt，由 `batch_infer_llm_api_swanlab.py` 提供外部 API 调用和实验记录。
- 叶子值全部隐藏，数组长度和嵌套 Key 保留；回答仍解析为完整 JSON，并使用相同的字段路径、叶子三元组和值准确率指标。
- system Prompt、远端 thinking 参数兼容开关、响应后等待、错误分类、micro/macro 模式和 SwanLab 表格均继承外部 API 版本。

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

## 运行方式

```bash
python inference/batch_infer_llm_api_swanlab_mask_value.py --help
```

建议先用 `--limit` 小规模验证路径、服务和输出格式，再运行完整 split。

## 输入与输出

**主要输出：**

- 输出结构与外部 API SwanLab 推理脚本相同。

**统计口径与异常：**

- 扫描文件数、模型错误数、解析/评估错误数和有效评估数应分开理解，指标分母以代码实际纳入的有效对象为准。
- 推理结果目录属于实验产物，不应覆盖 QA 数据源；改变预测字段名时需同步检查 `pred-keys`。


## 相关文档

- [batch_infer_llm_api_swanlab.py](batch_infer_llm_api_swanlab.md)
- [batch_infer_qa_mask_value.py](batch_infer_qa_mask_value.md)

[返回 inference 脚本索引](README.md)
