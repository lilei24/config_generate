# task_batch_inference_common.py

> 代码位置：[`scripts/infer_eval/task_batch_inference_common.py`](../../../scripts/infer_eval/task_batch_inference_common.py)

## 功能与业务价值

任务 2-5 批量推理脚本共用的 vLLM 与 OpenCode 调用框架。

**业务价值：** 统一不同任务的推理行为和错误语义，减少后端差异对实验可比性的影响。

## 核心逻辑

1. 定义多个任务入口共享的数据结构、参数和校验规则。
2. 将任务差异封装为规格或回调，使批处理、错误处理和实验记录保持一致。
3. 由具体推理或评估入口导入，不建议作为最终业务命令直接运行。

## 参数

该文件是公共模块，没有独立命令行入口；参数由调用方通过函数参数、任务规格或 `argparse.Namespace` 传入。

## 运行方式

由同目录下的具体推理、评估或任务入口导入使用，不直接执行。

## 关键接口

| 接口 | 职责 |
|---|---|
| `TaskInferenceSpec (class)` | 核心内部接口 |
| `SamplePaths (class)` | 核心内部接口 |
| `InferenceResult (class)` | 核心内部接口 |
| `add_dataset_arguments (function)` | 核心内部接口 |
| `validate_common_arguments (function)` | 核心内部接口 |
| `create_vllm_parser (function)` | 核心内部接口 |
| `create_opencode_parser (function)` | 核心内部接口 |
| `validate_vllm_arguments (function)` | 核心内部接口 |
| `validate_opencode_arguments (function)` | 核心内部接口 |
| `load_json_object (function)` | 核心内部接口 |
| `write_json_atomic (function)` | 核心内部接口 |
| `collect_samples (function)` | 核心内部接口 |
| `has_successful_result (function)` | 核心内部接口 |
| `strip_markdown_code_fence (function)` | 核心内部接口 |
| `parse_answer_text (function)` | 核心内部接口 |
| `import_openai (function)` | 核心内部接口 |
| 其他内部接口 | 另有 24 个辅助接口，详见源码。 |

## 输入、输出与口径

- 输入字段、候选筛选和异常状态以“核心逻辑”及源码校验条件为准。
- 推理结果以原答案文档为基础增加 `model-output` 和运行状态，错误原因不得静默丢弃。
- 评估时必须区分扫描样本、模型成功样本、结构可解析样本和实际参与指标平均的样本。
- SwanLab 是观测渠道，本地 CSV/JSON 才是可重复复核的指标结果。

[返回 批量推理与评估索引](README.md)
