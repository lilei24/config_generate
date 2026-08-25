# batch_analyze_network_business_vllm.py

> 代码位置：[`scripts/batch_analyze_network_business_vllm.py`](../../scripts/batch_analyze_network_business_vllm.py)

## 功能与业务价值

调用 OpenAI-compatible vLLM 服务批量生成通信网络业务分析与 HTML 报告。

**业务价值：** 负责原始拓扑质量分析、配置生成 QA 构建以及模型辅助业务分析。

## 核心逻辑

1. 读取并校验脚本声明的输入数据。
2. 执行模块定义的核心转换或统计。
3. 将结构化结果写入输出目录，并保留异常信息供复核。

## 参数

| 参数 | 说明 |
|---|---|
| `dataset_root` | 原始数据集根目录，目录下应包含 train/val |
| `-h, --help` | 显示当前脚本的完整命令帮助后退出。 |
| `-o OUTPUT_ROOT, --output-root OUTPUT_ROOT` | JSON、HTML 和汇总文件的输出根目录 |
| `--split {train,val,all}` | 选择 train、val 或全部数据划分。 |
| `--base-url BASE_URL` | OpenAI-compatible 模型服务的 API 根地址。 |
| `--api-key API_KEY` | 模型服务 API Key；本地 vLLM 未鉴权时通常使用占位值。 |
| `--model MODEL` | 请求中传给模型服务或 OpenCode Provider 的模型标识。 |
| `--temperature TEMPERATURE` | 模型采样温度；数值越低，输出通常越确定。 |
| `--request-timeout REQUEST_TIMEOUT` | 单次请求超时秒数，默认: 1200.0 |
| `--retries RETRIES` | 请求或输出解析失败后的重试次数，默认: 1 |
| `--retry-wait-seconds RETRY_WAIT_SECONDS` | 一次请求失败后，到下一次重试前等待的秒数。 |
| `--wait-seconds WAIT_SECONDS` | 每个样本处理完成后的等待秒数 |
| `--progress-interval PROGRESS_INTERVAL` | 每处理指定数量的文件打印一次进度；0 表示关闭。 |
| `--limit LIMIT` | 只处理排序后的前 N 个文件，用于小规模测试 |
| `--max-config-interpretations MAX_CONFIG_INTERPRETATIONS` | 每个站点最多要求模型解读的代表性配置数，默认: 20 |
| `--enable-thinking` | 开启模型思考模式；默认关闭 |
| `--resume` | 跳过已经成功生成结构化分析结果的文件 |

参数表以当前代码的 `--help` 为准。路径参数均相对于运行命令所在目录解析。

### 关键默认值

| 常量 | 当前值 |
|---|---|
| `DEFAULT_DATASET_ROOT` | `'datasets'` |
| `DEFAULT_OUTPUT_ROOT` | `'network-business-analysis'` |
| `DEFAULT_BASE_URL` | `'http://localhost:8000/v1'` |
| `DEFAULT_API_KEY` | `'empty'` |
| `DEFAULT_MODEL` | `'qwen3-8b'` |
| `DEFAULT_SPLIT` | `'all'` |
| `DEFAULT_TEMPERATURE` | `0.2` |
| `DEFAULT_REQUEST_TIMEOUT` | `1200.0` |
| `DEFAULT_RETRIES` | `1` |
| `DEFAULT_RETRY_WAIT_SECONDS` | `5.0` |
| `DEFAULT_WAIT_SECONDS` | `0.0` |
| `DEFAULT_PROGRESS_INTERVAL` | `1` |
| `DEFAULT_MAX_CONFIG_INTERPRETATIONS` | `20` |
| `SUMMARY_FILE` | `'analysis_summary.json'` |
| `FAILURE_FILE` | `'analysis_failures.csv'` |
| `INDEX_FILE` | `'index.html'` |

## 运行方式

```bash
python scripts/batch_analyze_network_business_vllm.py --help
```

确认数据路径和输出路径后，可去掉 `--help` 并传入上表参数执行。

## 关键接口

| 接口 | 职责 |
|---|---|
| `import_openai (function)` | 核心内部接口 |
| `collect_files (function)` | 核心内部接口 |
| `compact_json (function)` | 核心内部接口 |
| `config_objects (function)` | 核心内部接口 |
| `device_name (function)` | 核心内部接口 |
| `extract_config_entries (function)` | 按配置顶层 Key 提取真实配置，并生成稳定的 JSON 路径引用。 |
| `config_catalog (function)` | 核心内部接口 |
| `build_user_prompt (function)` | 核心内部接口 |
| `strip_code_fence (function)` | 核心内部接口 |
| `parse_json_object (function)` | 核心内部接口 |
| `require_string (function)` | 核心内部接口 |
| `require_string_list (function)` | 核心内部接口 |
| `require_object_list (function)` | 核心内部接口 |
| `validate_analysis (function)` | 核心内部接口 |
| `request_analysis (function)` | 核心内部接口 |
| `graph_statistics (function)` | 核心内部接口 |
| 其他内部接口 | 另有 16 个辅助接口，详见源码。 |

## 输入、输出与口径

- 输入字段、候选筛选和异常状态以“核心逻辑”及源码校验条件为准。
- 统计脚本需区分扫描文件数、有效文件数和参与数值计算的样本数，避免分母混淆。
- 输出目录不会自动上传，也不应覆盖原始数据集。

[返回 通用数据分析与配置生成索引](README.md)
