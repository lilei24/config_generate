# batch_infer_qa_swanlab_mask_value.py

> 代码位置：[`inference/batch_infer_qa_swanlab_mask_value.py`](../../inference/batch_infer_qa_swanlab_mask_value.py)

## 功能与业务价值

**仅预测 Value 的 SwanLab 推理。** 组合 Value 掩码 Prompt 与 SwanLab 批量推理能力。

**业务价值：** 在结构已知实验中同步观察逐样本表现与累计指标，便于与完整配置生成实验做公平对照。

## 核心逻辑

1. 使用 `build_key_skeleton` 生成嵌套 Key 骨架。
2. 复用 SwanLab 推理脚本的调用、评估、表格和错误处理。
3. 命令行参数与 `batch_infer_qa_swanlab.py` 完全一致。

## 代码实现说明

- 该入口不重新实现推理循环，而是在运行前把 SwanLab 基础脚本使用的 Prompt 构造器替换为 `batch_infer_qa_mask_value.build_user_prompt`。
- 目标答案先转成完整嵌套 Key 骨架，所有叶子值被占位符隐藏；模型仍返回完整 JSON，因此单样本指标、micro/macro 累计和表格字段无需修改。
- 输入顺序、错误定义、结果路径、SwanLab step 和表格上传间隔均与 `batch_infer_qa_swanlab.py` 相同。实验对比时应使用相同 split、模型和采样参数，只改变任务入口。

## 参数

| 参数 | 说明 | 默认值或约束 |
|---|---|---|
| `--qa-root` | QA 数据根目录，用于读取 prompt、input、output 或关联同名样本。 | 默认：`DEFAULT_QA_ROOT` |
| `--output-root` | 本脚本产物输出目录。 | 默认：`DEFAULT_OUTPUT_ROOT` |
| `--split` | 单个数据划分，例如 `train` 或 `val`。 | 默认：`'train'` |
| `--tasks` | 逗号分隔的任务目录，例如 `node_config_qa,device_config_qa`。 | 默认：`'device_config_qa,node_config_qa'` |
| `--base-url` | OpenAI-compatible Chat Completions 服务地址。 | 默认：`DEFAULT_BASE_URL` |
| `--api-key` | API 密钥；本地 vLLM 通常可使用占位值。 | 默认：`DEFAULT_API_KEY` |
| `--model` | 服务端暴露的模型名称，必须与部署配置一致。 | 默认：`DEFAULT_MODEL` |
| `--temperature` | 采样温度。 | 默认：`DEFAULT_TEMPERATURE` |
| `--progress-interval` | 每处理多少个文件打印一次进度；非正数通常表示关闭周期打印。 | 默认：`DEFAULT_PROGRESS_INTERVAL` |
| `--limit` | 最多处理的文件数；`0` 表示不限制。 | 默认：`0` |
| `--enable-thinking` | 启用 Qwen thinking；默认关闭 thinking。 | 开关参数 |
| `--swanlab-project` | SwanLab 项目名。 | 默认：`DEFAULT_SWANLAB_PROJECT` |
| `--swanlab-experiment` | SwanLab 实验名。 | 默认：`DEFAULT_SWANLAB_EXPERIMENT` |
| `--swanlab-mode` | SwanLab 运行模式，例如 `cloud` 或本地模式。 | 默认：`DEFAULT_SWANLAB_MODE` |
| `--eval-metric-mode` | 累计 eval 口径：`micro` 汇总计数后计算，`macro` 对有效样本指标求平均。 | 默认：`DEFAULT_EVAL_METRIC_MODE`；可选：`['micro', 'macro']` |
| `--sample-table-log-interval` | 每累计多少个样本重新上传一次样本表。 | 默认：`DEFAULT_SAMPLE_TABLE_LOG_INTERVAL` |



## 输入与输出

**主要输出：**

- 本地结果和 SwanLab 实验结构与 `batch_infer_qa_swanlab.py` 相同。

**统计口径与异常：**

- 扫描文件数、模型错误数、解析/评估错误数和有效评估数应分开理解，指标分母以代码实际纳入的有效对象为准。
- 推理结果目录属于实验产物，不应覆盖 QA 数据源；改变预测字段名时需同步检查 `pred-keys`。


## 相关文档

- [batch_infer_qa_mask_value.py](batch_infer_qa_mask_value.md)
- [batch_infer_qa_swanlab.py](batch_infer_qa_swanlab.md)

[返回 inference 脚本索引](README.md)
