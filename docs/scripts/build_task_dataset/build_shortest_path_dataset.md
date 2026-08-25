# build_shortest_path_dataset.py

> 代码位置：[`scripts/build_task_dataset/build_shortest_path_dataset.py`](../../../scripts/build_task_dataset/build_shortest_path_dataset.py)

## 功能与业务价值

构造两个节点之间最短链路任务数据集。

输入数据集目录结构默认是：

datasets/
  train/*.json
  val/*.json

一次运行会生成两套内容一一对应的数据集：

- with_answer: 保留 task_answer，供 Harness 评分使用
- without_answer: 删除 task_answer，供 Agent 执行任务使用

两套数据集都会保留 train/val 结构。每个输出 JSON 保留原始图结构，并在顶层新增：

- task_source_node_id: 源节点 ID
- task_target_node_id: 目标节点 ID
- task_question: 要求输出全部最短路径及对应设备名称、角色序列的问题
- task_answer: 最短路径长度、节点 ID 路径、角色序列和设备名称序列

如果一张图无法找到连通的源/目标节点对，则跳过该 JSON，并把原因写入
build_issues.jsonl。

**业务价值：** 打通 Agent Provider、图工具调用和自动评估的基础链路搜索流程。

## 核心逻辑

1. 把有效 links 视为无向边，过滤自环和无法解析的端点。
2. 使用固定随机种子选择可达节点对，并计算全部等长最短路径。
3. 同一次构建同时写出 with_answer 与 without_answer，保证上下文完全一致。

## 参数

| 参数 | 说明 |
|---|---|
| `-h, --help` | 显示当前脚本的完整命令帮助后退出。 |
| `--dataset-root DATASET_ROOT` | 原始数据集根目录，默认: datasets |
| `--output-root OUTPUT_ROOT` | 输出任务数据集根目录，默认: shortest_path_dataset |
| `--splits SPLITS [SPLITS ...]` | 需要处理的数据划分，默认: train val |
| `--seed SEED` | 随机种子，默认: 20260715 |
| `--max-attempts-per-graph MAX_ATTEMPTS_PER_GRAPH` | 每张图最多随机尝试多少组节点对，默认: 100 |
| `--progress-interval PROGRESS_INTERVAL` | 每处理多少个文件打印一次进度，默认: 100 |
| `--indent INDENT` | 输出 JSON 缩进，默认: 2 |

参数表以当前代码的 `--help` 为准。路径参数均相对于运行命令所在目录解析。

### 关键默认值

| 常量 | 当前值 |
|---|---|
| `DEFAULT_DATASET_ROOT` | `'datasets'` |
| `DEFAULT_OUTPUT_ROOT` | `'shortest_path_dataset'` |
| `DEFAULT_RANDOM_SEED` | `20260715` |
| `DEFAULT_SPLITS` | `('train', 'val')` |
| `DEFAULT_MAX_ATTEMPTS_PER_GRAPH` | `100` |
| `DEFAULT_PROGRESS_INTERVAL` | `100` |

## 运行方式

```bash
python scripts/build_task_dataset/build_shortest_path_dataset.py --help
```

确认数据路径和输出路径后，可去掉 `--help` 并传入上表参数执行。

## 关键接口

| 接口 | 职责 |
|---|---|
| `iter_json_files (function)` | 核心内部接口 |
| `load_json (function)` | 核心内部接口 |
| `get_device (function)` | 核心内部接口 |
| `get_node_role (function)` | 核心内部接口 |
| `get_node_information (function)` | 核心内部接口 |
| `build_adjacency (function)` | 根据 links 构造邻接表。 |
| `all_shortest_node_paths (function)` | 用 BFS 返回 source 到 target 的全部最短节点路径。 |
| `build_answer (function)` | 核心内部接口 |
| `choose_connected_node_pair (function)` | 核心内部接口 |
| `write_json (function)` | 核心内部接口 |
| `append_issue (function)` | 核心内部接口 |
| `process_file (function)` | 核心内部接口 |
| `write_stats_csv (function)` | 核心内部接口 |
| `build_dataset (function)` | 核心内部接口 |

## 输入、输出与口径

- 输入字段、候选筛选和异常状态以“核心逻辑”及源码校验条件为准。
- 构建结果通常同时包含 `with_answer` 与 `without_answer`，两者除答案字段外应保持一致。
- `build_summary.json` 和 issues/stats 文件用于解释跳过原因与最终样本数。
- 固定随机种子只有在输入文件集合与排序不变时才保证样本可复现。

[返回 任务数据集构建索引](README.md)
