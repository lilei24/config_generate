# batch_infer_shortest_path_opencode.py

> 代码位置：[`scripts/infer_eval/batch_infer_shortest_path_opencode.py`](../../../scripts/infer_eval/batch_infer_shortest_path_opencode.py)

## 功能与业务价值

批量调用 OpenCode，完成两节点全部最短路径任务。

脚本直接扫描 shortest_path_dataset/without_answer/{split} 下的 JSON，使用
包含 ``.json`` 后缀的文件名作为站点名称，并提取源节点 ID 和目标节点 ID
构造提示词。OpenCode 的回答不会写回标准答案目录，而是复制对应的 with_answer
样本，再在输出文件中增加 ``model-output`` 和 ``opencode-run`` 字段，方便
后续与 ``task_answer`` 对照评估。

OpenCode 使用 ``--format json`` 时返回的是 JSON 事件流。脚本会保留原始事件，
提取最后一个可解析的 assistant JSON，并校验最短路径回答的基本结构。

**业务价值：** 统一执行 vLLM/OpenCode 推理、错误记录、指标计算和 SwanLab 观测。

## 核心逻辑

1. 按 split 和文件名字典序发现任务 JSON，并支持断点跳过已有成功结果。
2. 通过任务规格构造 Prompt，调用 OpenCode，校验并解析模型 JSON。
3. 将 model-output、运行状态、耗时和错误原因写入与输入同名的结果文件，并打印批量进度。

## 参数

| 参数 | 说明 |
|---|---|
| `-h, --help` | 显示当前脚本的完整命令帮助后退出。 |
| `--hidden-root HIDDEN_ROOT` | 隐藏答案数据集根目录，默认: shortest_path_dataset/without_answer |
| `--answer-root ANSWER_ROOT` | 标准答案数据集根目录，默认: shortest_path_dataset/with_answer |
| `--output-root OUTPUT_ROOT` | 推理结果根目录，默认: opencode-results/shortest_path |
| `--split {train,val,all}` | 数据划分；all 会联合查找 train 和 val，默认: val |
| `--opencode-command OPENCODE_COMMAND` | OpenCode 可执行文件名称或路径，默认: opencode |
| `--attach ATTACH` | 可选的 OpenCode serve 地址，例如 http://localhost:4096 |
| `--model MODEL` | 可选模型，格式为 provider/model；省略时使用 OpenCode 默认模型 |
| `--agent AGENT` | 可选的 OpenCode Agent 名称；省略时使用 OpenCode 当前默认 Agent |
| `--opencode-workdir OPENCODE_WORKDIR` | 隔离的 OpenCode 工作目录，默认: opencode-harness-workspace |
| `--timeout-seconds TIMEOUT_SECONDS` | 每次调用超时时间，默认: 600 秒 |
| `--retries RETRIES` | 失败后的重试次数，默认: 1 |
| `--progress-interval PROGRESS_INTERVAL` | 每处理多少个 JSON 打印进度，默认: 1 |
| `--limit LIMIT` | 只处理扫描顺序中的前 N 个 JSON，适合小规模联调 |
| `--resume` | 断点续推：跳过已有成功结果，重新处理失败或损坏的结果 |
| `--dry-run` | 只扫描 JSON 并打印提示词，不调用 OpenCode、不写结果 |
| `--indent INDENT` | 输出 JSON 缩进，默认: 2 |

参数表以当前代码的 `--help` 为准。路径参数均相对于运行命令所在目录解析。

### 关键默认值

| 常量 | 当前值 |
|---|---|
| `DEFAULT_HIDDEN_ROOT` | `'shortest_path_dataset/without_answer'` |
| `DEFAULT_ANSWER_ROOT` | `'shortest_path_dataset/with_answer'` |
| `DEFAULT_OUTPUT_ROOT` | `'opencode-results/shortest_path'` |
| `DEFAULT_WORKDIR` | `'opencode-harness-workspace'` |
| `DEFAULT_SPLIT` | `'val'` |
| `DEFAULT_TIMEOUT_SECONDS` | `600.0` |
| `DEFAULT_RETRIES` | `1` |
| `DEFAULT_PROGRESS_INTERVAL` | `1` |

## 运行方式

```bash
python scripts/infer_eval/batch_infer_shortest_path_opencode.py --help
```

确认数据路径和输出路径后，可去掉 `--help` 并传入上表参数执行。

## 关键接口

| 接口 | 职责 |
|---|---|
| `SamplePaths (class)` | 核心内部接口 |
| `OpenCodeResult (class)` | 核心内部接口 |
| `load_json_object (function)` | 核心内部接口 |
| `has_successful_result (function)` | 仅将状态成功且包含结构化模型回答的结果视为已完成。 |
| `write_json (function)` | 核心内部接口 |
| `collect_sample_paths (function)` | 按 split 顺序和相对路径字典序收集全部任务样本。 |
| `build_prompt (function)` | 核心内部接口 |
| `decode_json_stream (function)` | 解析由多个 JSON 值组成的 OpenCode stdout，兼容单行和格式化事件。 |
| `strip_markdown_code_fence (function)` | 核心内部接口 |
| `parse_json_object_from_text (function)` | 核心内部接口 |
| `validate_shortest_path_answer (function)` | 核心内部接口 |
| `validate_path_metadata_sequences (function)` | 核心内部接口 |
| `extract_answer_and_session (function)` | 核心内部接口 |
| `build_opencode_command (function)` | 核心内部接口 |
| `subprocess_output_text (function)` | 统一 subprocess 正常返回和超时异常中的文本类型。 |
| `invoke_opencode (function)` | 核心内部接口 |
| 其他内部接口 | 另有 3 个辅助接口，详见源码。 |

## 输入、输出与口径

- 输入字段、候选筛选和异常状态以“核心逻辑”及源码校验条件为准。
- 推理结果以原答案文档为基础增加 `model-output` 和运行状态，错误原因不得静默丢弃。
- 评估时必须区分扫描样本、模型成功样本、结构可解析样本和实际参与指标平均的样本。
- SwanLab 是观测渠道，本地 CSV/JSON 才是可重复复核的指标结果。

[返回 批量推理与评估索引](README.md)
