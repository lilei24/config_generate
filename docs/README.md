# config_generate 文档中心

本文档与 `data_analyze` 分支代码目录一一对应。建议从本页定位业务模块，再进入模块索引和单脚本文档。

## 快速导航

| 模块 | 主要内容 | 文档 |
|---|---|---|
| 数据格式 | 原始拓扑、QA 与任务样本结构 | [数据集格式说明](dataset_format_notes.md) |
| 通用分析与配置生成 | 数据质量、规模、配置 QA、模型业务分析 | [scripts 索引](scripts/README.md) |
| 任务数据集构建 | 最短路径、故障、影响面、端口、VLAN 等任务 | [构建脚本索引](scripts/build_task_dataset/README.md) |
| 推理与评估 | vLLM、OpenCode、SwanLab、指标与轨迹 | [推理评估索引](scripts/infer_eval/README.md) |
| VLAN 专项 | 接口匹配、集合校验、约束路径和可视化 | [VLAN 索引](scripts/vlan_analysis/README.md) |
| 拓扑可视化 | 原始拓扑交互式 HTML | [可视化索引](topology_visualizer/README.md) |

## 阅读路径

1. 新接触数据：阅读[数据与目录](guides/dataset-layout.md)。
2. 运行统计：进入 [scripts 索引](scripts/README.md)，选择对应分析脚本。
3. 构造任务：从[任务构建索引](scripts/build_task_dataset/README.md)确认业务定义和答案口径。
4. 批量实验：阅读[标准工作流](guides/common-workflows.md)，再进入推理和评估文档。
5. 环境准备：参考[运行环境](guides/environment.md)。

## 文档维护约定

- 单个 Python 文件对应同层级、同名 Markdown。
- 新增或修改参数时，同步更新脚本文档的“参数”和“关键默认值”。
- 修改任务筛选、随机策略、答案结构或指标分母时，必须同步更新“核心逻辑”和“统计口径”。
- `docs/` 是正式版本化文档目录；临时分析产物不得写入该目录。
