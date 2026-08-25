# analyze_node_name_uniqueness.py

> 代码位置：[`scripts/analyze_node_name_uniqueness.py`](../../scripts/analyze_node_name_uniqueness.py)

## 功能与业务价值

分析原始拓扑数据中 devices.NAME 能否唯一标识节点。

主要关注同一站点（单个 JSON）内部：同一个非空节点名称是否对应多个不同
node.id。跨站点重名也会统计，但由于站点名称可以提供作用域，因此不会直接判定
站点内节点标识失效。

**业务价值：** 验证设备名称能否作为任务答案中的唯一标识，推动任务统一使用 node.id。

## 核心逻辑

1. 按 split 递归读取 JSON，并将坏 JSON、缺失字段和类型异常分开计数。
2. 依据模块定义的统计口径提取字段或构造无向图，完成逐文件计算。
3. 聚合全局及分组结果，输出 CSV/JSON/SVG 等可复核产物并打印进度。

## 参数

| 参数 | 说明 |
|---|---|
| `dataset_root` | 数据集根目录，包含 train/ 和 val/。默认：datasets |
| `-h, --help` | 显示当前脚本的完整命令帮助后退出。 |
| `-o OUTPUT_DIR, --output-dir OUTPUT_DIR` | 统计结果目录。默认：/tmp/node_name_uniqueness_analysis |
| `--split {train,val,all}` | 分析 train、val 或全部数据。默认：all |
| `--progress-interval PROGRESS_INTERVAL` | 每处理 N 个文件打印一次进度，0 表示关闭。默认：50 |

参数表以当前代码的 `--help` 为准。路径参数均相对于运行命令所在目录解析。

### 关键默认值

| 常量 | 当前值 |
|---|---|
| `DEFAULT_DATASET_ROOT` | `'datasets'` |
| `DEFAULT_OUTPUT_DIR` | `'/tmp/node_name_uniqueness_analysis'` |
| `DEFAULT_PROGRESS_INTERVAL` | `50` |
| `STATISTICS_FILE` | `'node_name_uniqueness_statistics.json'` |
| `WITHIN_GRAPH_DUPLICATES_FILE` | `'within_graph_duplicate_node_names.csv'` |
| `CROSS_GRAPH_REUSE_FILE` | `'cross_graph_reused_node_names.csv'` |

## 运行方式

```bash
python scripts/analyze_node_name_uniqueness.py --help
```

确认数据路径和输出路径后，可去掉 `--help` 并传入上表参数执行。

## 关键接口

| 接口 | 职责 |
|---|---|
| `GraphNameResult (class)` | 核心内部接口 |
| `iter_json_files (function)` | 核心内部接口 |
| `get_device_name (function)` | 核心内部接口 |
| `analyze_graph (function)` | 核心内部接口 |
| `build_scope_summary (function)` | 核心内部接口 |
| `build_cross_graph_reuse (function)` | 核心内部接口 |
| `write_csv (function)` | 核心内部接口 |
| `print_summary (function)` | 核心内部接口 |
| `run_analysis (function)` | 核心内部接口 |

## 输入、输出与口径

- 输入字段、候选筛选和异常状态以“核心逻辑”及源码校验条件为准。
- 统计脚本需区分扫描文件数、有效文件数和参与数值计算的样本数，避免分母混淆。
- 输出目录不会自动上传，也不应覆盖原始数据集。

[返回 通用数据分析与配置生成索引](README.md)
