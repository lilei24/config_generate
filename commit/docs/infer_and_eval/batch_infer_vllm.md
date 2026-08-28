# batch_infer_vllm.py

**源码：** [`batch_infer_vllm.py`](../../infer_and_eval/batch_infer_vllm.py)

[返回代码索引](README.md)

## 模块职责

该文件是七类任务共用的 vLLM 批量推理入口，负责：

- 解析数据集、模型服务和批处理参数。
- 根据任务名称加载 `TaskSpec`。
- 初始化 OpenAI-compatible 客户端。
- 对单样本执行请求、重试和 JSON 解析。
- 将模型答案写入对应的有答案样本。
- 输出批次汇总和错误明细。

任务 Prompt、答案结构和结果评估不在此文件中硬编码，分别交给 `inference_common.py`、`task_specs.py` 和评估模块。

## 主要函数

### `parse_args()`

定义统一推理参数，并在模型调用前完成基本合法性检查：

- `temperature`、超时必须满足有效范围。
- 重试次数、等待时间、进度间隔和缩进不能为负数。
- `limit` 如果提供，不能小于 0。
- `task` 只能取 `TASK_SPECS` 中已注册的名称。

路径参数允许两级覆盖：优先使用 `hidden-root` 和 `answer-root`，否则根据 `dataset-root` 推导；`dataset-root` 也未提供时使用任务配置默认值。

### `import_openai()`

延迟导入 `OpenAI`，使代码在仅查看帮助或运行本地评估时不强制依赖 `openai`。依赖缺失时给出明确安装错误。

### `request_one(client, args, spec, prompt)`

负责单个样本的完整模型调用。

请求消息：

```text
system: inference_common.SYSTEM_PROMPT
user:   build_prompt() 生成的任务问题和完整拓扑 JSON
```

Chat Completions 请求参数包括：

- `model`
- `temperature`
- `stream=False`
- `chat_template_kwargs.enable_thinking`

一次尝试分为两个错误阶段：

1. `request`：网络异常、服务报错、超时或模型返回空内容。
2. `model_output_parse`：模型返回了文本，但无法提取满足任务结构的 JSON。

请求和解析失败都会按照 `retries` 重试。成功时返回解析后的字典和成功元数据；最终失败时返回 `None`，并保存最后一次错误和非空原始回答。

### `main()`

批处理主流程：

1. 获取任务配置并解析数据、答案和输出目录。
2. 通过 `collect_samples()` 按相对路径配对 `without_answer` 与 `with_answer`。
3. 应用 `limit`，为空时直接报错。
4. 创建共享 OpenAI 客户端，避免每个样本重复初始化。
5. 按字典序处理样本。
6. `resume` 模式下，使用 `successful_result()` 跳过已有成功结果。
7. 检查隐藏答案文件不含 `task_answer`，并检查有答案文件确实包含标准答案。
8. 构造 Prompt，调用 `request_one()`。
9. 以有答案样本为基础加入 `model-output` 和 `inference_metadata`。
10. 使用原子写入保存结果，避免中途退出留下半个 JSON。
11. 更新成功、失败、跳过数量并打印文本进度。
12. 写入 `batch_summary.json` 和 `batch_errors.csv`。

## 结果结构

成功：

```json
{
  "task_answer": {},
  "model-output": {},
  "inference_metadata": {
    "success": true,
    "error_stage": null,
    "error": null,
    "model": "Qwen/Qwen3.6-27B",
    "base_url": "http://localhost:8000/v1",
    "thinking_enabled": false,
    "attempts": 1,
    "duration_seconds": 2.5
  }
}
```

失败：

```json
{
  "task_answer": {},
  "model-output": null,
  "inference_metadata": {
    "success": false,
    "error_stage": "model_output_parse",
    "error": "ValueError: ...",
    "raw_model_output": "模型原始文本"
  }
}
```

样本文件自身损坏时，错误阶段为 `sample_processing`。只要同名有答案文件仍能读取，脚本就会写出失败结果；若标准答案文件本身也无法读取，则只在批次错误 CSV 中记录。

## 断点续推

`--resume` 只跳过同时满足以下条件的文件：

- 输出 JSON 可读取。
- `inference_metadata.success` 为 `true`。
- `model-output` 是 JSON 对象。

失败结果、损坏结果和缺失结果都会重新推理。`skipped` 因此表示已有成功结果，不代表数据错误或构造跳过。

## 进度与等待

脚本使用文本进度而不是动态图形进度条：

```text
[12/746] succeeded=10 failed=2 skipped=0 elapsed=00:03:25
```

`progress-interval` 控制打印频率，`wait-seconds` 在每个样本处理完成后等待，包括断点跳过的样本。

## 扩展注意事项

- 不应在该入口中增加某个任务专用 Prompt；任务问题由数据集中的 `task_question` 提供。
- 不应在推理阶段判断答案是否正确，语义正确性属于评估职责。
- 如果接入非 vLLM 服务，只要兼容 OpenAI Chat Completions 和 `extra_body` 即可复用；不支持 `chat_template_kwargs` 的服务需要调整请求体。

