# config_generate 推理分支文档中心

本文档对应 `inference` 分支，主要包含配置生成数据集构造、模型推理、SwanLab 评估和结果分析代码。

## 重点代码

### inference

配置生成推理主要使用以下两个脚本：

| 推理方式 | 代码 | 作用 |
|---|---|---|
| 本地部署的 vLLM | [`inference/batch_infer_qa_swanlab.py`](inference/batch_infer_qa_swanlab.md) | 通过本地 OpenAI-compatible vLLM 服务批量推理，同时保存逐样本结果并上传 SwanLab。 |
| 外部 LLM API | [`inference/batch_infer_llm_api_swanlab.py`](inference/batch_infer_llm_api_swanlab.md) | 通过外部 OpenAI-compatible API 批量推理，同时保存逐样本结果并上传 SwanLab。 |

这两个脚本都会在推理过程中使用 `model-output` 和 `answer` 计算单样本指标及截至当前 step 的累计指标，并上传到 SwanLab。常规配置生成实验直接选择其中一个脚本即可，不需要再单独运行评估脚本。

### scripts

配置生成数据集主要使用以下两个脚本：

| 构建方式 | 代码 | 作用 |
|---|---|---|
| 构建完整上下文数据集 | [`scripts/build_config_generation_dataset.py`](scripts/build_config_generation_dataset.md) | 从原始拓扑中选择待预测配置，构造 node 和 deviceGroup 两类 QA 数据。 |
| 构建 Token 受限数据集 | [`scripts/build_config_generation_dataset_pruned.py`](scripts/build_config_generation_dataset_pruned.md) | 对超过指定 Input Token 阈值的图删除部分远距离节点，再选择待预测配置并构造 QA 数据。 |

## 目录说明

- [`inference/`](inference/README.md)：模型推理、SwanLab 指标记录、离线评估、实验因素分析和结果绘图。
- [`scripts/`](scripts/README.md)：从原始拓扑构造配置生成 QA，以及对已有 QA 的 Input 进行节点裁剪。
