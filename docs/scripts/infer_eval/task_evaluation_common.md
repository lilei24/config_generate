# task_evaluation_common.py

> 代码位置：[`scripts/infer_eval/task_evaluation_common.py`](../../../scripts/infer_eval/task_evaluation_common.py)

## 功能与业务价值

任务评估脚本共用的批处理、SwanLab 记录和路径集合指标。

**业务价值：** 统一路径集合和集合类指标的计算口径，保证不同任务评估结果可比较。

## 核心逻辑

1. 定义多个任务入口共享的数据结构、参数和校验规则。
2. 将任务差异封装为规格或回调，使批处理、错误处理和实验记录保持一致。
3. 由具体推理或评估入口导入，不建议作为最终业务命令直接运行。

## 参数

该文件是公共模块，没有独立命令行入口；参数由调用方通过函数参数、任务规格或 `argparse.Namespace` 传入。

### 关键默认值

| 常量 | 当前值 |
|---|---|
| `PATH_METRIC_NAMES` | `('path_length_accuracy', 'path_precision', 'path_recall', 'path_f1')` |
| `PATH_DETAIL_NAMES` | `('predicted_path_count', 'gold_path_count', 'true_positive', 'false_positive', 'false_negative')` |
| `DEFAULT_SWANLAB_COLOR_SEED` | `20260727` |

## 运行方式

由同目录下的具体推理、评估或任务入口导入使用，不直接执行。

## 关键接口

| 接口 | 职责 |
|---|---|
| `add_evaluation_arguments (function)` | 核心内部接口 |
| `validate_evaluation_arguments (function)` | 核心内部接口 |
| `load_json_object (function)` | 核心内部接口 |
| `normalize_path_set (function)` | 返回去重路径集合、原始预测数量和非法路径数量。 |
| `evaluate_path_document (function)` | 核心内部接口 |
| `collect_sample_items (function)` | 核心内部接口 |
| `import_swanlab (function)` | 核心内部接口 |
| `deterministic_experiment_color (function)` | 将固定种子、实验名和区分键稳定映射为十六进制颜色。 |
| `experiment_color_key (function)` | 核心内部接口 |
| `init_swanlab (function)` | 核心内部接口 |
| `get_run_info (function)` | 核心内部接口 |
| `log_metrics (function)` | 核心内部接口 |
| `json_table_text (function)` | 核心内部接口 |
| `build_table_row (function)` | 核心内部接口 |
| `log_table (function)` | 核心内部接口 |
| `write_csv (function)` | 核心内部接口 |
| 其他内部接口 | 另有 2 个辅助接口，详见源码。 |

## 输入、输出与口径

- 输入字段、候选筛选和异常状态以“核心逻辑”及源码校验条件为准。
- 推理结果以原答案文档为基础增加 `model-output` 和运行状态，错误原因不得静默丢弃。
- 评估时必须区分扫描样本、模型成功样本、结构可解析样本和实际参与指标平均的样本。
- SwanLab 是观测渠道，本地 CSV/JSON 才是可重复复核的指标结果。

[返回 批量推理与评估索引](README.md)
