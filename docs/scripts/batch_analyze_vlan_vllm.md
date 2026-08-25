# batch_analyze_vlan_vllm.py

> 代码位置：[`scripts/batch_analyze_vlan_vllm.py`](../../scripts/batch_analyze_vlan_vllm.py)

## 功能与业务价值

使用 OpenAI-compatible vLLM 服务逐文件分析原始拓扑中的 VLAN 情况。

**业务价值：** 负责原始拓扑质量分析、配置生成 QA 构建以及模型辅助业务分析。

## 核心逻辑

1. 读取并校验脚本声明的输入数据。
2. 执行模块定义的核心转换或统计。
3. 将结构化结果写入输出目录，并保留异常信息供复核。

## 参数

| 参数 | 说明 |
|---|---|
| `dataset_root` | 原始数据集根目录，目录下应包含 train/val，默认: datasets |
| `-h, --help` | 显示当前脚本的完整命令帮助后退出。 |
| `-o OUTPUT_ROOT, --output-root OUTPUT_ROOT` | 逐文件分析结果根目录，默认: vlan-llm-analysis |
| `--split {train,val,all}` | 处理的数据划分，默认: all |
| `--base-url BASE_URL` | OpenAI-compatible 模型服务的 API 根地址。 |
| `--api-key API_KEY` | 模型服务 API Key；本地 vLLM 未鉴权时通常使用占位值。 |
| `--model MODEL` | 请求中传给模型服务或 OpenCode Provider 的模型标识。 |
| `--temperature TEMPERATURE` | 模型采样温度，默认: 0.2 |
| `--request-timeout REQUEST_TIMEOUT` | 单次 API 请求超时秒数，默认: 600.0 |
| `--retries RETRIES` | 首次请求失败后的重试次数，默认: 1 |
| `--retry-wait-seconds RETRY_WAIT_SECONDS` | 请求重试前等待秒数，默认: 5.0 |
| `--wait-seconds WAIT_SECONDS` | 每个样本请求完成后等待秒数，默认: 0.0 |
| `--progress-interval PROGRESS_INTERVAL` | 每处理 N 个文件打印进度，0 表示关闭，默认: 1 |
| `--enable-thinking` | 开启模型思考模式；默认通过 chat_template_kwargs 关闭 |
| `--skip-existing` | 结果文件已存在时跳过；默认固定覆盖 |

参数表以当前代码的 `--help` 为准。路径参数均相对于运行命令所在目录解析。

### 关键默认值

| 常量 | 当前值 |
|---|---|
| `DEFAULT_DATASET_ROOT` | `'datasets'` |
| `DEFAULT_OUTPUT_ROOT` | `'vlan-llm-analysis'` |
| `DEFAULT_BASE_URL` | `'http://localhost:8000/v1'` |
| `DEFAULT_API_KEY` | `'empty'` |
| `DEFAULT_MODEL` | `'qwen3-8b'` |
| `DEFAULT_SPLIT` | `'all'` |
| `DEFAULT_TEMPERATURE` | `0.2` |
| `DEFAULT_REQUEST_TIMEOUT` | `600.0` |
| `DEFAULT_RETRIES` | `1` |
| `DEFAULT_RETRY_WAIT_SECONDS` | `5.0` |
| `DEFAULT_WAIT_SECONDS` | `0.0` |
| `DEFAULT_PROGRESS_INTERVAL` | `1` |
| `SUMMARY_FILE` | `'vlan_llm_analysis_summary.json'` |
| `FAILURE_FILE` | `'vlan_llm_analysis_failures.csv'` |

## 运行方式

```bash
python scripts/batch_analyze_vlan_vllm.py --help
```

确认数据路径和输出路径后，可去掉 `--help` 并传入上表参数执行。

## 关键接口

| 接口 | 职责 |
|---|---|
| `import_openai (function)` | 核心内部接口 |
| `iter_json_files (function)` | 核心内部接口 |
| `format_model_output (function)` | 按非空行保存自然语言回复，避免 JSON 字符串中出现大量转义换行。 |
| `build_user_prompt (function)` | 核心内部接口 |
| `request_analysis (function)` | 核心内部接口 |
| `write_json_atomic (function)` | 核心内部接口 |
| `make_error_result (function)` | 核心内部接口 |
| `process_file (function)` | 核心内部接口 |
| `write_failures (function)` | 核心内部接口 |
| `run (function)` | 核心内部接口 |

## 输入、输出与口径

- 输入字段、候选筛选和异常状态以“核心逻辑”及源码校验条件为准。
- 统计脚本需区分扫描文件数、有效文件数和参与数值计算的样本数，避免分母混淆。
- 输出目录不会自动上传，也不应覆盖原始数据集。

[返回 通用数据分析与配置生成索引](README.md)
