# upload_macro_metrics_swanlab.py

> 代码位置：[`inference/upload_macro_metrics_swanlab.py`](../../inference/upload_macro_metrics_swanlab.py)

## 功能与业务价值

**历史推理结果 Macro 指标上传。** 独立读取已有推理 JSON，逐样本重算指标，并在新 SwanLab 实验中记录 sample 与截至当前 step 的 macro eval 曲线。

**业务价值：** 用于把早期采用 micro 口径的推理结果转换为样本等权的 macro 观察视角，不依赖原推理 run。

## 核心逻辑

1. 按文件名字典序扫描既有结果。
2. 解析预测和答案，错误样本记录为 sample 错误但不进入有效样本均值。
3. 每个有效样本记录 `sample/*`，累计列表计算 `eval/*` 的算术平均。
4. 创建新 SwanLab 实验，不恢复旧实验。

## 代码实现说明

- 程序独立扫描已有推理结果，不调用 `batch_evaluate_qa.py` 的命令参数，也不依赖已有 SwanLab run。默认按 split/task 及路径字典序确定 step。
- 每个结果读取预测与 `answer` 后调用统一指标模块。成功样本先记录当前 `sample/*`，再加入历史有效指标列表，并对列表内每个指标做算术平均得到当前 `eval/*`。
- 文件存在 API error、缺预测、JSON 解析失败或评估异常时会打印/记录失败状态，但不会加入 macro 均值列表。因此 eval 横轴 step 是已处理文件序号，均值分母是截至当前的有效评估样本数。
- 每次运行创建新的 SwanLab 实验，适合把同一批历史结果以 macro 口径重新观察，不会覆盖原推理实验。

## 参数

| 参数 | 说明 | 默认值或约束 |
|---|---|---|
| `--result-root` | 推理结果根目录，目录下按 split/task 保存逐样本 JSON。 | 默认：`DEFAULT_RESULT_ROOT` |
| `--splits` | 逗号分隔的数据划分，例如 `train,val`。 | 默认：`DEFAULT_SPLITS` |
| `--tasks` | 逗号分隔的任务目录，例如 `node_config_qa,device_config_qa`。 | 默认：`DEFAULT_TASKS` |
| `--pred-keys` | 按优先级查找预测内容的字段名列表，兼容历史命名。 | 默认：`DEFAULT_PRED_KEYS` |
| `--gold-key` | 结果 JSON 中监督答案字段名。 | 默认：`DEFAULT_GOLD_KEY` |
| `--array-mode` | JSON 数组路径口径：`wildcard` 统一为 `[]`，`index` 保留下标。 | 默认：`'wildcard'`；可选：`['wildcard', 'index']` |
| `--limit` | 最多处理的文件数；`0` 表示不限制。 | 默认：`0` |
| `--progress-interval` | 每处理多少个文件打印一次进度；非正数通常表示关闭周期打印。 | 默认：`DEFAULT_PROGRESS_INTERVAL` |
| `--swanlab-project` | SwanLab 项目名。 | 默认：`DEFAULT_SWANLAB_PROJECT` |
| `--swanlab-experiment` | SwanLab 实验名。 | 默认：`DEFAULT_SWANLAB_EXPERIMENT` |
| `--swanlab-mode` | SwanLab 运行模式，例如 `cloud` 或本地模式。 | 默认：`DEFAULT_SWANLAB_MODE` |


### 关键默认值

| 常量 | 当前代码表达式 |
|---|---|
| `DEFAULT_RESULT_ROOT` | `Path('inference-results')` |
| `DEFAULT_SPLITS` | `'val'` |
| `DEFAULT_TASKS` | `'node_config_qa'` |
| `DEFAULT_PRED_KEYS` | `'model-output,model_output,model-ouput'` |
| `DEFAULT_GOLD_KEY` | `'answer'` |
| `DEFAULT_PROGRESS_INTERVAL` | `500` |
| `DEFAULT_SWANLAB_PROJECT` | `'config-generation'` |
| `DEFAULT_SWANLAB_EXPERIMENT` | `'offline-macro-metrics'` |
| `DEFAULT_SWANLAB_MODE` | `'cloud'` |


## 输入与输出

**主要输出：**

- 主要产物为新的 SwanLab 实验曲线，不修改原结果 JSON。

**统计口径与异常：**

- 扫描文件数、模型错误数、解析/评估错误数和有效评估数应分开理解，指标分母以代码实际纳入的有效对象为准。
- 推理结果目录属于实验产物，不应覆盖 QA 数据源；改变预测字段名时需同步检查 `pred-keys`。


## 相关文档

- [metric.py](metric.md)
- [swanlab_utils.py](swanlab_utils.md)

[返回 inference 脚本索引](README.md)
