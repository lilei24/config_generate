# batch_infer_qa.py

> 代码位置：[`inference/batch_infer_qa.py`](../../inference/batch_infer_qa.py)

## 功能与业务价值

**OpenAI-compatible 批量配置生成推理。** 批量读取 QA 样本，通过 vLLM 或其他 OpenAI Chat Completions 兼容服务生成缺失配置，并将成功结果与失败原因逐文件落盘。

**业务价值：** 把模型服务收敛为 `base_url + api_key + model + messages` 接口，使同一套数据和 Prompt 可在不同部署模型间复用。

## 核心逻辑

1. 按任务目录和 JSON 文件名字典序扫描样本，可通过 `limit` 截断调试。
2. 校验 `prompt`、`input`、`output`，根据答案顶层 Key 注入可选结构提示并构造用户 Prompt。
3. 调用 Chat Completions；默认通过 `extra_body` 关闭 Qwen thinking，并清理残留 `<think>` 内容。
4. 尽力把模型文本解析为 JSON；解析失败时保留原文和解析错误，请求失败写入 `failures.jsonl`。
5. 结果保持 `split/task/相对文件名` 目录结构，并保存 `structure-hints`、`model-output` 和 `answer`。

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

路径参数相对于执行命令时的当前工作目录解析；运行 `--help` 可查看代码中的即时说明。

### 关键默认值

| 常量 | 当前代码表达式 |
|---|---|
| `DEFAULT_QA_ROOT` | `Path('520QA')` |
| `DEFAULT_OUTPUT_ROOT` | `Path('inference-results')` |
| `DEFAULT_BASE_URL` | `'http://localhost:8000/v1'` |
| `DEFAULT_API_KEY` | `'empty'` |
| `DEFAULT_MODEL` | `'qwen3-8b'` |
| `DEFAULT_TEMPERATURE` | `0.2` |
| `DEFAULT_PROGRESS_INTERVAL` | `50` |
| `TOP_LEVEL_KEY_STRUCTURE_HINTS` | `{}` |

## 运行方式

```bash
python inference/batch_infer_qa.py --help
```

建议先用 `--limit` 小规模验证路径、服务和输出格式，再运行完整 split。

## 输入与输出

**主要输出：**

- `<output-root>/<split>/<task>/**/*.json`：逐样本推理结果。
- `<output-root>/<split>/failures.jsonl`：读取或调用失败记录。

**统计口径与异常：**

- 扫描文件数、模型错误数、解析/评估错误数和有效评估数应分开理解，指标分母以代码实际纳入的有效对象为准。
- 推理结果目录属于实验产物，不应覆盖 QA 数据源；改变预测字段名时需同步检查 `pred-keys`。

## 关键接口

| 接口 | 类型 | 职责 |
|---|---|---|
| `import_openai_client` | function | 实现该脚本的核心处理步骤。 |
| `iter_qa_files` | function | 实现该脚本的核心处理步骤。 |
| `load_qa` | function | 实现该脚本的核心处理步骤。 |
| `output_top_level_keys` | function | 只读取监督答案的顶层 Key，不把答案内部结构或 value 放入 Prompt。 |
| `structure_hints_value_for_keys` | function | 返回当前目标 Key 对应的结构化常见配置；未配置时返回 None。 |
| `structure_hints_for_keys` | function | 把结构化常见配置格式化为插入 Prompt 的 JSON 文本。 |
| `structure_hints_for_sample` | function | 提取当前样本实际使用的结构提示，供结果 JSON 直接保存。 |
| `build_user_prompt` | function | 实现该脚本的核心处理步骤。 |
| `strip_think` | function | 实现该脚本的核心处理步骤。 |
| `strip_markdown_fence` | function | 实现该脚本的核心处理步骤。 |
| `parse_model_output` | function | Best-effort parse model output so result JSON is easy to inspect. |
| `chat_completion` | function | 实现该脚本的核心处理步骤。 |
| `result_path` | function | 实现该脚本的核心处理步骤。 |
| `write_json` | function | 实现该脚本的核心处理步骤。 |
| `append_jsonl` | function | 实现该脚本的核心处理步骤。 |
| `print_progress` | function | 实现该脚本的核心处理步骤。 |
| `run` | function | 实现该脚本的核心处理步骤。 |
| `parse_args` | function | 实现该脚本的核心处理步骤。 |
| `main` | function | 实现该脚本的核心处理步骤。 |

## 相关文档

- [batch_infer_qa_mask_value.py](batch_infer_qa_mask_value.md)
- [batch_infer_qa_swanlab.py](batch_infer_qa_swanlab.md)
- [metric.py](metric.md)

[返回 inference 脚本索引](README.md)
