# task_specs.py

**源码：** [`task_specs.py`](../../infer_and_eval/task_specs.py)

[返回代码索引](README.md)

## 模块职责

该文件是统一推理评估框架的任务注册表。它不读取数据、不调用模型、也不计算指标，只负责描述“任务名称对应哪个数据目录、哪种答案结构和哪个答案字段”。

集中注册的目的是让推理和评估入口保持通用，避免为七个任务复制七套批处理代码。

## `TaskSpec` 数据结构

```python
@dataclass(frozen=True)
class TaskSpec:
    name: str
    dataset_root: Path
    result_root: Path
    evaluation_root: Path
    answer_kind: str
    answer_field: str | None = None
```

字段含义：

| 字段 | 作用 |
|---|---|
| `name` | 任务唯一标识，对应命令行 `--task` |
| `dataset_root` | 默认任务数据集根目录 |
| `result_root` | 默认 vLLM 推理结果目录 |
| `evaluation_root` | 默认本地评估输出目录 |
| `answer_kind` | 答案结构类别，驱动推理校验和评估分派 |
| `answer_field` | `node_set` 类型在答案中的节点数组字段 |

使用 `frozen=True` 后，注册完成的配置不能在运行过程中被意外修改。

## `_spec()` 工厂函数

调用方只需要提供任务名称、数据集目录和答案类型，工厂函数统一推导：

```text
result_root     = vllm-results/<task_name>
evaluation_root = vllm-results/<task_name>-evaluation
```

这保证七个任务采用一致的默认结果目录规则。

## 七任务注册关系

| 中文任务 | `--task` | 数据集目录 | `answer_kind` | `answer_field` |
|---|---|---|---|---|
| 节点最短路径查询 | `shortest_path` | `shortest_path_dataset` | `extended_path` | 无 |
| 上行节点路径查询 | `uplink_node_path` | `uplink_node_path_dataset` | `path` | 无 |
| 可达下游终端节点 | `downstream_reachable_terminal` | `downstream_reachable_terminal_dataset` | `node_set` | `downstream_terminal_node_ids` |
| 节点故障约束路径查询 | `node_failure_reroute` | `node_failure_reroute_dataset` | `path` | 无 |
| 指定CORE约束的AP间最短路径查询 | `ap_pair_via_core_path` | `ap_pair_via_core_path_dataset` | `path` | 无 |
| vlan约束的交换机路径查询 | `vlan_constrained_shortest_path` | `vlan_constrained_shortest_path_dataset` | `path` | 无 |
| 故障影响AP节点 | `node_failure_ap_impact` | `node_failure_ap_impact_dataset` | `node_set` | `impacted_ap_ids` |

## 三类答案

### `extended_path`

用于节点最短路径查询，模型答案必须包含：

```text
path_length
paths
path_role_sequences
path_device_names
```

评估除路径指标外，还检查路径合法性、角色序列和设备名称序列。

### `path`

用于只要求跳数和路径的任务：

```text
path_length
paths
```

任务条件如故障节点、指定 CORE 或 VLAN 保存在输入样本顶层，不要求模型重复预测。

### `node_set`

用于返回节点 ID 集合的任务。`answer_field` 指定真正需要比较的数组，例如：

```text
impacted_ap_ids
downstream_terminal_node_ids
```

## `get_task_spec()`

根据命令行任务名称从 `TASK_SPECS` 取出配置。未知名称会抛出明确错误；通常 argparse 的 `choices` 会更早阻止非法任务名。

推理和评估入口都使用同一函数，因此两个阶段不会对同一任务采用不同目录或答案类型。

## 增加新任务

如果新任务可以复用现有答案类型，只需要增加一条注册：

```python
"new_task": _spec(
    "new_task",
    "new_task_dataset",
    "path",
)
```

如果是新的节点集合字段，应设置 `answer_field`。如果答案结构不属于三类现有类型，则必须同步扩展推理校验、指标名称和评估器，否则注册后无法正确处理。

## 路径一致性注意事项

数据集构造脚本的输出目录必须与这里的 `dataset_root` 一致。若构造时使用了其他 `--output-root`，推理时应显式传入 `--dataset-root`，或更新注册表默认目录。

