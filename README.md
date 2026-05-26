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
