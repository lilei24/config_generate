# batch_evaluate.py

**源码：** [`batch_evaluate.py`](../../infer_and_eval/batch_evaluate.py)

[返回代码索引](README.md)

## 模块职责

该文件是七类任务共用的独立评估入口。它不调用模型，而是读取已经落盘的推理结果，完成：

- 单样本指标计算。
- `zero` 或 `exclude` 错误样本策略。
- 截至当前步骤的累计宏平均。
- SwanLab 数值曲线和样本详情表上传。
- 本地逐样本、错误和汇总文件输出。

## 主要常量

`DETAIL_NAMES` 定义所有评估器共用的计数列：

```text
predicted_count
gold_count
true_positive
false_positive
false_negative
malformed_count
```

这些列用于解释 Precision、Recall 和 F1，不直接作为 SwanLab 主指标。

## 主要函数

### `parse_args()`

解析任务、结果目录、split、错误策略和 SwanLab 参数。`task` 决定指标集合和评估器，`result-root` 与 `output-dir` 未提供时使用 `TaskSpec` 默认值。

`error-policy` 只有两个合法值：

- `zero`：失败样本以全零指标进入平均。
- `exclude`：失败样本不进入平均分母。

### `init_swanlab()`

在未指定 `disable-swanlab` 时延迟导入并初始化 SwanLab。实验配置记录：

- 任务名称。
- 结果目录和 split。
- 错误策略。
- `running macro average` 聚合口径。
- 当前任务全部指标名称。

### `build_table_row()`

生成 `sample/details` 表格的一行。表格列为：

```text
json_name
context
answer
model-output
```

`context` 从完整结果中排除 `task_answer`、`model-output` 和推理元数据，避免同一内容重复出现在多列。JSON 使用缩进格式转换为字符串，便于在 SwanLab 中查看。

### `log_sample_table()`

使用 `swanlab.echarts.Table` 在评估结束后一次性记录 `sample/details`。若当前 SwanLab 版本没有 `echarts.Table`，脚本明确报错，而不是静默丢失样本详情。

### `main()`

评估主流程：

1. 读取任务配置，解析结果和本地输出目录。
2. 按 split 与相对路径字典序扫描结果 JSON。
3. 调用 `metric_names(spec)` 初始化当前任务指标。
4. 对每个文件读取 JSON，并通过 `inference_success()` 判断模型是否成功返回。
5. 成功返回时调用 `evaluate_document()` 计算单样本指标和计数详情。
6. 异常或失败样本保持全零指标，并记录错误原因。
7. 根据 `error-policy` 决定当前样本是否加入 `metric_sums` 和 `averaging_count`。
8. 向 SwanLab 记录 `sample/<metric>` 和 `eval/<metric>`。
9. 累积样本详情表、本地 CSV 行和错误行。
10. 循环结束后上传 `sample/details`，再关闭 SwanLab。
11. 计算最终宏平均并写入本地文件。

## 累计宏平均

每个任务指标先在单个样本内计算，然后累计：

```text
eval/metric = 已纳入样本的单样本 metric 之和 / averaging_count
```

这不是把所有样本的 TP、FP、FN 合并后重新计算的 micro 指标。

在 `zero` 模式下，`averaging_count` 等于已处理样本数；在 `exclude` 模式下，它只等于成功完成评估的样本数。

## SwanLab 内容

### `sample/*`

当前单个样本的数值指标。`exclude` 模式下失败样本不记录虚假的零分 sample 点。

### `eval/*`

截至当前文件的累计宏平均指标。曲线横轴 step 仍按结果文件处理顺序递增。

### `sample/details`

评估结束时上传的完整样本详情表，用于将文件名、上下文、标准答案和模型答案对应起来。

## 本地输出

### `per_sample_metrics.csv`

包含：

- split 和相对文件名。
- `model_returned`。
- `evaluation_success`。
- `included_in_average`。
- 错误原因。
- TP、FP、FN 等计数。
- 当前任务所有单样本指标。

### `evaluation_errors.csv`

只包含存在错误原因的样本，便于独立排查服务失败、解析失败和文件损坏。

### `evaluation_summary.json`

记录任务、路径、split、错误策略、总数、成功数、失败数、实际平均分母、成功率和最终指标。

## 错误处理边界

- 推理元数据为失败：按错误策略计零或排除。
- `model-output` 不是对象：视为推理失败。
- 结果 JSON 损坏或评估器抛出异常：记录为评估失败。
- 模型答案结构正确但内容错误：正常计算低分，不记为错误文件。

## 扩展注意事项

- 新增指标应先在 `evaluation_common.py` 返回，再由 `metric_names()`声明，避免 CSV 和 SwanLab 字段不一致。
- 如果样本数量很大，`sample/details` 会在内存中累积完整上下文；必要时可增加关闭表格或限制行数的参数。
- 评估实验需要比较多个模型时，应使用不同 `swanlab-experiment`，本地输出目录也应分开。

