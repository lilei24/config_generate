# 网络拓扑任务数据集与评测工具

本项目从网络物理拓扑 JSON 构造可自动验证的 Agent 任务数据集，并提供统一的 vLLM 批量推理、独立指标评估、SwanLab 实验记录和交互式拓扑可视化能力。

## 文档导航

| 文档 | 内容 |
|---|---|
| [任务数据集构造](build_task_dataset/README.md) | 七类任务、构造脚本映射和数据集公共约定 |
| [推理与评估](infer_and_eval.md) | vLLM 推理、结果落盘、评价指标和 SwanLab 记录 |
| [任务拓扑可视化](task_visualizer.md) | 三类任务的交互式 HTML 可视化 |

## 代码结构

```text
build_task_dataset_scripts/  七类任务数据集构造
infer_and_eval/              统一推理与独立评估
task_visualizer/             任务拓扑可视化
docs/                        集中式项目文档
```

## 整体数据流

```text
原始拓扑 datasets/train、datasets/val
                  │
                  ▼
          任务数据集构造
                  │
          ┌───────┴────────┐
          ▼                ▼
 with_answer          without_answer
 标准答案版本            隐藏答案版本
          │                │
          │                ▼
          │            vLLM 推理
          │                │
          └───────┬────────┘
                  ▼
      task_answer + model-output
                  │
          ┌───────┴────────┐
          ▼                ▼
      本地评估文件       SwanLab 实验记录
```

构造阶段从同一个已完成任务选择的样本生成 `with_answer` 和 `without_answer`，确保两份数据除 `task_answer` 外一致。推理阶段读取隐藏答案版本，但结果文件以有答案版本为基础加入 `model-output`，因此评估阶段只需要读取一个结果 JSON。

## 原始拓扑字段

- `nodes[].id`：节点唯一标识，任务路径统一使用节点 ID。
- `nodes[].device` 或 `nodes[].devices`：设备名称、物理类型和型号。
- `nodes[].topologyNode.DEVICEROLE`：AP、ACC、AGG、CORE、Firewall 等逻辑角色。
- `links[].source`、`links[].target`：物理链路端点。
- `links[].link.LEFTPORT`、`RIGHTPORT`：source 侧和 target 侧端口。
- `nodes[].configs[]`：VLAN 约束任务使用的交换机接口配置。

## 公共口径

- 路径长度表示链路跳数，即路径节点数减一。
- 多条等长最短路径全部作为标准答案保留。
- 任务路径、故障节点、上游节点和终端节点均使用 `nodes[].id`。
- 固定随机种子仅在输入文件集合、排序和代码版本一致时保证可复现。
- 推理失败和答案错误分开处理：能解析成任务 JSON 的错误答案进入指标计算。

## 运行环境

- Python 3.9 或兼容版本。
- 数据集构造与 HTML 可视化主要使用 Python 标准库。
- vLLM 推理依赖 `openai` Python SDK和 OpenAI-compatible Chat Completions 服务。
- SwanLab 在线记录依赖 `swanlab`；本地评估可以关闭上传。

