# build_structure_hints_from_csv.py

> 代码位置：[`inference/build_structure_hints_from_csv.py`](../../inference/build_structure_hints_from_csv.py)

## 功能与业务价值

**从结构分布生成 Prompt 提示。** 读取结构分布 CSV，把高频 Path 还原为带类型占位符的嵌套 JSON，并生成 `TOP_LEVEL_KEY_STRUCTURE_HINTS` Python 文件。

**业务价值：** 把离线结构统计转化为可直接用于推理 Prompt 的兜底先验，减少缺少同名上下文时的结构幻觉。

## 核心逻辑

1. 筛选 `sample_count` 大于配置阈值的结构，可按 split/task 过滤。
2. 解析对象路径与数组 `[]`，合并为树形结构。
3. 按叶子类型生成 `<string>`、`<number>`、`<boolean>` 等占位值。
4. 同一顶层 Key 保留多个满足阈值的常见结构。

## 代码实现说明

- 输入是 `analyze_output_structures.py` 产生的 distribution CSV。代码先按 `sample_count > min-sample-count` 筛选，并可限制 split/task，避免将极少出现的长尾 Schema 注入 Prompt。
- Path 解析器识别 `/` 分隔字段、JSON Pointer 转义和数组 `[]`。每条路径插入树节点，多条路径共同恢复对象和列表嵌套关系。
- 叶子根据统计中记录的 JSON 类型生成 `<string>`、`<number>`、`<boolean>`、`<null>` 等占位符；占位符只表示结构和类型，不包含训练答案真实值。
- 输出 Python 文件按顶层 Key 建立列表，同一 Key 可有多个高频结构。生成内容需要人工审查后放入推理脚本的 `TOP_LEVEL_KEY_STRUCTURE_HINTS`，不会自动改写 Prompt 源码。

## 参数

| 参数 | 说明 | 默认值或约束 |
|---|---|---|
| `--input-csv` | 控制该脚本对应处理行为。 | 默认：`DEFAULT_INPUT_CSV` |
| `--output-file` | 控制该脚本对应处理行为。 | 默认：`DEFAULT_OUTPUT_FILE` |
| `--min-sample-count` | Keep rows whose sample_count is strictly greater than this value. Default: 5. | 默认：`DEFAULT_MIN_SAMPLE_COUNT` |
| `--splits` | 逗号分隔的数据划分，例如 `train,val`。 | 默认：`''` |
| `--tasks` | 逗号分隔的任务目录，例如 `node_config_qa,device_config_qa`。 | 默认：`''` |


### 关键默认值

| 常量 | 当前代码表达式 |
|---|---|
| `DEFAULT_INPUT_CSV` | `Path('output-structure-analysis/output_structure_distribution.csv')` |
| `DEFAULT_OUTPUT_FILE` | `Path('top_level_key_structure_hints.py')` |
| `DEFAULT_MIN_SAMPLE_COUNT` | `5` |
| `VALUE_PLACEHOLDER` | `'<VALUE>'` |


## 输入与输出

**主要输出：**

- 默认生成包含 `TOP_LEVEL_KEY_STRUCTURE_HINTS` 的 Python 文件。

**统计口径与异常：**

- 扫描文件数、模型错误数、解析/评估错误数和有效评估数应分开理解，指标分母以代码实际纳入的有效对象为准。
- 推理结果目录属于实验产物，不应覆盖 QA 数据源；改变预测字段名时需同步检查 `pred-keys`。


## 相关文档

- [analyze_output_structures.py](analyze_output_structures.md)
- [batch_infer_qa.py](batch_infer_qa.md)

[返回 inference 脚本索引](README.md)
