# inference_common.py

**源码：** [`inference_common.py`](../../infer_and_eval/inference_common.py)

[返回代码索引](README.md)

## 模块职责

该文件封装推理阶段与具体模型请求无关的公共能力：

- `with_answer` 和 `without_answer` 样本配对。
- Prompt 构造。
- 模型文本中的 JSON 提取。
- 不同答案类型的结构校验。
- 原子写入、断点成功判断、错误 CSV 和耗时格式化。

模型客户端和重试循环位于 `batch_infer_vllm.py`，避免公共模块与某一种服务调用方式强绑定。

## `SYSTEM_PROMPT`

系统提示统一限定模型角色和输出边界：

- 只能依据输入拓扑和 `task_question`。
- 不得猜测不存在的节点、链路或配置。
- 只输出 JSON。
- 不输出解释、Markdown、代码块或思考过程。

具体任务 Schema 和示例由数据集中的 `task_question` 提供，系统提示不重复维护七套任务格式。

## `SamplePaths`

```python
@dataclass(frozen=True)
class SamplePaths:
    split: str
    relative_path: Path
    hidden_path: Path
    answer_path: Path
    output_path: Path
```

它把同一个任务样本在三个位置的路径绑定起来：隐藏答案输入、有答案标准样本和推理输出。使用相同 `relative_path` 是保证答案配对正确的关键。

## JSON 文件处理

### `load_json_object()`

读取 UTF-8 JSON，并要求顶层必须是对象。数组、字符串或数字顶层会直接报错。

### `write_json_atomic()`

先写入同目录的 `.tmp` 文件，再通过替换操作生成最终文件。这样模型推理或进程中断时，不会留下看似存在但内容不完整的结果 JSON。

## 样本扫描与配对

### `collect_samples()`

处理 `train`、`val` 或 `all`：

1. 检查每个 split 的 hidden 和 answer 目录都存在。
2. 递归扫描 hidden 目录下的 JSON，并按路径排序。
3. 计算相对于 split 根目录的路径。
4. 使用相同相对路径定位 answer 文件和 output 文件。

该函数不提前读取全部 JSON，内容错误留给单样本处理阶段记录，避免一个坏文件中断整个扫描。

## Prompt 构造

### `build_prompt()`

要求样本包含非空字符串 `task_question`，然后生成：

```text
请完成以下任务：

<task_question>

【完整任务拓扑 JSON】
<without_answer 的紧凑 JSON>
```

完整样本本身也含有 `task_question`，前置展示是为了提高模型对任务要求的注意力；紧凑 JSON 用于减少非必要空白 token。

## 答案结构校验

### `_validate_path_list()`

只检查能够进入评估所需的结构：

- `paths` 是非空数组。
- 每条路径是非空数组。
- 每个节点 ID 是非空字符串。

它不检查路径是否真实存在，也不要求路径节点数等于 `path_length + 1`。这些属于答案正确性，应由评估指标处理。

### `validate_answer()`

根据 `TaskSpec.answer_kind` 分派：

#### `path`

- `path_length` 必须是非负整数，布尔值不算整数答案。
- `paths` 通过基础路径数组校验。

#### `extended_path`

除基础路径字段外：

- `path_role_sequences` 和 `path_device_names` 必须是数组。
- 两个数组的路径数量必须与 `paths` 一致。
- 每条角色、名称序列长度必须与对应节点路径一致。
- 序列元素必须是字符串。

这些约束用于保证后续能够按路径位置评价角色和设备名称。

#### `node_set`

- 从 `answer_field` 读取数组。
- 每个元素必须是非空节点 ID 字符串。
- 不允许重复节点 ID。

## 模型文本解析

### `strip_code_fence()`

若模型仍输出 Markdown 代码块，移除最外层围栏。该函数只是兼容模型偏差，不代表 Prompt 鼓励输出代码块。

### `parse_model_output()`

解析分两步：

1. 先尝试把完整清理后文本作为 JSON 解码。
2. 若失败，从文本中每个 `{` 位置尝试 `JSONDecoder.raw_decode()`，提取嵌入解释文本中的 JSON 对象。

所有候选对象依次经过 `validate_answer()`：

- 第一个结构合法的对象作为 `model-output`。
- 找到 JSON 但结构都不合法时，报告第一条结构错误。
- 完全找不到 JSON 对象时，报告“模型回答中没有可解析的 JSON 对象”。

这种设计区分了“服务没有返回”“返回内容不是 JSON”和“JSON 字段结构错误”三种情况。

## 断点判断

### `successful_result()`

只有输出文件同时满足以下条件才允许 `--resume` 跳过：

- 文件存在且 JSON 可读取。
- `inference_metadata` 是对象。
- `inference_metadata.success` 为 `true`。
- `model-output` 是对象。

失败和损坏结果会重新推理。

## 辅助输出

- `write_csv()`：固定写出批次错误字段，并使用 UTF-8 BOM 方便表格软件识别中文。
- `elapsed_text()`：把单调时钟耗时格式化为 `HH:MM:SS`，不受系统时间调整影响。

## 扩展注意事项

- 新答案类型应在 `validate_answer()` 中增加明确分支，不能让未知类型默认通过。
- 结构校验应保持最小化，避免把可评估的错误答案误标为推理失败。
- 若任务允许空路径或空节点集合，需要单独调整当前“非空路径”约束及对应指标定义。

