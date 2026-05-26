# config_generate

配置生成任务项目。

## vLLM 推理

`inference` 分支提供 OpenAI-compatible Chat Completions 推理脚手架。只要 vLLM
已经以 `/v1/chat/completions` 形式启动，就可以复用同一套客户端调用 Qwen、
Gemma、Llama、DeepSeek 等模型。

先修改配置：

```text
config/inference_config.yaml
```

关键字段：

```yaml
base_url: http://localhost:8000/v1
api_key: EMPTY
model: Qwen/Qwen3-8B
qa_root: QA
output_dir: inference_outputs
temperature: 0
max_tokens: 2048
```

运行少量样本做 dry run，检查 prompt：

```bash
python3 -m inference.run_inference --config config/inference_config.yaml --limit 2 --dry-run
```

连接 vLLM 服务实际推理：

```bash
python3 -m inference.run_inference --config config/inference_config.yaml --limit 2
```

输出会写到：

```text
inference_outputs/
  train/
    node_config_qa/
    device_config_qa/
  val/
    node_config_qa/
    device_config_qa/
```

每个输出 JSON 包含请求 messages、模型原始文本、解析出的 JSON、解析错误和原始响应。
