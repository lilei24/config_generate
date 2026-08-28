# 推理与评估

**对应代码目录：** [`infer_and_eval/`](../infer_and_eval/)

[返回文档总览](README.md)

该模块为七类拓扑任务提供统一的 vLLM 推理和 SwanLab 评估入口。推理与评估完全分离：推理先逐文件保存模型答案，评估再读取结果计算单样本指标和累计宏平均指标。

## 文件职责

| 文件 | 功能 |
|---|---|
| [`batch_infer_vllm.py`](../infer_and_eval/batch_infer_vllm.py) | 调用 OpenAI-compatible vLLM 服务并逐文件保存结果 |
| [`batch_evaluate.py`](../infer_and_eval/batch_evaluate.py) | 独立评估、本地输出和 SwanLab 上传 |
| [`task_specs.py`](../infer_and_eval/task_specs.py) | 七任务名称、默认目录、答案类型和答案字段注册表 |
| [`inference_common.py`](../infer_and_eval/inference_common.py) | 文件扫描、Prompt 构造、模型调用结果解析和结构校验 |
| [`evaluation_common.py`](../infer_and_eval/evaluation_common.py) | 路径、角色、设备名称和节点集合指标计算 |

## 任务配置

`task_specs.py` 中的每个 `TaskSpec` 包含：

- `name`：命令行 `--task` 使用的任务标识。
- `dataset_root`：默认任务数据集根目录。
- `result_root`：默认推理结果目录。
- `evaluation_root`：默认评估输出目录。
- `answer_kind`：决定答案结构校验和指标计算方式。
- `answer_field`：节点集合任务在答案中的字段名。

答案类型：

| 类型 | 中文任务 | 评价范围 |
|---|---|---|
| `extended_path` | 节点最短路径查询 | 跳数、路径、路径合法性、角色和设备名称 |
| `path` | 上行节点路径查询、节点故障约束路径查询、指定CORE约束的AP间最短路径查询、vlan约束的交换机路径查询 | 跳数和路径集合 |
| `node_set` | 可达下游终端节点、故障影响AP节点 | 节点 ID 集合 |

## vLLM 推理过程

1. 根据 `--task` 加载任务配置。
2. 按文件路径字典序扫描 `without_answer/<split>`。
3. 检查隐藏答案样本不包含 `task_answer`。
4. 读取 `task_question`，与完整任务拓扑 JSON 共同构成用户消息。
5. 通过 OpenAI-compatible Chat Completions API 调用 vLLM。
6. 从模型文本中提取 JSON 对象，并检查任务要求的字段类型。
7. 加载同名 `with_answer` 文件，加入 `model-output` 和 `inference_metadata`。
8. 请求失败、JSON 无法解析或字段结构不合法时仍生成结果文件，并记录错误阶段和原始模型回答。
9. 输出批次汇总和错误 CSV。

推理校验只负责判断模型回答能否进入评估，不判断答案是否正确。例如，模型返回的 `path_length` 与路径节点数不一致时仍视为成功返回，由 `path_length_accuracy` 记录错误。

## 推理参数

| 参数 | 默认值 | 作用 |
|---|---:|---|
| `--task` | 必填 | 选择任务配置 |
| `--dataset-root` | 任务配置值 | 同时包含 with_answer 和 without_answer 的根目录 |
| `--hidden-root` | `<dataset>/without_answer` | 单独覆盖隐藏答案目录 |
| `--answer-root` | `<dataset>/with_answer` | 单独覆盖标准答案目录 |
| `--output-root` | `vllm-results/<task>` | 推理结果目录 |
| `--split` | `val` | `train`、`val` 或 `all` |
| `--base-url` | `http://localhost:8000/v1` | OpenAI-compatible 服务地址 |
| `--api-key` | `empty` | API Key |
| `--model` | `qwen3-8b` | 服务端模型名称，例如 `Qwen/Qwen3.6-27B` |
| `--temperature` | `0.2` | 采样温度 |
| `--request-timeout` | `600` | 单次请求超时秒数 |
| `--retries` | `1` | 首次失败后的重试次数 |
| `--retry-wait-seconds` | `5` | 重试间隔秒数 |
| `--wait-seconds` | `0` | 每个样本处理后的等待时间 |
| `--enable-thinking` | 关闭 | 开启模型思考模式 |
| `--resume` | 关闭 | 跳过已有成功结果，重试失败或损坏结果 |
| `--limit` | 不限制 | 只处理扫描顺序中的前 N 个样本 |
| `--progress-interval` | `1` | 文本进度打印间隔，`0` 表示关闭 |
| `--indent` | `2` | 输出 JSON 缩进 |

## 推理结果

成功结果：

```json
{
  "task_answer": {
    "path_length": 3,
    "paths": [["A", "B", "C", "D"]]
  },
  "model-output": {
    "path_length": 3,
    "paths": [["A", "B", "C", "D"]]
  },
  "inference_metadata": {
    "success": true,
    "error_stage": null,
    "error": null,
    "model": "Qwen/Qwen3.6-27B",
    "attempts": 1,
    "duration_seconds": 2.35
  }
}
```

失败结果的 `model-output` 为 `null`，错误保存在 `inference_metadata.error_stage` 和 `error`；模型已返回文本但无法解析时，原文保存在 `raw_model_output`。

批次输出：

- `batch_summary.json`：任务、模型、总数、成功、失败、断点跳过和耗时。
- `batch_errors.csv`：split、文件名、输出路径、错误阶段和错误原因。

## 独立评估过程

1. 按字典序读取推理结果 JSON。
2. 根据 `inference_metadata.success` 判断模型是否有效返回。
3. 根据任务的 `answer_kind` 选择评估器。
4. 每个样本独立比较 `task_answer` 与 `model-output`。
5. 使用 `--error-policy` 决定失败样本是否进入平均分母。
6. 本地写出逐样本指标、错误明细和汇总指标。
7. SwanLab 逐步记录 `sample/*` 和 `eval/*`，评估结束后上传 `sample/details` 表格。

## 错误样本策略

| 策略 | 行为 | 使用场景 |
|---|---|---|
| `zero` | 推理或评估失败样本的指标按 0 计入平均 | 衡量端到端系统能力 |
| `exclude` | 失败样本不进入平均分母 | 研究有效模型回答的质量 |

两种策略都会在 `evaluation_summary.json` 中保留总样本数、成功数、失败数和实际平均分母。

## 评估参数

| 参数 | 默认值 | 作用 |
|---|---:|---|
| `--task` | 必填 | 选择任务和指标集合 |
| `--result-root` | `vllm-results/<task>` | 推理结果根目录 |
| `--output-dir` | `vllm-results/<task>-evaluation` | 本地评估输出目录 |
| `--split` | `val` | `train`、`val` 或 `all` |
| `--error-policy` | `zero` | 失败样本计零或排除 |
| `--progress-interval` | `100` | 评估进度打印间隔 |
| `--swanlab-project` | `topology-agent-evaluation` | SwanLab 项目名称 |
| `--swanlab-experiment` | `<task>-evaluation` | 实验名称 |
| `--swanlab-mode` | `cloud` | SwanLab 运行模式 |
| `--disable-swanlab` | 关闭 | 仅生成本地评估文件 |

## 各任务指标

### 节点最短路径查询

- `path_length_accuracy`：最短跳数是否正确。
- `path_valid_rate`：预测路径中节点、端点及相邻链路均合法的比例。
- `path_precision`、`path_recall`、`path_f1`：完整节点 ID 路径集合的查准率、查全率和 F1。
- `path_exact_match_rate`：跳数和全部路径是否完全一致。
- `role_accuracy`：路径角色序列准确率。
- `device_name_accuracy`：路径设备名称序列准确率。

### 上行节点路径查询

`path_length_accuracy`、`path_precision`、`path_recall`、`path_f1`。

### 可达下游终端节点

`terminal_precision`、`terminal_recall`、`terminal_f1`、`terminal_exact_match_rate`。

### 节点故障约束路径查询

`path_length_accuracy`、`path_precision`、`path_recall`、`path_f1`。

### 指定CORE约束的AP间最短路径查询

`path_length_accuracy`、`path_precision`、`path_recall`、`path_f1`。

### vlan约束的交换机路径查询

`path_length_accuracy`、`path_precision`、`path_recall`、`path_f1`。

### 故障影响AP节点

`impacted_ap_precision`、`impacted_ap_recall`、`impacted_ap_f1`。

所有最终指标先按单个样本计算，再按实际平均分母进行宏平均。路径集合指标把完整节点 ID 序列作为一个集合元素，只有整条序列一致才算命中。

## 评估输出与 SwanLab

本地文件：

```text
<evaluation_output>/
├── per_sample_metrics.csv
├── evaluation_errors.csv
└── evaluation_summary.json
```

SwanLab：

- `sample/<metric>`：当前单个样本指标。
- `eval/<metric>`：截至当前步骤的累计宏平均指标。
- `sample/details`：`json_name`、完整上下文、标准答案和模型输出表格。
