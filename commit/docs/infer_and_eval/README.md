# 推理评估代码索引

本目录解释统一推理评估模块的代码实现。入口脚本负责参数解析和批处理编排，公共模块负责可复用的数据扫描、答案解析和指标计算，任务注册表负责把七类数据集映射到正确的校验与评估方式。

[返回推理评估总览](../infer_and_eval.md)

## 模块关系

```text
task_specs.py
    │
    ├──────────────┐
    ▼              ▼
batch_infer_vllm  batch_evaluate
    │              │
    ▼              ▼
inference_common  evaluation_common
    │              │
    ▼              ▼
推理结果 JSON      本地指标 + SwanLab
```

## 子文档

| 模块 | 核心职责 | 文档 |
|---|---|---|
| `batch_infer_vllm.py` | vLLM 客户端初始化、重试、批处理和结果写入 | [查看](batch_infer_vllm.md) |
| `batch_evaluate.py` | 错误策略、累计宏平均、SwanLab 和本地输出 | [查看](batch_evaluate.md) |
| `task_specs.py` | 任务名称、默认路径、答案类型和字段注册 | [查看](task_specs.md) |
| `inference_common.py` | 样本路径配对、Prompt、JSON 提取和结构校验 | [查看](inference_common.md) |
| `evaluation_common.py` | 路径与节点集合指标、结果扫描和推理状态兼容 | [查看](evaluation_common.md) |

## 调用边界

- 推理入口不计算正确率，只判断模型回答是否能解析成当前任务所需结构。
- 评估入口不调用模型，只读取已经落盘且同时包含 `task_answer` 和 `model-output` 的结果。
- 任务差异集中在 `TaskSpec`，公共流程不通过大量任务名称分支重复实现。
- SwanLab 只由评估入口初始化，推理过程不依赖 SwanLab。

## 增加新任务

扩展新任务通常需要：

1. 在 `task_specs.py` 注册任务名称和默认目录。
2. 确认现有 `path`、`extended_path` 或 `node_set` 是否能表达答案。
3. 若答案结构不同，在 `inference_common.validate_answer()` 增加结构校验。
4. 在 `evaluation_common.metric_names()` 和 `evaluate_document()` 增加指标分派。
5. 使用同一推理、评估入口运行，无需复制批处理代码。

