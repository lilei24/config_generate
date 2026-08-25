# analyze_top_level_key_centrality.py

> 代码位置：[`scripts/analyze_top_level_key_centrality.py`](../../scripts/analyze_top_level_key_centrality.py)

## 功能与业务价值

Analyze top-level key distributions over node centrality.

For each graph JSON under the dataset root, the script:
- reads `nodes` and `links`
- treats links as an undirected graph
- computes degree centrality and betweenness centrality for every node
- maps each top-level key found in node `config`/`configs` to the nodes that expose it
- aggregates centrality statistics per top-level key

The script intentionally keeps its defaults local and uses only the standard library.

**业务价值：** 分析配置类型与节点拓扑位置的关系，判断配置生成是否依赖核心或边缘设备。

## 核心逻辑

1. 按 split 递归读取 JSON，并将坏 JSON、缺失字段和类型异常分开计数。
2. 依据模块定义的统计口径提取字段或构造无向图，完成逐文件计算。
3. 聚合全局及分组结果，输出 CSV/JSON/SVG 等可复核产物并打印进度。

## 参数

| 参数 | 说明 |
|---|---|
| `-h, --help` | 显示当前脚本的完整命令帮助后退出。 |
| `--dataset-root DATASET_ROOT` | Dataset root containing train/ and val/ directories. |
| `--output-dir OUTPUT_DIR` | Directory to write analysis outputs. |
| `--splits SPLITS` | Comma-separated split names, e.g. train,val. |
| `--tasks TASKS` | Comma-separated task dirs, e.g. node_config_qa,device_config_qa. |
| `--progress-interval PROGRESS_INTERVAL` | Print progress every N files. Use 0 to disable. |

参数表以当前代码的 `--help` 为准。路径参数均相对于运行命令所在目录解析。

### 关键默认值

| 常量 | 当前值 |
|---|---|
| `DEFAULT_DATASET_ROOT` | `'datasets'` |
| `DEFAULT_OUTPUT_DIR` | `'/tmp/top_level_key_centrality'` |
| `DEFAULT_SPLITS` | `'train,val'` |
| `DEFAULT_TASKS` | `'node_config_qa,device_config_qa'` |
| `DEFAULT_PROGRESS_INTERVAL` | `500` |

## 运行方式

```bash
python scripts/analyze_top_level_key_centrality.py --help
```

确认数据路径和输出路径后，可去掉 `--help` 并传入上表参数执行。

## 关键接口

| 接口 | 职责 |
|---|---|
| `KeyCentralityStats (class)` | 核心内部接口 |
| `KeyOwnerStats (class)` | 核心内部接口 |
| `parse_csv_values (function)` | 核心内部接口 |
| `iter_json_files (function)` | 核心内部接口 |
| `load_json (function)` | 核心内部接口 |
| `node_config_items (function)` | 核心内部接口 |
| `node_top_level_keys (function)` | 核心内部接口 |
| `device_group_config_items (function)` | 核心内部接口 |
| `device_group_top_level_keys (function)` | 核心内部接口 |
| `build_graph (function)` | 核心内部接口 |
| `degree_centrality (function)` | 核心内部接口 |
| `betweenness_centrality (function)` | Compute normalized betweenness centrality for an undirected graph. |
| `write_csv (function)` | 核心内部接口 |
| `write_json (function)` | 核心内部接口 |
| `collect_rows (function)` | 核心内部接口 |
| `summarize (function)` | 核心内部接口 |
| 其他内部接口 | 另有 3 个辅助接口，详见源码。 |

## 输入、输出与口径

- 输入字段、候选筛选和异常状态以“核心逻辑”及源码校验条件为准。
- 统计脚本需区分扫描文件数、有效文件数和参与数值计算的样本数，避免分母混淆。
- 输出目录不会自动上传，也不应覆盖原始数据集。

[返回 通用数据分析与配置生成索引](README.md)
