# batch_infer_qa_mask_value.py

> 代码位置：[`inference/batch_infer_qa_mask_value.py`](../../inference/batch_infer_qa_mask_value.py)

## 功能与业务价值

**仅预测 Value 的批量推理。** 在标准批量推理上提供目标答案的完整嵌套 Key 骨架，只要求模型补全不同 JSON 类型的 Value。

**业务价值：** 用于对比“同时生成结构和值”与“结构已知、仅生成值”的任务难度，隔离结构幻觉对结果的影响。

## 核心逻辑

1. 递归遍历监督答案，保留对象 Key、数组层级和数组元素数量。
2. 把所有叶子值替换为 `<VALUE_TO_PREDICT>`，形成不泄露真实值的目标骨架。
3. Prompt 强制保持 Key 和层级不变，并按 string、number、boolean、null、object、array 的合法 JSON 类型补值。
4. 复用 `batch_infer_qa.py` 的文件扫描、模型调用、错误记录和结果写入逻辑。

## 代码实现说明

### Key 骨架生成

- `build_key_skeleton` 递归遍历 `output`：字典保留全部 Key，列表保留原有元素与嵌套层次，所有非 dict/list 叶子统一替换为 `<VALUE_TO_PREDICT>`。
- 该处理不会根据原值类型生成不同占位符，因此占位符本身不泄露 string、number、boolean 或 null；模型需要结合字段语义和上下文判断最终 JSON 类型。
- 数组的长度和每个元素的 Key 仍来自答案，因此本实验固定了目标结构，主要测量 Value 推断能力，不应与完整结构生成任务直接混为同一难度口径。

### Prompt 约束与流程复用

- Prompt 同时提供网络拓扑上下文、原任务问题和 Key 骨架，并明确禁止新增、删除、改名或移动任何 Key。
- 最终回答仍要求返回完整 `{key: value}` JSON，而不是只返回值列表，保证结果可以继续复用原有 `metric.py` 和离线分析脚本。
- `run` 在执行前将基础模块的 `build_user_prompt` 替换为当前实现，文件发现、OpenAI 调用、thinking 控制、错误日志和输出路径全部复用 `batch_infer_qa.py`。

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


### 关键默认值

| 常量 | 当前代码表达式 |
|---|---|
| `VALUE_PLACEHOLDER` | `'<VALUE_TO_PREDICT>'` |


## 输入与输出

**主要输出：**

- 输出目录和结果结构与 `batch_infer_qa.py` 相同。

**统计口径与异常：**

- 扫描文件数、模型错误数、解析/评估错误数和有效评估数应分开理解，指标分母以代码实际纳入的有效对象为准。
- 推理结果目录属于实验产物，不应覆盖 QA 数据源；改变预测字段名时需同步检查 `pred-keys`。


## 相关文档

- [batch_infer_qa.py](batch_infer_qa.md)
- [batch_infer_qa_swanlab_mask_value.py](batch_infer_qa_swanlab_mask_value.md)

[返回 inference 脚本索引](README.md)
