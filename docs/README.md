# config_generate 推理分支文档中心

本文档对应 `inference` 分支，覆盖配置生成批量推理、离线评估、SwanLab 实验、误差因素分析和结果绘图。文档目录按照代码目录组织，便于从业务任务定位到具体脚本。

## 快速导航

| 入口 | 内容 |
|---|---|
| [inference 脚本索引](inference/README.md) | 25 个 Python 文件的一对一文档与分类导航 |
| [推理与评估工作流](guides/inference-workflow.md) | 从 QA、模型服务到离线分析的标准执行顺序 |
| [配置生成指标](guides/metrics.md) | field path、leaf triple、value accuracy、幻觉率、micro/macro 口径 |
| [目录与结果格式](guides/result-layout.md) | QA 输入、推理结果、错误日志和分析目录约定 |

## 建议阅读顺序

1. 首次运行先阅读[目录与结果格式](guides/result-layout.md)。
2. 根据模型部署方式选择[批量推理脚本](inference/README.md#批量推理)。
3. 阅读[配置生成指标](guides/metrics.md)，明确分母和 micro/macro 差异。
4. 按[推理与评估工作流](guides/inference-workflow.md)完成推理、评估和因素分析。

## 维护约定

- `inference/*.py` 与 `docs/inference/*.md` 保持同名一一对应。
- 修改 Prompt、默认路径、命令行参数、结果字段或指标分母时，同步更新相应文档。
- `docs/` 是正式版本化文档目录；模型结果、CSV、SVG 和 SwanLab 本地日志写入实验输出目录。
