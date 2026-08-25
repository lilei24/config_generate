# metric.py

> 代码位置：[`inference/metric.py`](../../inference/metric.py)

## 功能与业务价值

**配置 JSON 结构与值指标。** 把预测和答案展开为 JSON 路径多重集合，统一计算顶层配置、字段路径、叶子三元组、值准确率及幻觉/缺失字段指标。

**业务价值：** 为在线推理、离线评估和因素分析提供唯一指标定义，避免不同脚本采用不一致的路径与分母。

## 核心逻辑

1. 递归遍历 dict/list；数组可统一表示为 `[]`，也可保留下标。
2. 字段路径按 Counter 多重集合匹配，重复数组结构不会被错误去重。
3. 叶子三元组由 `(path, JSON type, normalized value)` 组成。
4. 值准确率只在匹配叶子路径内比较值；幻觉率以预测字段数为分母，缺失率以答案字段数为分母。
5. `evaluate_json` 汇总所有指标，供其他脚本直接调用。

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
| `load_json` | function | 支持传入 dict/list 或 JSON 字符串。 |
| `json_type` | function | 返回 JSON 类型名。 |
| `normalize_value` | function | 把叶子值标准化成可比较、可哈希的字符串。 |
| `is_leaf` | function | JSON 叶子节点：非 dict、非 list。 |
| `escape_path_key` | function | 简单处理 JSON Pointer 中的特殊字符。 |
| `counter_prf` | function | 基于 Counter 的 Precision / Recall / F1。 |
| `collect_json_features` | function | 从 JSON 中抽取： |
| `top_level_config_metric` | function | 指标 1：顶层配置名准确率。 |
| `value_accuracy_metric` | function | 指标 4：值准确率。 |
| `hallucination_missing_metric` | function | 指标 6：幻觉字段 / 缺失字段。 |
| `evaluate_json` | function | 总评估函数。 |
| `evaluate_record` | function | 如果你的数据格式是： |
| `pretty_print_metrics` | function | 简单打印核心指标。 |

[返回 inference 脚本索引](README.md)
