# build_config_generation_dataset_pruned.py

> 代码位置：[`scripts/build_config_generation_dataset_pruned.py`](../../scripts/build_config_generation_dataset_pruned.py)

## 功能与业务价值

该脚本直接从原始拓扑构造配置生成 QA，但在抽取预测目标之前先控制图上下文长度。对于估算 Token 超过阈值的图，它保留一个随机中心节点，并持续删除距离中心最远的节点，直到满足阈值或已经没有可删除节点。

该版本用于降低超长拓扑对模型上下文窗口、显存和推理吞吐的压力，同时尽量保留中心节点附近的局部拓扑与配置参考。

## 核心逻辑

1. 读取一张原始图并估算紧凑 JSON 文本的 Token 数。
2. Token 超限时，从有效 node id 中随机选择一个裁剪中心。
3. 在当前无向拓扑上计算中心到所有节点的最短距离。
4. 优先删除不可达节点，其次逐个删除有限距离最远的节点，并同步删除关联链路。
5. 每删除一个节点重新估算 Token，直到低于阈值。
6. 在裁剪后的图上重新收集配置候选，并分别构造 node/deviceGroup QA。
7. 将裁剪前后规模和中心节点写入每个样本的 `metadata.context_pruning`。

## 代码实现说明

### Token 估算

- 图先使用无 ASCII 转义、无额外空白的紧凑 JSON 序列化，字段插入顺序保持不变。
- 粗略 BPE 规则将单个中文字符计为一个 Token；连续 ASCII 字母、数字及 `_-./` 按约四个字符一个 Token 估算；其他非空白字符按一个 Token 统计。
- 这是用于控制数量级的快速估算，不等同于 Qwen、Gemma 等具体 tokenizer 的精确长度。`max-input-tokens=0` 时完全关闭裁剪。

### 拓扑裁剪

- links 按无向边构造邻接表，只使用 source 和 target 都存在于 nodes 中的链路。BFS 计算从中心节点到其他节点的无权最短路径长度。
- 删除优先级由“是否不可达、距离、原 nodes 数组位置”组成：不可达节点视为距离无穷，最先删除；同距离时删除原列表中更靠后的节点，使结果稳定。
- 中心节点永远不删除。删除一个节点时同时删除 `nodes` 中对应对象及所有 source/target 指向它的 links，避免留下悬空边。
- 每次只删除一个节点并重新计算距离和 Token。虽然计算成本较高，但能严格遵守“逐步删除当前最远节点”的业务规则。

### 裁剪后构造目标

- 目标配置不是在裁剪前选择。脚本完成整图裁剪后，才从剩余节点配置和设备组配置中重新建立候选池并随机选取目标。
- 因此该脚本不使用 `build_config_generation_dataset.py` 已生成的 target，也不是在基础 QA 上继续处理；它是从原始数据开始的独立构造方案。
- 对 node 样本，随机裁剪中心不一定等于最终 target node。对 deviceGroup 样本，中心节点只用于保留局部上下文。
- `metadata.context_pruning` 保存中心节点、阈值、原始/最终 Token 估算、原始/最终节点数、删除节点数、是否执行裁剪以及最终是否仍超限。

### 异常与汇总

- 图没有有效 node id 时无法选择中心；如果本身超限，结果会标记无法正常完成裁剪。
- 只剩中心节点但 Token 仍超限时设置 `still_over_limit=true`，仍按代码中的候选情况决定是否能构造样本，并在问题文件中留下记录。
- `build_summary.json` 除基础样本计数外，还包含裁剪图数量、超限数量、删除节点总数以及裁剪前后 Token/节点平均值。

## 参数

| 参数 | 默认值 | 说明 |
|---|---|---|
| `dataset_root` | `datasets` | 原始数据集根目录。 |
| `-o, --output-dir` | `QA` | 裁剪后 QA 输出根目录。 |
| `--splits` | `train val` | 需要处理的数据划分。 |
| `--seed` | `20260522` | 随机中心和目标配置选择的固定种子。 |
| `--selector` | `random` | 裁剪完成后的目标 Key 选择策略。 |
| `--mask-strategy` | `remove_random_key` | 目标配置遮挡策略。 |
| `--progress-interval` | `100` | 进度打印间隔。 |
| `--max-input-tokens` | `100000` | 构造 QA 前允许的粗略图 Token 上限；`0` 禁用裁剪。 |

## 输入与输出

**输入：** `datasets/<split>/**/*.json` 原始图。

**输出：**

- `QA/<split>/node_config_qa/*.json`
- `QA/<split>/device_config_qa/*.json`
- 每个样本中的 `metadata.context_pruning`
- `QA/build_summary.json`
- `QA/build_issues.jsonl`

[返回配置生成数据集构造脚本索引](README.md)
