# evaluation_common.py

**源码：** [`evaluation_common.py`](../../infer_and_eval/evaluation_common.py)

[返回代码索引](README.md)

## 模块职责

该文件实现与任务批处理无关的评估算法：

- 根据任务配置返回指标名称。
- 规范化路径和节点 ID 集合。
- 计算 Precision、Recall、F1 和计数详情。
- 评价普通路径、扩展路径和节点集合答案。
- 扫描结果文件并兼容推理状态字段。

`batch_evaluate.py` 负责循环、平均和 SwanLab；该模块只负责“一个结果 JSON 应得到哪些指标”。

## `EvaluationResult`

```python
@dataclass(frozen=True)
class EvaluationResult:
    metrics: dict[str, float]
    details: dict[str, int]
```

- `metrics`：需要进入单样本曲线和宏平均的浮点指标。
- `details`：预测数、答案数、TP、FP、FN 和非法元素数等解释性计数。

## 指标名称分派

### `metric_names(spec)`

根据 `answer_kind` 和 `answer_field` 返回稳定有序的指标元组：

- `extended_path`：八个最短路径、合法性、角色和设备名称指标。
- `path`：跳数准确率和路径 Precision、Recall、F1。
- `node_set + impacted_ap_ids`：受影响 AP Precision、Recall、F1。
- 其他当前节点集合任务：终端 Precision、Recall、F1 和完全匹配率。

返回顺序直接影响 CSV 列顺序和 SwanLab 指标初始化。

## 路径规范化

### `normalize_paths()`

将路径数组转换为 `set[tuple[str, ...]]`：

- 完整节点序列作为一个集合元素。
- 非数组、空路径或含非法节点 ID 的路径记为 malformed。
- 重复路径只保留一份，同时把重复数量计入 malformed。
- 返回去重集合、原始预测数量和非法数量。

因此路径命中要求整条节点 ID 序列完全一致，局部节点或局部边相同不算命中。

## 通用 Precision、Recall、F1

### `prf(predicted, gold, malformed)`

计算：

```text
TP = |predicted ∩ gold|
FP = |predicted - gold| + malformed
FN = |gold - predicted|

Precision = TP / (TP + FP)
Recall    = TP / (TP + FN)
F1        = 2PR / (P + R)
```

分母为 0 时指标取 0。非法或重复预测进入 FP，防止模型通过重复正确路径获得不合理结果。

## 图结构与路径合法性

### `build_graph()`

从结果 JSON 的 `nodes` 和 `links` 构建节点集合与邻接表。`directed=false` 时双向加入边。

### `path_is_valid()`

用于节点最短路径查询的 `path_valid_rate`，检查：

- 路径节点数等于标准答案最短跳数加一。
- 首节点与任务源节点一致。
- 末节点与任务目标节点一致。
- 所有节点存在于拓扑。
- 每对相邻节点在邻接表中存在链路。

该指标验证物理可执行性，但不替代路径集合 Precision 和 Recall。

## 角色与设备名称

### `aligned_sequence_accuracy()`

1. 使用标准答案中的完整节点路径作为键，建立路径到标准序列的映射。
2. 遍历模型预测路径及其角色或名称序列。
3. 预测路径不存在于标准答案时，其序列位置不计正确。
4. 对能够匹配的路径按位置比较字符串。
5. 正确位置数除以模型提交的序列位置总数。

路径漏报主要由 `path_recall` 体现；角色和设备名称准确率重点衡量模型已提交路径上的语义对齐。

## 路径任务评价

### `evaluate_path(document, extended)`

公共四项指标：

- `path_length_accuracy`：预测跳数与标准跳数完全相等为 1，否则为 0。
- `path_precision`：预测完整路径中正确路径的比例。
- `path_recall`：标准完整路径被找回的比例。
- `path_f1`：路径 Precision 与 Recall 的调和平均。

`extended=True` 时增加：

- `path_valid_rate`。
- `path_exact_match_rate`。
- `role_accuracy`。
- `device_name_accuracy`。

`path_exact_match_rate` 只有在跳数正确、路径集合完全相同且没有非法或重复路径时为 1。

值得注意：模型可以找对路径但答错 `path_length`。这种情况下路径 Precision、Recall、F1 可以为 1，而 `path_length_accuracy` 为 0，这正是把不同错误维度分开评价的设计目的。

## 节点集合评价

### `normalize_ids()`

将节点数组转换为集合。空字符串、非字符串和重复节点记为 malformed。

### `evaluate_node_set()`

根据 `TaskSpec.answer_field` 同时读取标准和预测节点集合：

- 故障影响AP节点输出 `impacted_ap_precision/recall/f1`。
- 可达下游终端节点输出 `terminal_precision/recall/f1` 和 `terminal_exact_match_rate`。

完全匹配要求预测集合与标准集合相同且没有非法或重复元素，节点顺序不影响结果。

## 总评估分派

### `evaluate_document()`

```text
extended_path -> evaluate_path(..., extended=True)
path          -> evaluate_path(..., extended=False)
node_set      -> evaluate_node_set(...)
```

该函数是 `batch_evaluate.py` 调用的统一单样本入口。

## 结果文件扫描

### `collect_result_files()`

- 输入是单个 JSON 时直接返回一个 `single` 样本。
- 输入是目录时按 `train`、`val` 或 `all` 查找 split。
- split 目录不存在时立即报错。
- 每个 split 内递归扫描 JSON 并按相对路径字典序返回。

批次级 `batch_summary.json` 位于 split 目录之外，因此正常目录结构下不会被误当作样本。

## 推理状态识别

### `inference_success()`

优先读取新框架的 `inference_metadata`，同时兼容旧结果中的 `vllm-run`：

- 元数据缺失：失败。
- `success` 不为 `true`：失败并返回记录的错误原因。
- `model-output` 不是对象：失败。
- 三项均满足：允许进入指标计算。

## CSV 输出

`write_csv()` 根据调用方传入的列顺序写出 UTF-8 BOM CSV，确保逐样本文件和错误文件保持稳定字段顺序。

## 扩展注意事项

- 新任务若复用完整路径集合，可以直接使用 `path`。
- 新节点集合任务若需要不同指标前缀，应在 `metric_names()` 和 `evaluate_node_set()` 同步增加分支。
- 指标名称和实际返回字典必须完全一致，否则批处理累计时会出现缺失字段。
- 若未来需要 micro 指标，应单独累计 TP、FP、FN 后计算，不能把当前单样本 F1 平均误称为 micro F1。

