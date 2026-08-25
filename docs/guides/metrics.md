# 配置生成指标

指标统一由 `inference/metric.py` 定义。JSON 对象展开为路径 Counter；数组在默认 `wildcard` 模式下使用 `[]`，在 `index` 模式下保留具体下标。

## 核心指标

| 指标 | 定义 |
|---|---|
| `field_path_precision` | 正确预测字段路径数 / 预测字段路径总数，低值表示额外结构或幻觉字段多。 |
| `field_path_recall` | 正确预测字段路径数 / 答案字段路径总数，低值表示结构缺失多。 |
| `field_path_f1` | 字段路径 Precision 与 Recall 的调和平均。 |
| `leaf_triple_precision` | 正确 `(path, JSON type, value)` 数 / 预测叶子三元组总数。 |
| `leaf_triple_recall` | 正确叶子三元组数 / 答案叶子三元组总数。 |
| `leaf_triple_f1` | 叶子三元组 Precision 与 Recall 的调和平均，同时约束路径、类型和值。 |
| `value_accuracy` | 值正确数 / 已匹配叶子路径数；只在路径匹配后判断值。 |
| `hallucinated_rate` | 预测中超出答案的字段路径数 / 预测字段路径总数。 |
| `missing_rate` | 答案中未被预测的字段路径数 / 答案字段路径总数。 |

路径和三元组都采用多重集合匹配，重复出现的数组元素会计数，不是简单集合去重。

## Micro 与 Macro

- `micro`：先累计所有有效样本的 correct、pred total、gold total，再计算 Precision/Recall/F1。字段多的样本权重更大。
- `macro`：先计算每个有效样本的指标，再对样本做算术平均。每个样本权重相同。

因此，按顶层 Key 的 F1 乘样本数后加权平均通常不等于全局 micro F1。错误或无法解析的样本是否进入分母，应查看具体脚本的 `evaluated_files` 逻辑；当前通用离线评估仅将成功解析且完成评估的样本加入数值累计。
