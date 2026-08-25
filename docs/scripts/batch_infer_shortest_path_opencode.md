# batch_infer_shortest_path_opencode.py

> 代码位置：[`scripts/batch_infer_shortest_path_opencode.py`](../../scripts/batch_infer_shortest_path_opencode.py)

## 功能与业务价值

兼容入口：请优先使用 scripts/infer_eval 下的新版脚本。

**业务价值：** 负责原始拓扑质量分析、配置生成 QA 构建以及模型辅助业务分析。

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

## 运行方式

```bash
python scripts/batch_infer_shortest_path_opencode.py --help
```

确认数据路径和输出路径后，可去掉 `--help` 并传入上表参数执行。

## 关键接口

该入口主要通过导入公共框架并调用 `main()` 完成工作。

## 输入、输出与口径

- 输入字段、候选筛选和异常状态以“核心逻辑”及源码校验条件为准。
- 统计脚本需区分扫描文件数、有效文件数和参与数值计算的样本数，避免分母混淆。
- 输出目录不会自动上传，也不应覆盖原始数据集。

[返回 通用数据分析与配置生成索引](README.md)
