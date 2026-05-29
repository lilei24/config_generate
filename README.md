# config_generate

配置生成任务项目。

## vLLM 批量推理

安装依赖：

```bash
pip install openai
```

默认读取：

```text
520QA/train/device_config_qa/*.json
520QA/train/node_config_qa/*.json
```

默认输出：

```text
inference-results/train/device_config_qa/*.json
inference-results/train/node_config_qa/*.json
```

运行：

```bash
python3 inference/batch_infer_qa.py \
  --base-url http://localhost:8000/v1 \
  --api-key empty \
  --model qwen3-8b \
  --temperature 0.2 \
  --progress-interval 20
```

脚本不会主动限制输入 token 或输出 token。样本过长、服务端上下文不足、
服务异常等问题都会作为失败原因记录下来。

每个输出 JSON 包含：

```json
{
  "model-ouput": {
    "模型预测的配置名": {}
  },
  "answer": {
    "标准答案配置名": {}
  }
}
```

如果模型输出不是合法 JSON，脚本不会中断，会额外写入
`model-output-parse-error` 和 `model-output-raw`，方便检查原始回答。

失败会记录到：

```text
inference-results/train/failures.jsonl
```

默认会通过 vLLM `extra_body.chat_template_kwargs.enable_thinking=false` 尝试关闭
Qwen3 thinking，并额外去掉输出中的 `<think>...</think>` 内容。

## 批量评估

默认读取：

```text
inference-qwen3-8b/train/device_config_qa/*.json
inference-qwen3-8b/train/node_config_qa/*.json
inference-qwen3-8b/val/device_config_qa/*.json
inference-qwen3-8b/val/node_config_qa/*.json
```

运行：

```bash
python3 inference/batch_evaluate_qa.py
```

默认输出到：

```text
metric-results/qwen3-8b/
```

其中：

- `summary.json`：按 split/task 汇总指标，并统计模型推理错误数量。
- `per_file_metrics.jsonl`：每个成功推理文件的详细指标。
- `error_summary.csv`：按错误原因聚合的数量统计。
- `eval_errors.jsonl`：评估脚本自身遇到的坏 JSON、缺字段等问题。

## SwanLab 推理和评估

安装依赖：

```bash
pip install swanlab
```

带 SwanLab 记录的推理：

```bash
python3 inference/batch_infer_qa_swanlab.py \
  --base-url http://localhost:8000/v1 \
  --api-key empty \
  --model qwen3-8b \
  --output-root inference-qwen3-8b \
  --swanlab-project config-generation \
  --swanlab-experiment qwen3-8b-inference
```

每个样本会上传：

- `sample/table` 表格，包含 step、样本文件名、模型回答、`answer`
- 样本级 `sample/field_path/precision`
- 样本级 `sample/field_path/recall`
- 样本级 `sample/field_path/f1`
- 样本级 `sample/leaf_triple/precision`
- 样本级 `sample/leaf_triple/recall`
- 样本级 `sample/leaf_triple/f1`
- 样本级 `sample/value_accuracy/accuracy`
- 样本级 `sample/hallucination_missing/hallucinated_rate`
- 样本级 `sample/hallucination_missing/missing_rate`

`sample/table` 默认每 50 个样本更新一次，可以通过
`--sample-table-log-interval` 调整。设为 `1` 时每个样本都更新表格。
曲线图 tooltip 仍只显示数值指标；需要查看某个点的模型回答和答案时，
用曲线上的 step 到 `sample/table` 中查同一行。

远程 LLM API 版本：

```bash
python3 inference/batch_infer_llm_api_swanlab.py \
  --base-url http://10.246.114.119:9000/v1 \
  --api-key empty \
  --model Qwen-Qwen3_6-27B \
  --temperature 0.6 \
  --output-root inference-qwen3_6-27b \
  --swanlab-project config-generation \
  --swanlab-experiment qwen3_6-27b-api-inference
```

这个脚本默认会发送 system message：

```text
你是个智能助手
```

如果远程服务支持 Qwen/vLLM 的 `extra_body.chat_template_kwargs.enable_thinking=false`，
可以额外加：

```bash
--enable-thinking-extra-body
```

带 SwanLab 记录的评估：

```bash
python3 inference/batch_evaluate_qa_swanlab.py \
  --result-root inference-qwen3-8b \
  --output-root metric-results/qwen3-8b \
  --swanlab-project config-generation \
  --swanlab-experiment qwen3-8b-evaluation
```

如果要把评估指标补充到已有推理实验里，使用推理实验的 run id：

```bash
python3 inference/batch_evaluate_qa_swanlab.py \
  --result-root inference-qwen3-8b \
  --output-root metric-results/qwen3-8b \
  --swanlab-project config-generation \
  --swanlab-run-id <推理实验ID> \
  --swanlab-resume must \
  --swanlab-log-step 999999
```

`--swanlab-run-id` 可以在 SwanLab 实验 URL 的 `/runs/<exp_id>/`
或实验的 Environment 页面中找到。传了 `--swanlab-run-id` 但不传
`--swanlab-resume` 时，脚本默认使用 `must`，确保不会误开新实验。

评估脚本会上传每个 split/task 的汇总：

- `field_path`
- `leaf_triple`
- `value_accuracy`
- `hallucinated_rate`
- `missing_rate`
