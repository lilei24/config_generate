# build_config_generation_dataset.py

> 代码位置：[`scripts/build_config_generation_dataset.py`](../../scripts/build_config_generation_dataset.py)

## 功能与业务价值

从图 JSON 数据集构造配置生成任务的 QA 样本。

当前任务粒度是预测一个 config 对象里的一个顶层 key：

- node 配置来自 ``nodes[].configs[]``，同时兼容历史样例里的 ``nodes[].config[]``。
- deviceGroup 配置来自 ``deviceGroups[].configs[]``。
- 一个训练样本只遮挡一个顶层 key，目标输出也只包含该 key 对应的配置对象。

脚本把“选择哪个 key”与“怎样遮挡 key”拆成独立策略，后续可以在不改主流程
的前提下新增前部 key、后部 key 选择策略，或者新增占位符类遮挡策略。

**业务价值：** 把不规则拓扑配置转为配置补全 QA，使模型能够基于其余拓扑上下文预测被隐藏配置。

## 核心逻辑

1. 分别收集 node configs/config 与 deviceGroups configs 中的顶层配置对象。
2. 通过可替换的 TargetSelector 随机选择目标配置对象，仅隐藏该对象。
3. 保留整张图和其余配置，输出 prompt、input、output 与 metadata。

## 参数

| 参数 | 说明 |
|---|---|
| `dataset_root` | Dataset root containing train/ and val/ directories. Default: datasets |
| `-h, --help` | 显示当前脚本的完整命令帮助后退出。 |
| `-o OUTPUT_DIR, --output-dir OUTPUT_DIR` | Directory for generated QA data. Default: QA |
| `--splits SPLITS [SPLITS ...]` | Split directory names to build. |
| `--seed SEED` | Seed for deterministic target selection. |
| `--selector {random}` | Target key selector. New selection policies can be registered in TARGET_SELECTORS. |
| `--mask-strategy {remove_random_key}` | How the selected config key is hidden from input. |
| `--progress-interval PROGRESS_INTERVAL` | Print progress every N source JSON files. Use 0 to disable. Default: 100 |

参数表以当前代码的 `--help` 为准。路径参数均相对于运行命令所在目录解析。

### 关键默认值

| 常量 | 当前值 |
|---|---|
| `DEFAULT_DATASET_ROOT` | `'datasets'` |
| `DEFAULT_OUTPUT_DIR` | `'QA'` |
| `DEFAULT_RANDOM_SEED` | `20260522` |
| `DEFAULT_PROGRESS_INTERVAL` | `100` |

## 运行方式

```bash
python scripts/build_config_generation_dataset.py --help
```

确认数据路径和输出路径后，可去掉 `--help` 并传入上表参数执行。

## 关键接口

| 接口 | 职责 |
|---|---|
| `ConfigTarget (class)` | 一个可被预测的配置顶层 key 的定位信息。 |
| `BuildIssue (class)` | 构造数据集时需要落盘记录的源文件问题。 |
| `iter_json_files (function)` | 按 split 递归枚举 JSON 文件。 |
| `list_split_json_files (function)` | 列出单个 split 下的 JSON 文件，便于提前知道进度总数。 |
| `load_graph (function)` | 读取一张图。 |
| `top_level_config_keys (function)` | 枚举 config/configs 列表内所有可预测顶层 key。 |
| `node_config_items (function)` | 读取 node 配置列表字段。 |
| `collect_node_targets (function)` | 收集整张图中所有 node config 候选目标。 |
| `collect_device_group_targets (function)` | 收集整张图中所有 deviceGroup configs 候选目标。 |
| `select_random_target (function)` | 从候选池里随机选择一个目标。 |
| `get_target_object (function)` | 根据 ConfigTarget 找到包含目标 key 的 config 对象。 |
| `get_target_config_list (function)` | 根据 ConfigTarget 找到目标所属的 config/configs 列表。 |
| `remove_random_key (function)` | 复制原图，并从 input 中删除被选中的顶层配置 key。 |
| `target_output (function)` | 从未遮挡的原图中提取监督目标。 |
| `prompt_for_target (function)` | 根据目标来源生成对应任务提示词。 |
| `target_metadata (function)` | 把目标定位信息写入样本，便于回溯原始 JSON。 |
| 其他内部接口 | 另有 7 个辅助接口，详见源码。 |

## 输入、输出与口径

- 输入字段、候选筛选和异常状态以“核心逻辑”及源码校验条件为准。
- 统计脚本需区分扫描文件数、有效文件数和参与数值计算的样本数，避免分母混淆。
- 输出目录不会自动上传，也不应覆盖原始数据集。

[返回 通用数据分析与配置生成索引](README.md)
