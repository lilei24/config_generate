# analyze_graph_max_finite_shortest_path.py

> 代码位置：[`scripts/analyze_graph_max_finite_shortest_path.py`](../../scripts/analyze_graph_max_finite_shortest_path.py)

## 功能与业务价值

统计原始数据集中每张图的最大有限最短路长度。

“最大有限最短路长度”定义为：一张图中所有可达节点对的最短路径长度的最大值。
路径长度按链路跳数计算。对于不连通图，只比较可达节点对；存在有效节点但没有
任何有效链路时，结果记为 0。

输出格式参考 link_field_stats.py：只生成一个格式化 JSON 文件，顶层包含全局
汇总 summary 和逐图结果 per_file，并在终端打印进度、耗时、ETA 和长度分布。

**业务价值：** 衡量站点拓扑直径和最坏搜索深度，为路径任务难度分层提供依据。

## 核心逻辑

1. 按 split 递归读取 JSON，并将坏 JSON、缺失字段和类型异常分开计数。
2. 依据模块定义的统计口径提取字段或构造无向图，完成逐文件计算。
3. 聚合全局及分组结果，输出 CSV/JSON/SVG 等可复核产物并打印进度。

## 参数

| 参数 | 说明 |
|---|---|
| `dataset_root` | 数据集根目录，内含 train/ 和 val/。默认：datasets |
| `-h, --help` | 显示当前脚本的完整命令帮助后退出。 |
| `-o OUTPUT_DIR, --output-dir OUTPUT_DIR` | 统计结果输出目录。默认：/tmp/max_finite_shortest_path_analysis |
| `--split {train,val,all}` | 统计范围：train、val 或 all。默认：all |
| `--progress-interval PROGRESS_INTERVAL` | 每 N 张图打印一次进度。0 表示不打印。默认：50 |

参数表以当前代码的 `--help` 为准。路径参数均相对于运行命令所在目录解析。

### 关键默认值

| 常量 | 当前值 |
|---|---|
| `DEFAULT_DATASET_ROOT` | `'datasets'` |
| `DEFAULT_OUTPUT_DIR` | `'/tmp/max_finite_shortest_path_analysis'` |
| `DEFAULT_PROGRESS_INTERVAL` | `50` |

## 运行方式

```bash
python scripts/analyze_graph_max_finite_shortest_path.py --help
```

确认数据路径和输出路径后，可去掉 `--help` 并传入上表参数执行。

## 关键接口

| 接口 | 职责 |
|---|---|
| `GraphPathLengthResult (class)` | 核心内部接口 |
| `iter_json_files (function)` | 按 split 递归枚举 JSON 文件。 |
| `list_split_json_files (function)` | 核心内部接口 |
| `load_graph (function)` | 核心内部接口 |
| `build_adjacency (function)` | 根据 nodes 和 links 构造邻接表，并返回数据质量状态。 |
| `maximum_finite_shortest_path_length (function)` | 对每个源节点执行 BFS，返回所有有限最短距离中的最大值。 |
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
