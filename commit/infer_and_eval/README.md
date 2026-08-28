# 推理与评估

该目录提供七类拓扑任务共用的 vLLM 推理和 SwanLab 评估入口。推理与评估完全分离：推理结果先逐文件写入本地，评估脚本随后读取这些结果计算指标。

## 文件说明

| 文件 | 功能 |
|---|---|
| `batch_infer_vllm.py` | 调用 OpenAI-compatible vLLM 服务，批量推理并逐文件保存结果 |
| `batch_evaluate.py` | 独立计算逐样本指标、累计平均指标并上传 SwanLab |
| `task_specs.py` | 定义七个任务的数据目录、结果目录和答案类型 |
| `inference_common.py` | 文件扫描、Prompt 构造、模型输出解析和答案校验 |
| `evaluation_common.py` | 路径及节点集合指标计算、结果文件扫描 |

## 支持任务

- `shortest_path`
- `uplink_node_path`
- `node_failure_reroute`
- `node_failure_ap_impact`
- `ap_pair_via_core_path`
- `downstream_reachable_terminal`
- `vlan_constrained_shortest_path`

## 推理

```bash
python commit/infer_and_eval/batch_infer_vllm.py \
  --task shortest_path \
  --split val \
  --base-url http://localhost:8000/v1 \
  --model qwen3-8b
```

输出 JSON 以 `with_answer` 文件为基础，增加：

```json
{
  "model-output": {},
  "inference_metadata": {
    "success": true,
    "error_stage": null,
    "error": null
  }
}
```

使用 `--resume` 时，已有成功结果会被跳过，失败或损坏文件会重新推理。

## 评估

```bash
python commit/infer_and_eval/batch_evaluate.py \
  --task shortest_path \
  --split val \
  --error-policy zero \
  --swanlab-experiment qwen3-8b-shortest-path
```

`--error-policy` 控制失败样本如何参与平均：

- `zero`：失败样本各指标按零分计入，衡量端到端系统能力。
- `exclude`：失败样本不进入平均分母，衡量有效模型回答的质量。

两种策略都会在 `evaluation_summary.json` 中记录失败数量和实际平均分母。SwanLab 的 `sample/*` 表示单样本指标，`eval/*` 表示截至当前步骤的累计宏平均指标。

