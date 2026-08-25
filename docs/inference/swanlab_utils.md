# swanlab_utils.py

> 代码位置：[`inference/swanlab_utils.py`](../../inference/swanlab_utils.py)

## 功能与业务价值

**SwanLab 公共工具。** 集中封装 SwanLab 导入、运行配置、指标命名、micro/macro 累计、样本表格和结束逻辑。

**业务价值：** 保证多个推理与评估入口上传相同字段，减少实验之间因日志实现差异造成的不可比。

## 核心逻辑

1. 记录 Python 版本、Git commit、脚本名和命令行参数。
2. 将指标映射为稳定的 `field_path/*`、`leaf_triple/*` 等名称。
3. macro 对有效样本指标求算术平均；micro 先累计正确数和预测/答案总数再计算。
4. 统一样本表头和 JSON 可读格式。

## 参数

该文件是公共库模块，没有独立命令行参数，供其他脚本导入调用。

## 运行方式

该模块由同目录脚本导入，不建议作为独立命令执行。

## 输入与输出

**主要输出：**

- 该文件是库模块，不直接写文件。

**统计口径与异常：**

- 扫描文件数、模型错误数、解析/评估错误数和有效评估数应分开理解，指标分母以代码实际纳入的有效对象为准。
- 推理结果目录属于实验产物，不应覆盖 QA 数据源；改变预测字段名时需同步检查 `pred-keys`。

## 关键接口

| 接口 | 类型 | 职责 |
|---|---|---|
| `import_swanlab` | function | 实现该脚本的核心处理步骤。 |
| `current_git_commit` | function | 实现该脚本的核心处理步骤。 |
| `base_runtime_config` | function | 实现该脚本的核心处理步骤。 |
| `metric_log_values` | function | 实现该脚本的核心处理步骤。 |
| `macro_metric_log_values` | function | 实现该脚本的核心处理步骤。 |
| `running_eval_log_values` | function | 实现该脚本的核心处理步骤。 |
| `sample_table_headers` | function | 实现该脚本的核心处理步骤。 |
| `sample_table_row` | function | 实现该脚本的核心处理步骤。 |
| `json_dumps` | function | 实现该脚本的核心处理步骤。 |
| `make_table` | function | 实现该脚本的核心处理步骤。 |
| `finish_swanlab` | function | 实现该脚本的核心处理步骤。 |

[返回 inference 脚本索引](README.md)
