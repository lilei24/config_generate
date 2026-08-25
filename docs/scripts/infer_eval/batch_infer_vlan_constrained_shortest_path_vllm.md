# batch_infer_vlan_constrained_shortest_path_vllm.py

> 代码位置：[`scripts/infer_eval/batch_infer_vlan_constrained_shortest_path_vllm.py`](../../../scripts/infer_eval/batch_infer_vlan_constrained_shortest_path_vllm.py)

## 功能与业务价值

使用 OpenAI-compatible vLLM 批量推理 VLAN 约束最短路径任务。

**业务价值：** 统一执行 vLLM/OpenCode 推理、错误记录、指标计算和 SwanLab 观测。

## 核心逻辑

1. 按 split 和文件名字典序发现任务 JSON，并支持断点跳过已有成功结果。
2. 通过任务规格构造 Prompt，调用 OpenAI-compatible vLLM，校验并解析模型 JSON。
3. 将 model-output、运行状态、耗时和错误原因写入与输入同名的结果文件，并打印批量进度。

## 参数

| 参数 | 说明 |
|---|---|
| `-h, --help` | 显示当前脚本的完整命令帮助后退出。 |
| `--hidden-root HIDDEN_ROOT` | without_answer 数据集根目录，默认: vlan_constrained_shortest_path_dataset/without_answer |
| `--answer-root ANSWER_ROOT` | with_answer 数据集根目录，默认: vlan_constrained_shortest_path_dataset/with_answer |
| `--output-root OUTPUT_ROOT` | 推理结果根目录，默认: vllm-results/vlan_constrained_shortest_path |
| `--split {train,val,all}` | 处理的数据划分，默认: val |
| `--progress-interval PROGRESS_INTERVAL` | 每处理 N 个文件打印进度，0 表示关闭，默认: 1 |
| `--limit LIMIT` | 只处理扫描顺序中的前 N 个 JSON |
| `--resume` | 断点续推：跳过已有成功结果，重新处理失败或损坏的结果 |
| `--indent INDENT` | 输出 JSON 的缩进空格数。 |
| `--base-url BASE_URL` | OpenAI-compatible 模型服务的 API 根地址。 |
| `--api-key API_KEY` | 模型服务 API Key；本地 vLLM 未鉴权时通常使用占位值。 |
| `--model MODEL` | 请求中传给模型服务或 OpenCode Provider 的模型标识。 |
| `--temperature TEMPERATURE` | 模型采样温度；数值越低，输出通常越确定。 |
| `--request-timeout REQUEST_TIMEOUT` | 单次 API 请求超时秒数，默认: 600.0 |
| `--retries RETRIES` | 首次请求失败后的重试次数，默认: 1 |
| `--retry-wait-seconds RETRY_WAIT_SECONDS` | 一次请求失败后，到下一次重试前等待的秒数。 |
| `--wait-seconds WAIT_SECONDS` | 每个样本处理完成后等待秒数，默认: 0.0 |
| `--enable-thinking` | 开启模型思考模式；默认关闭 |

参数表以当前代码的 `--help` 为准。路径参数均相对于运行命令所在目录解析。

## 运行方式

```bash
python scripts/infer_eval/batch_infer_vlan_constrained_shortest_path_vllm.py --help
```

确认数据路径和输出路径后，可去掉 `--help` 并传入上表参数执行。

## 关键接口

该入口主要通过导入公共框架并调用 `main()` 完成工作。

## 输入、输出与口径

- 输入字段、候选筛选和异常状态以“核心逻辑”及源码校验条件为准。
- 推理结果以原答案文档为基础增加 `model-output` 和运行状态，错误原因不得静默丢弃。
- 评估时必须区分扫描样本、模型成功样本、结构可解析样本和实际参与指标平均的样本。
- SwanLab 是观测渠道，本地 CSV/JSON 才是可重复复核的指标结果。

[返回 批量推理与评估索引](README.md)
