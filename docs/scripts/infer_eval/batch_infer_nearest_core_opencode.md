# batch_infer_nearest_core_opencode.py

> 代码位置：[`scripts/infer_eval/batch_infer_nearest_core_opencode.py`](../../../scripts/infer_eval/batch_infer_nearest_core_opencode.py)

## 功能与业务价值

使用 OpenCode 批量推理 AP 到最近目标角色路径任务。

**业务价值：** 统一执行 vLLM/OpenCode 推理、错误记录、指标计算和 SwanLab 观测。

## 核心逻辑

1. 按 split 和文件名字典序发现任务 JSON，并支持断点跳过已有成功结果。
2. 通过任务规格构造 Prompt，调用 OpenCode，校验并解析模型 JSON。
3. 将 model-output、运行状态、耗时和错误原因写入与输入同名的结果文件，并打印批量进度。

## 参数

| 参数 | 说明 |
|---|---|
| `-h, --help` | 显示当前脚本的完整命令帮助后退出。 |
| `--hidden-root HIDDEN_ROOT` | without_answer 数据集根目录，默认: uplink_node_path_dataset/without_answer |
| `--answer-root ANSWER_ROOT` | with_answer 数据集根目录，默认: uplink_node_path_dataset/with_answer |
| `--output-root OUTPUT_ROOT` | 推理结果根目录，默认: opencode-results/uplink_node_path |
| `--split {train,val,all}` | 处理的数据划分，默认: val |
| `--progress-interval PROGRESS_INTERVAL` | 每处理 N 个文件打印进度，0 表示关闭，默认: 1 |
| `--limit LIMIT` | 只处理扫描顺序中的前 N 个 JSON |
| `--resume` | 断点续推：跳过已有成功结果，重新处理失败或损坏的结果 |
| `--indent INDENT` | 输出 JSON 的缩进空格数。 |
| `--opencode-command OPENCODE_COMMAND` | OpenCode 可执行文件名称或路径，默认: opencode |
| `--attach ATTACH` | 可选 OpenCode serve 地址；省略时每个样本直接运行 opencode |
| `--model MODEL` | 可选 OpenCode 模型，格式为 provider/model |
| `--agent AGENT` | OpenCode 使用的 Agent 名称；为空时使用默认 Agent。 |
| `--opencode-workdir OPENCODE_WORKDIR` | OpenCode 项目和工具工作目录，默认: opencode-harness-workspace |
| `--timeout-seconds TIMEOUT_SECONDS` | 每次 OpenCode 调用超时秒数，默认: 600.0 |
| `--retries RETRIES` | 首次调用失败后的重试次数，默认: 1 |
| `--dry-run` | 只扫描样本并打印 Prompt，不调用 OpenCode、不写结果 |

参数表以当前代码的 `--help` 为准。路径参数均相对于运行命令所在目录解析。

## 运行方式

```bash
python scripts/infer_eval/batch_infer_nearest_core_opencode.py --help
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
