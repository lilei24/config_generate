# analyze_nearest_core_path_length.py

> 代码位置：[`scripts/analyze_nearest_core_path_length.py`](../../scripts/analyze_nearest_core_path_length.py)

## 功能与业务价值

统计“上行节点路径查询”任务数据集中的最短路径长度。

默认读取 ``uplink_node_path_dataset/with_answer/{train,val}``，直接使用已经构造好的
``task_answer.path_length``，避免重新随机选择 AP 后与实际任务样本不一致。

输出格式与 analyze_graph_max_finite_shortest_path.py 一致：只生成一个格式化 JSON，
顶层包含全局汇总 summary 和逐文件结果 per_file；终端打印进度、速度、ETA、
长度汇总与长度分布。

**业务价值：** 验证 AP 到上游目标任务的跳数难度分布，支撑任务采样和指标分层。

## 核心逻辑

1. 按 split 递归读取 JSON，并将坏 JSON、缺失字段和类型异常分开计数。
2. 依据模块定义的统计口径提取字段或构造无向图，完成逐文件计算。
3. 聚合全局及分组结果，输出 CSV/JSON/SVG 等可复核产物并打印进度。

## 参数

| 参数 | 说明 |
|---|---|
| `input_root` | 上行节点路径查询有答案数据集根目录，内含 train/ 和 val/。默认：uplink_node_path_dataset/with_answer |
| `-h, --help` | 显示当前脚本的完整命令帮助后退出。 |
| `-o OUTPUT_DIR, --output-dir OUTPUT_DIR` | 统计结果输出目录。默认：/tmp/uplink_node_path_length_analysis |
| `--split {train,val,all}` | 统计范围：train、val 或 all。默认：all |
| `--progress-interval PROGRESS_INTERVAL` | 每 N 个样本打印一次进度。0 表示不打印。默认：50 |

参数表以当前代码的 `--help` 为准。路径参数均相对于运行命令所在目录解析。

### 关键默认值

| 常量 | 当前值 |
|---|---|
| `DEFAULT_INPUT_ROOT` | `'uplink_node_path_dataset/with_answer'` |
| `DEFAULT_OUTPUT_DIR` | `'/tmp/uplink_node_path_length_analysis'` |
| `DEFAULT_PROGRESS_INTERVAL` | `50` |

## 运行方式

```bash
python scripts/analyze_nearest_core_path_length.py --help
```

确认数据路径和输出路径后，可去掉 `--help` 并传入上表参数执行。

## 关键接口

| 接口 | 职责 |
|---|---|
| `NearestCorePathLengthResult (class)` | 核心内部接口 |
| `iter_json_files (function)` | 核心内部接口 |
| `list_split_json_files (function)` | 核心内部接口 |
| `load_json (function)` | 核心内部接口 |
| `analyze_file (function)` | 核心内部接口 |
| `number_summary (function)` | 核心内部接口 |
| `value_distribution (function)` | 核心内部接口 |
| `build_scope_statistics (function)` | 核心内部接口 |
| `write_json (function)` | 核心内部接口 |
| `terminal_bar (function)` | 核心内部接口 |
| `print_terminal_summary (function)` | 核心内部接口 |
| `build_statistics (function)` | 核心内部接口 |

## 输入、输出与口径

- 输入字段、候选筛选和异常状态以“核心逻辑”及源码校验条件为准。
- 统计脚本需区分扫描文件数、有效文件数和参与数值计算的样本数，避免分母混淆。
- 输出目录不会自动上传，也不应覆盖原始数据集。

[返回 通用数据分析与配置生成索引](README.md)
