# inference 脚本索引

本目录与代码目录 `inference/` 一一对应。每个 Python 文件都有同名文档，重点说明业务用途、核心逻辑、参数、输入输出和指标口径。

## 重点代码

配置生成推理主要使用以下两个脚本：

| 推理方式 | 代码 | 作用 |
|---|---|---|
| 本地部署的 vLLM | [batch_infer_qa_swanlab.py](batch_infer_qa_swanlab.md) | 调用本地 OpenAI-compatible vLLM 服务完成批量推理，保存逐样本结果，并将单样本指标和累计评估指标上传 SwanLab。 |
| 外部 LLM API | [batch_infer_llm_api_swanlab.py](batch_infer_llm_api_swanlab.md) | 调用外部 OpenAI-compatible API 完成批量推理，保存逐样本结果，并将单样本指标和累计评估指标上传 SwanLab。 |

常规配置生成实验根据模型部署方式直接选择其中一个脚本即可。两个脚本都在推理过程中使用 `model-output` 和 `answer` 计算评估指标并上传 SwanLab，不需要再单独运行评估脚本。

下方其他脚本主要用于仅预测 Value 的对照实验、历史结果离线分析、指标复算和结果绘图。

## 批量推理

| 脚本 | 功能 |
|---|---|
| [batch_infer_qa.py](batch_infer_qa.md) | **OpenAI-compatible 批量配置生成推理**：批量读取 QA 样本，通过 vLLM 或其他 OpenAI Chat Completions 兼容服务生成缺失配置，并将成功结果与失败原因逐文件落盘。 |
| [batch_infer_qa_mask_value.py](batch_infer_qa_mask_value.md) | **仅预测 Value 的批量推理**：在标准批量推理上提供目标答案的完整嵌套 Key 骨架，只要求模型补全不同 JSON 类型的 Value。 |
| [batch_infer_qa_swanlab.py](batch_infer_qa_swanlab.md) | **带 SwanLab 记录的批量推理**：在标准 OpenAI-compatible 推理流程中计算单样本指标，并向 SwanLab 记录 sample 曲线、运行中 eval 均值和样本表格。 |
| [batch_infer_qa_swanlab_mask_value.py](batch_infer_qa_swanlab_mask_value.md) | **仅预测 Value 的 SwanLab 推理**：组合 Value 掩码 Prompt 与 SwanLab 批量推理能力。 |
| [batch_infer_llm_api_swanlab.py](batch_infer_llm_api_swanlab.md) | **外部 LLM API 批量推理与 SwanLab 记录**：面向项目外部 OpenAI-compatible API 执行配置生成，支持 system Prompt、Qwen thinking 开关和返回后等待。 |
| [batch_infer_llm_api_swanlab_mask_value.py](batch_infer_llm_api_swanlab_mask_value.md) | **外部 API 的仅预测 Value 推理**：将 Value 掩码任务接入外部 LLM API 与 SwanLab 实验流程。 |

## 评估与指标

| 脚本 | 功能 |
|---|---|
| [metric.py](metric.md) | **配置 JSON 结构与值指标**：把预测和答案展开为 JSON 路径多重集合，统一计算顶层配置、字段路径、叶子三元组、值准确率及幻觉/缺失字段指标。 |
| [batch_evaluate_qa.py](batch_evaluate_qa.md) | **离线批量评估与 Token 因素分析**：对已保存推理结果进行统一离线评估，并关联原 QA Input 的粗略 Token 数和节点数。 |
| [batch_evaluate_qa_swanlab.py](batch_evaluate_qa_swanlab.md) | **离线评估结果上传 SwanLab**：先执行本地批量评估，再将 summary 中的聚合指标上传 SwanLab；支持恢复已有 run。 |
| [upload_macro_metrics_swanlab.py](upload_macro_metrics_swanlab.md) | **历史推理结果 Macro 指标上传**：独立读取已有推理 JSON，逐样本重算指标，并在新 SwanLab 实验中记录 sample 与截至当前 step 的 macro eval 曲线。 |
| [swanlab_utils.py](swanlab_utils.md) | **SwanLab 公共工具**：集中封装 SwanLab 导入、运行配置、指标命名、micro/macro 累计、样本表格和结束逻辑。 |

## 离线分析

| 脚本 | 功能 |
|---|---|
| [analyze_model_output_tokens.py](analyze_model_output_tokens.md) | **模型输出 Token 分布分析**：统计已保存 `model-output` 的粗略 Token 数、分位数、阈值覆盖率和直方图。 |
| [analyze_output_structures.py](analyze_output_structures.md) | **目标配置结构分布分析**：按答案顶层 Key 统计 JSON Path 结构类型及样本频次。 |
| [analyze_inference_order_metrics.py](analyze_inference_order_metrics.md) | **推理顺序指标趋势分析**：按实际文件推理顺序每 N 个样本分组，比较窗口指标与累计指标。 |
| [analyze_qa_metric_factors.py](analyze_qa_metric_factors.md) | **QA 上下文因素与指标分析**：从每个样本内部提取顶层 Key、答案 Path 在 Input 中的出现次数、节点数、1/2/3 跳邻居数和可见配置 Key 数，并分析其与指标的关系。 |
| [analyze_neighbor_config_similarity.py](analyze_neighbor_config_similarity.md) | **邻居同名配置距离实验**：计算目标节点到最近同名顶层配置节点的真实最短路径距离，并关联生成指标。 |
| [analyze_topology_position.py](analyze_topology_position.md) | **目标节点拓扑位置实验**：统计目标节点累计 1/2/3-hop 邻居数、连通分量大小、是否孤立和归一化中介中心性，并关联生成指标。 |
| [analyze_distance_by_root_key.py](analyze_distance_by_root_key.md) | **同名配置距离与顶层 Key 联合分析**：在最近同名配置距离基础上进一步按答案 root key 细分生成指标。 |
| [analyze_betweenness_by_distance.py](analyze_betweenness_by_distance.md) | **中介中心性与同名配置距离分析**：联合分析目标节点中介中心性分组、最近同名配置距离和生成指标。 |
| [analyze_betweenness_distance_rootkey.py](analyze_betweenness_distance_rootkey.md) | **中介中心性、距离与 Root Key 三维分析**：按中介中心性、最近同名配置距离和答案顶层 Key 三层维度聚合生成指标。 |
| [analyze_inputLength_rootkey.py](analyze_inputLength_rootkey.md) | **上下文长度与 Root Key 分析及热力图**：估算 QA Input Token 数，按长度区间和答案顶层 Key 聚合生成指标，并直接输出热力图。 |

## 结构提示

| 脚本 | 功能 |
|---|---|
| [build_structure_hints_from_csv.py](build_structure_hints_from_csv.md) | **从结构分布生成 Prompt 提示**：读取结构分布 CSV，把高频 Path 还原为带类型占位符的嵌套 JSON，并生成 `TOP_LEVEL_KEY_STRUCTURE_HINTS` Python 文件。 |

## 结果绘图

| 脚本 | 功能 |
|---|---|
| [plot_distance_rootkey.py](plot_distance_rootkey.md) | **距离与 Root Key 指标绘图**：把距离和 root key 联合分析 CSV 绘制为热力图及柱状图。 |
| [plot_betweenness_distance.py](plot_betweenness_distance.md) | **中介中心性与距离指标绘图**：读取逐文件中介中心性/距离结果，在 root key 维度聚合后绘制热力图和柱状图。 |
| [plot_betweenness_distance_rootkey.py](plot_betweenness_distance_rootkey.md) | **三维因素联合热力图**：把 `betweenness × distance × root key` 聚合结果绘制为 combined heatmap 等图。 |

## 上层导航

- [文档中心](../README.md)
