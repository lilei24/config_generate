# 推理与评估工作流

## 1. 构造或准备输入

QA 默认按 `<qa-root>/<split>/<task>/**/*.json` 组织。单个样本至少包含 `prompt`、`input` 和 `output`；`output` 只作为本地答案与评估依据，不直接作为模型上下文值泄露。

需要从原始拓扑构造 QA 时，可选择基础构造或构造前裁剪版本；如果需要在相同预测目标上继续缩短上下文，使用已有 QA 二次裁剪脚本。三者的区别见[配置生成数据集构造脚本](../scripts/README.md)。

## 2. 选择推理入口

- 本地 vLLM/OpenAI-compatible：`batch_infer_qa.py`。
- 本地服务并记录 SwanLab：`batch_infer_qa_swanlab.py`。
- 外部 API 并记录 SwanLab：`batch_infer_llm_api_swanlab.py`。
- 仅预测 Value：选择对应的 `*_mask_value.py` 变体。

运行前先用 `--limit 2` 验证服务地址、模型名、Prompt、输出 JSON 和失败日志。默认按任务列表顺序、每个目录内 JSON 文件名字典序执行。

## 3. 检查推理结果

正常结果包含 `structure-hints`、`model-output` 和 `answer`。模型文本不能解析时会额外保存 `model-output-parse-error` 与 `model-output-raw`；请求或读取失败保存 `error`，并写入 split 级 `failures.jsonl`。

## 4. 离线评估

使用 `batch_evaluate_qa.py` 对已有结果复算指标。评估会区分 model error、eval error 和 evaluated file，并输出逐文件指标、总指标及 Token 分桶结果。需要 SwanLab 汇总时使用 `batch_evaluate_qa_swanlab.py`；需要把历史结果按样本等权重算为 macro 曲线时使用 `upload_macro_metrics_swanlab.py`。

## 5. 因素分析

- 上下文和输出长度：`analyze_inputLength_rootkey.py`、`analyze_model_output_tokens.py`。
- 配置结构：`analyze_output_structures.py`、`build_structure_hints_from_csv.py`。
- 拓扑和参考距离：`analyze_topology_position.py`、`analyze_neighbor_config_similarity.py` 及三维联合分析脚本。
- 数据顺序：`analyze_inference_order_metrics.py`。

因素分析必须同时指定与结果对应的 `result-root` 和原 QA 的 `qa-root`，否则无法关联 metadata、Input 和拓扑。
