# build_device_type_statistics_dataset.py

> 代码位置：[`scripts/build_task_dataset/build_device_type_statistics_dataset.py`](../../../scripts/build_task_dataset/build_device_type_statistics_dataset.py)

## 功能与业务价值

构造按物理设备类型统计设备名称的任务数据集。

每张原始拓扑生成一个样本。标准答案使用 nodes[].devices.TYPE（兼容历史字段
nodes[].device.TYPE）动态分组，并收集对应的 NAME；逻辑角色不参与统计。
一次运行同步生成 with_answer 和 without_answer 两套数据集。

**业务价值：** 评估 Agent 从拓扑上下文按物理类型汇总设备的结构化信息抽取能力。

## 核心逻辑

1. 递归扫描指定 train/val，并校验单图 JSON 的 nodes、links 与任务所需业务字段。
2. 从满足约束的候选中按固定种子或确定性顺序选择任务对象，计算可自动验证的标准答案。
3. 保持原始拓扑上下文，写出任务字段；需要盲测时同步生成隐藏 task_answer 的版本。

## 参数

| 参数 | 说明 |
|---|---|
| `-h, --help` | 显示当前脚本的完整命令帮助后退出。 |
| `--dataset-root DATASET_ROOT` | 原始数据集根目录，默认: datasets |
| `--output-root OUTPUT_ROOT` | 任务数据集输出根目录，默认: device_type_statistics_dataset |
| `--splits SPLITS [SPLITS ...]` | 处理的数据划分，默认: train val |
| `--progress-interval PROGRESS_INTERVAL` | 每处理 N 个文件打印进度，0 表示关闭，默认: 100 |
| `--indent INDENT` | 输出 JSON 的缩进空格数。 |

参数表以当前代码的 `--help` 为准。路径参数均相对于运行命令所在目录解析。

### 关键默认值

| 常量 | 当前值 |
|---|---|
| `DEFAULT_DATASET_ROOT` | `'datasets'` |
| `DEFAULT_OUTPUT_ROOT` | `'device_type_statistics_dataset'` |
| `DEFAULT_SPLITS` | `('train', 'val')` |
| `DEFAULT_PROGRESS_INTERVAL` | `100` |
| `WITH_ANSWER_DIR` | `'with_answer'` |
| `WITHOUT_ANSWER_DIR` | `'without_answer'` |
| `STATS_FILE` | `'device_type_statistics.csv'` |
| `SUMMARY_FILE` | `'build_summary.json'` |
| `ISSUES_FILE` | `'build_issues.jsonl'` |

## 运行方式

```bash
python scripts/build_task_dataset/build_device_type_statistics_dataset.py --help
```

确认数据路径和输出路径后，可去掉 `--help` 并传入上表参数执行。

## 关键接口

| 接口 | 职责 |
|---|---|
| `iter_json_files (function)` | 核心内部接口 |
| `load_graph (function)` | 核心内部接口 |
| `nonempty_string (function)` | 核心内部接口 |
| `get_complete_device (function)` | 读取完整设备信息，优先使用原始数据常见的 devices 字段。 |
| `collect_device_statistics (function)` | 严格收集所有节点的物理类型和名称，避免生成不完整标准答案。 |
| `build_task_graph (function)` | 核心内部接口 |
| `write_json (function)` | 核心内部接口 |
| `append_issue (function)` | 核心内部接口 |
| `remove_stale_outputs (function)` | 核心内部接口 |
| `write_stats (function)` | 核心内部接口 |
| `build_dataset (function)` | 核心内部接口 |

## 输入、输出与口径

- 输入字段、候选筛选和异常状态以“核心逻辑”及源码校验条件为准。
- 构建结果通常同时包含 `with_answer` 与 `without_answer`，两者除答案字段外应保持一致。
- `build_summary.json` 和 issues/stats 文件用于解释跳过原因与最终样本数。
- 固定随机种子只有在输入文件集合与排序不变时才保证样本可复现。

[返回 任务数据集构建索引](README.md)
