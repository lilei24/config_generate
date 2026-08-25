# evaluate_shortest_path_results.py

> 代码位置：[`scripts/infer_eval/evaluate_shortest_path_results.py`](../../../scripts/infer_eval/evaluate_shortest_path_results.py)

## 功能与业务价值

评价单个或一批最短路径推理结果，并将指标记录到 SwanLab。

**业务价值：** 统一执行 vLLM/OpenCode 推理、错误记录、指标计算和 SwanLab 观测。

## 核心逻辑

1. 读取同一结果 JSON 中的 task_answer 与 model-output，错误样本单独识别。
2. 按任务语义规范化路径或集合，计算每样本指标和截至当前样本的平均指标。
3. 输出逐文件指标、汇总结果，并可将曲线与样本表记录到 SwanLab。

## 指标口径

| 指标 | 含义 |
|---|---|
| `path_length_accuracy` | 预测最短跳数是否与标准答案一致。 |
| `path_valid_rate` | 预测路径中拓扑连通、方向正确且长度满足要求的路径比例。 |
| `path_precision` | 预测路径集合中属于标准答案集合的比例，反映误报。 |
| `path_recall` | 标准答案路径集合被模型找回的比例，反映漏报。 |
| `path_f1` | 路径 Precision 与 Recall 的调和平均。 |
| `path_exact_match_rate` | 跳数、路径集合及必要附加字段全部正确的样本命中率。 |
| `role_accuracy` | 预测路径对应角色序列与节点真实 DEVICEROLE 的一致率。 |
| `device_name_accuracy` | 预测路径对应设备名序列与节点真实 NAME 的一致率。 |

脚本先计算单样本指标，再对参与评估的样本做算术平均；模型运行错误或输出结构错误的处理以代码中的有效样本判定为准。

## 参数

| 参数 | 说明 |
|---|---|
| `result_path` | 一个同时包含 task_answer 和 model-output 的结果 JSON；也可传入结果根目录进行批量评价，默认: vllm-results/shortest_path |
| `-h, --help` | 显示当前脚本的完整命令帮助后退出。 |
| `--output-dir OUTPUT_DIR` | 评价结果目录，默认: vllm-results/shortest_path-evaluation |
| `--split {train,val,all}` | 评价的数据划分，默认: val |
| `--progress-interval PROGRESS_INTERVAL` | 每处理 N 个文件打印进度，0 表示关闭，默认: 100 |
| `--swanlab-project SWANLAB_PROJECT` | SwanLab 项目名称，默认: topology-shortest-path |
| `--swanlab-experiment SWANLAB_EXPERIMENT` | SwanLab 实验名称，默认: shortest-path-evaluation |
| `--swanlab-mode SWANLAB_MODE` | SwanLab 运行模式，默认: cloud |
| `--swanlab-color-seed SWANLAB_COLOR_SEED` | 根据实验名生成确定性颜色的固定随机种子，默认: 20260727 |
| `--swanlab-color-key SWANLAB_COLOR_KEY` | 实验颜色区分键；默认使用 result_path，不同模型可显式传入不同键 |
| `--disable-swanlab` | 只生成本地评价文件，不初始化和上传 SwanLab |

参数表以当前代码的 `--help` 为准。路径参数均相对于运行命令所在目录解析。

### 关键默认值

| 常量 | 当前值 |
|---|---|
| `DEFAULT_RESULT_PATH` | `'vllm-results/shortest_path'` |
| `DEFAULT_OUTPUT_DIR` | `'vllm-results/shortest_path-evaluation'` |
| `DEFAULT_SPLIT` | `'val'` |
| `DEFAULT_PROGRESS_INTERVAL` | `100` |
| `DEFAULT_SWANLAB_PROJECT` | `'topology-shortest-path'` |
| `DEFAULT_SWANLAB_EXPERIMENT` | `'shortest-path-evaluation'` |
| `DEFAULT_SWANLAB_MODE` | `'cloud'` |
| `METRIC_NAMES` | `('path_length_accuracy', 'path_valid_rate', 'path_precision', 'path_recall', 'path_f1', 'path_exact_match_rate', 'role_accuracy', 'device_name_accuracy')` |

## 运行方式

```bash
python scripts/infer_eval/evaluate_shortest_path_results.py --help
```

确认数据路径和输出路径后，可去掉 `--help` 并传入上表参数执行。

## 关键接口

| 接口 | 职责 |
|---|---|
| `SampleMetrics (class)` | 核心内部接口 |
| `import_swanlab (function)` | 核心内部接口 |
| `load_json_object (function)` | 核心内部接口 |
| `get_device (function)` | 核心内部接口 |
| `build_node_metadata (function)` | 核心内部接口 |
| `build_adjacency (function)` | 核心内部接口 |
| `normalize_gold_paths (function)` | 核心内部接口 |
| `normalize_predicted_paths (function)` | 核心内部接口 |
| `is_valid_shortest_path (function)` | 核心内部接口 |
| `annotation_accuracy (function)` | 核心内部接口 |
| `evaluate_document (function)` | 核心内部接口 |
| `write_csv (function)` | 核心内部接口 |
| `collect_sample_items (function)` | 返回 (split, 文件路径, 展示名称)，单文件和批量目录使用同一评价流程。 |
| `init_swanlab (function)` | 核心内部接口 |
| `log_swanlab_metrics (function)` | 核心内部接口 |
| `json_table_text (function)` | 核心内部接口 |
| 其他内部接口 | 另有 3 个辅助接口，详见源码。 |

## 输入、输出与口径

- 输入字段、候选筛选和异常状态以“核心逻辑”及源码校验条件为准。
- 推理结果以原答案文档为基础增加 `model-output` 和运行状态，错误原因不得静默丢弃。
- 评估时必须区分扫描样本、模型成功样本、结构可解析样本和实际参与指标平均的样本。
- SwanLab 是观测渠道，本地 CSV/JSON 才是可重复复核的指标结果。

[返回 批量推理与评估索引](README.md)
