# config_generate 推理分支文档中心

本文档对应 `inference` 分支，覆盖配置生成批量推理、离线评估、SwanLab 实验、误差因素分析和结果绘图。文档目录按照代码目录组织，便于从业务任务定位到具体脚本。

## 重点代码

配置生成推理直接使用以下两个脚本：

| 推理方式 | 代码 | 作用 |
|---|---|---|
| 本地部署的 vLLM | [`inference/batch_infer_qa_swanlab.py`](inference/batch_infer_qa_swanlab.md) | 通过本地 OpenAI-compatible vLLM 服务批量推理，同时保存逐样本结果并上传 SwanLab。 |
| 外部 LLM API | [`inference/batch_infer_llm_api_swanlab.py`](inference/batch_infer_llm_api_swanlab.md) | 通过外部 OpenAI-compatible API 批量推理，同时保存逐样本结果并上传 SwanLab。 |

这两个脚本都会在推理过程中使用 `model-output` 和 `answer` 计算单样本指标及截至当前 step 的累计指标，并上传到 SwanLab。常规配置生成实验直接选择其中一个脚本即可，不需要再单独运行评估脚本。

离线评估代码主要用于重新分析历史推理结果、生成本地 CSV，或研究 Input Token 与指标之间的关系，不是完成常规 SwanLab 推理实验的必需步骤。

## 快速导航

| 入口 | 内容 |
|---|---|
| [配置生成数据集构造](scripts/README.md) | 从原始拓扑生成 QA、构造前 Token 裁剪及已有 QA 二次裁剪 |
| [inference 脚本索引](inference/README.md) | 25 个 Python 文件的一对一文档与分类导航 |
| [配置生成指标](guides/metrics.md) | field path、leaf triple、value accuracy、幻觉率、micro/macro 口径 |
| [目录与结果格式](guides/result-layout.md) | QA 输入、推理结果、错误日志和分析目录约定 |

## 维护约定

- `scripts/*.py`、`inference/*.py` 分别与对应文档目录中的 Markdown 保持同名一一对应。
- 修改 Prompt、默认路径、命令行参数、结果字段或指标分母时，同步更新相应文档。
- `docs/` 是正式版本化文档目录；模型结果、CSV、SVG 和 SwanLab 本地日志写入实验输出目录。
