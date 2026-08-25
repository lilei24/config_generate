# analyze_shortest_path_inference_trend.py

> 代码位置：[`scripts/infer_eval/analyze_shortest_path_inference_trend.py`](../../../scripts/infer_eval/analyze_shortest_path_inference_trend.py)

## 功能与业务价值

按推理顺序分析最短路径任务指标及核心样本难度因素。

**业务价值：** 统一执行 vLLM/OpenCode 推理、错误记录、指标计算和 SwanLab 观测。

## 核心逻辑

1. 按 split 递归读取 JSON，并将坏 JSON、缺失字段和类型异常分开计数。
2. 依据模块定义的统计口径提取字段或构造无向图，完成逐文件计算。
3. 聚合全局及分组结果，输出 CSV/JSON/SVG 等可复核产物并打印进度。

## 参数

| 参数 | 说明 |
|---|---|
| `result_path` | 包含 task_answer 和 model-output 的结果文件或目录 |
| `-h, --help` | 显示当前脚本的完整命令帮助后退出。 |
| `--output-dir OUTPUT_DIR` | 分析结果目录，默认: vllm-results/shortest_path-trend-analysis |
| `--split {train,val,all}` | 分析的数据划分，默认: val |
| `--window-size WINDOW_SIZE` | 每组包含的连续推理样本数，默认: 100 |
| `--focus-metric {path_length_accuracy,path_valid_rate,path_precision,path_recall,path_f1,path_exact_match_rate}` | 趋势摘要重点分析的指标，默认: path_f1 |
| `--progress-interval PROGRESS_INTERVAL` | 每处理 N 个文件打印进度，0 表示关闭，默认: 100 |

参数表以当前代码的 `--help` 为准。路径参数均相对于运行命令所在目录解析。

### 关键默认值

| 常量 | 当前值 |
|---|---|
| `DEFAULT_RESULT_PATH` | `'vllm-results/shortest_path'` |
| `DEFAULT_OUTPUT_DIR` | `'vllm-results/shortest_path-trend-analysis'` |
| `DEFAULT_SPLIT` | `'val'` |
| `DEFAULT_WINDOW_SIZE` | `100` |
| `DEFAULT_PROGRESS_INTERVAL` | `100` |
| `DEFAULT_FOCUS_METRIC` | `'path_f1'` |
| `FACTOR_NAMES` | `('input_context_chars', 'node_count', 'link_count', 'gold_path_length', 'gold_path_count')` |

## 运行方式

```bash
python scripts/infer_eval/analyze_shortest_path_inference_trend.py --help
```

确认数据路径和输出路径后，可去掉 `--help` 并传入上表参数执行。

## 关键接口

| 接口 | 职责 |
|---|---|
| `write_csv (function)` | 核心内部接口 |
| `count_list (function)` | 核心内部接口 |
| `is_model_success (function)` | 核心内部接口 |
| `context_character_count (function)` | 计算实际任务上下文的紧凑 JSON 字符数，不包含答案和推理结果。 |
| `extract_factors (function)` | 核心内部接口 |
| `build_sample_rows (function)` | 核心内部接口 |
| `build_window_rows (function)` | 核心内部接口 |
| `build_summary (function)` | 核心内部接口 |
| `plot_trends (function)` | 核心内部接口 |

## 输入、输出与口径

- 输入字段、候选筛选和异常状态以“核心逻辑”及源码校验条件为准。
- 推理结果以原答案文档为基础增加 `model-output` 和运行状态，错误原因不得静默丢弃。
- 评估时必须区分扫描样本、模型成功样本、结构可解析样本和实际参与指标平均的样本。
- SwanLab 是观测渠道，本地 CSV/JSON 才是可重复复核的指标结果。

[返回 批量推理与评估索引](README.md)
