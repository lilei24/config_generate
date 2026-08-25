# 目录与结果格式

## QA 输入

QA 可由 `scripts/build_config_generation_dataset.py` 或其裁剪版本从原始 `datasets/train|val` 生成。

```text
520QA/
  train/
    node_config_qa/*.json
    device_config_qa/*.json
  val/
    node_config_qa/*.json
    device_config_qa/*.json
```

单个 QA JSON 的核心字段：

```json
{
  "prompt": "请预测节点配置 ...",
  "input": {"deviceGroups": [], "nodes": [], "links": []},
  "output": {"target-top-level-key": {}}
}
```

## 推理结果

推理保持相同的 split、task 和相对文件名：

```text
inference-results/<split>/<task>/<sample>.json
```

```json
{
  "structure-hints": null,
  "model-output": {"target-top-level-key": {}},
  "answer": {"target-top-level-key": {}}
}
```

兼容读取字段包括 `model-output`、`model_output` 和历史拼写 `model-ouput`。新结果应统一写 `model-output`。

## 错误字段

- `error`：样本读取失败或模型请求异常。
- `model-output-parse-error`：服务返回内容，但无法解析为目标 JSON。
- `model-output-raw`：解析失败时保留的原始模型文本。
- `failures.jsonl`：split 级失败索引；每次推理运行按当前代码逻辑固定覆盖旧日志。

## 分析产物

分析脚本默认写入 `metric-results/` 或脚本自己的输出目录。CSV 用于复核与二次统计，JSON 保存总体摘要，SVG/PNG/PDF 用于可视化。分析输出不应写回 QA 或推理结果目录。
