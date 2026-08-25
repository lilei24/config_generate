# add_task_answers_to_results.py

> 代码位置：[`scripts/infer_eval/add_task_answers_to_results.py`](../../../scripts/infer_eval/add_task_answers_to_results.py)

## 功能与业务价值

按相同相对路径将标准 task_answer 补充到推理结果 JSON。

**业务价值：** 统一执行 vLLM/OpenCode 推理、错误记录、指标计算和 SwanLab 观测。

## 核心逻辑

1. 定义多个任务入口共享的数据结构、参数和校验规则。
2. 将任务差异封装为规格或回调，使批处理、错误处理和实验记录保持一致。
3. 由具体推理或评估入口导入，不建议作为最终业务命令直接运行。

## 参数

| 参数 | 说明 |
|---|---|
| `result_root` | 缺少 task_answer 的推理结果根目录，目录下包含 train/val |
| `answer_root` | 包含 task_answer 的标准答案根目录，目录下包含 train/val |
| `-h, --help` | 显示当前脚本的完整命令帮助后退出。 |
| `-o OUTPUT_ROOT, --output-root OUTPUT_ROOT` | 补全结果输出根目录，默认: /tmp/results_with_task_answer |
| `--split {train,val,all}` | 处理 train、val 或全部数据，默认: all |
| `--progress-interval PROGRESS_INTERVAL` | 每处理 N 个文件打印一次进度，0 表示关闭，默认: 100 |
| `--indent INDENT` | 输出 JSON 的缩进空格数。 |

参数表以当前代码的 `--help` 为准。路径参数均相对于运行命令所在目录解析。

### 关键默认值

| 常量 | 当前值 |
|---|---|
| `DEFAULT_OUTPUT_ROOT` | `'/tmp/results_with_task_answer'` |
| `DEFAULT_SPLIT` | `'all'` |
| `DEFAULT_PROGRESS_INTERVAL` | `100` |
| `SUMMARY_FILE` | `'add_task_answers_summary.json'` |
| `ISSUES_FILE` | `'add_task_answers_issues.jsonl'` |

## 运行方式

```bash
python scripts/infer_eval/add_task_answers_to_results.py --help
```

确认数据路径和输出路径后，可去掉 `--help` 并传入上表参数执行。

## 关键接口

| 接口 | 职责 |
|---|---|
| `load_json_object (function)` | 核心内部接口 |
| `write_json (function)` | 核心内部接口 |
| `append_issue (function)` | 核心内部接口 |
| `json_files (function)` | 核心内部接口 |
| `remove_stale_output (function)` | 核心内部接口 |
| `issue_record (function)` | 核心内部接口 |
| `run (function)` | 核心内部接口 |

## 输入、输出与口径

- 输入字段、候选筛选和异常状态以“核心逻辑”及源码校验条件为准。
- 推理结果以原答案文档为基础增加 `model-output` 和运行状态，错误原因不得静默丢弃。
- 评估时必须区分扫描样本、模型成功样本、结构可解析样本和实际参与指标平均的样本。
- SwanLab 是观测渠道，本地 CSV/JSON 才是可重复复核的指标结果。

[返回 批量推理与评估索引](README.md)
