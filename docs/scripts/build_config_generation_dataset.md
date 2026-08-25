# build_config_generation_dataset.py

> 代码位置：[`scripts/build_config_generation_dataset.py`](../../scripts/build_config_generation_dataset.py)

## 功能与业务价值

该脚本从原始网络拓扑 JSON 构造配置生成 QA 数据集。每张有效拓扑最多生成一个节点配置样本和一个设备组配置样本，并分别写入 `node_config_qa` 与 `device_config_qa`。

它将完整拓扑上下文、待预测问题和标准答案组织为统一 JSON，为后续 vLLM、外部 API、SwanLab 推理及离线指标分析提供稳定输入。

## 核心逻辑

1. 按 `train`、`val` 等 split 递归扫描原始 JSON，并保持文件名字典序。
2. 分别收集节点配置和设备组配置的全部可预测顶层 Key。
3. 使用固定随机种子从两类候选池中各选择一个目标。
4. 深拷贝原图，只从 Input 删除当前目标 Key，保留节点、链路、设备组及其他未遮挡配置。
5. 将目标配置对象写入 `output`，将目标位置与构造策略写入 `metadata`。
6. 两类任务分别输出到独立目录，异常和汇总写入根目录报告。

## 代码实现说明

### 目标候选收集

- 节点配置优先读取 `nodes[].configs[]`，并兼容历史字段 `nodes[].config[]`；设备组配置读取 `deviceGroups[].configs[]`。
- 配置列表中的每个字典可以包含一个或多个顶层 Key。代码不会假设“一项配置只能有一个 Key”，而是把每个 Key 分别转换为 `ConfigTarget` 候选。
- 节点候选记录 node 数组位置、配置列表字段名、配置项位置、顶层 Key 和 `node_id`。设备组候选额外记录设备组名称与类型，便于样本追溯。
- 节点候选池与设备组候选池相互独立；某一类没有候选时只跳过该类，不影响另一类样本生成。

### 选择与遮挡策略

- `TargetSelector` 只负责从有序候选池选择目标，当前注册策略为 `random`。随机数生成器使用 `--seed` 初始化，因此相同数据、扫描顺序和参数会选中相同目标。
- `MaskStrategy` 只负责修改 Input，当前策略为 `remove_random_key`。实现先深拷贝原图，再从目标配置字典中删除选中的顶层 Key，不会修改标准答案来源。
- 如果删除后目标配置字典变为空字典，代码会从 `config/configs` 列表中移除整个空项；同一列表中的其他配置和目标字典中的其他顶层 Key 保留。
- 选择器和遮挡策略通过注册表解耦，后续可以增加靠前/靠后 Key 选择或占位符遮挡，而不修改数据集主循环。

### QA 内容与目录

单个输出样本包含：

- `prompt`：说明预测节点配置或全局设备组配置，并包含目标顶层配置名。
- `input`：除当前目标 Key 外的完整图 JSON，原字段顺序保持不变。
- `output`：只包含被隐藏的一个顶层 Key 及其完整 Value。
- `metadata`：记录源文件、split、selector、mask strategy 和目标定位信息，不作为模型输入。

输出目录为 `<output-dir>/<split>/node_config_qa/` 和 `<output-dir>/<split>/device_config_qa/`，文件名与源 JSON 一致。路径冲突、坏 JSON 和其他构造问题写入 `build_issues.jsonl`；扫描数、候选缺失数和两类已生成样本数写入 `build_summary.json`。

## 参数

| 参数 | 默认值 | 说明 |
|---|---|---|
| `dataset_root` | `datasets` | 原始数据集根目录，其下包含 split 子目录。 |
| `-o, --output-dir` | `QA` | QA 数据集输出根目录。 |
| `--splits` | `train val` | 需要构造的数据划分，可传一个或多个。 |
| `--seed` | `20260522` | 目标随机选择种子。 |
| `--selector` | `random` | 配置顶层 Key 选择策略。 |
| `--mask-strategy` | `remove_random_key` | 目标配置遮挡策略。 |
| `--progress-interval` | `100` | 每处理多少个源 JSON 打印一次进度；`0` 关闭周期输出。 |

## 输入与输出

**输入：** 原始图 JSON，主要使用 `nodes`、`deviceGroups`、`links` 及节点/设备组配置字段。

**输出：**

- `QA/<split>/node_config_qa/*.json`
- `QA/<split>/device_config_qa/*.json`
- `QA/build_summary.json`
- `QA/build_issues.jsonl`

[返回配置生成数据集构造脚本索引](README.md)
