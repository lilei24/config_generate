# analyze_dataset.py

> 代码位置：[`scripts/analyze_dataset.py`](../../scripts/analyze_dataset.py)

## 功能与业务价值

Analyze graph JSON datasets for node config generation.

The script expects a dataset root containing train/ and val/ folders. Each JSON
file should describe one graph with nodes and links. It intentionally uses only
the Python standard library so it can run on the data host without extra setup.

**业务价值：** 建立数据质量基线，识别字段缺失、结构漂移和配置稀疏性，为后续样本构造提供可信输入。

## 核心逻辑

1. 按 split 递归读取 JSON，并将坏 JSON、缺失字段和类型异常分开计数。
2. 依据模块定义的统计口径提取字段或构造无向图，完成逐文件计算。
3. 聚合全局及分组结果，输出 CSV/JSON/SVG 等可复核产物并打印进度。

## 参数

| 参数 | 说明 |
|---|---|
| `dataset_root` | Dataset root containing train/ and val/ directories. Default: /data/my_dataset |
| `-h, --help` | 显示当前脚本的完整命令帮助后退出。 |
| `-o OUTPUT_DIR, --output-dir OUTPUT_DIR` | Directory for generated reports. Default: /tmp/config_analysis |
| `--splits SPLITS [SPLITS ...]` | Split directory names to analyze. |

参数表以当前代码的 `--help` 为准。路径参数均相对于运行命令所在目录解析。

### 关键默认值

| 常量 | 当前值 |
|---|---|
| `DEFAULT_DATASET_ROOT` | `'/data/my_dataset'` |
| `DEFAULT_OUTPUT_DIR` | `'/tmp/config_analysis'` |

## 运行方式

```bash
python scripts/analyze_dataset.py --help
```

确认数据路径和输出路径后，可去掉 `--help` 并传入上表参数执行。

## 关键接口

| 接口 | 职责 |
|---|---|
| `PathStat (class)` | 核心内部接口 |
| `GroupStat (class)` | 核心内部接口 |
| `type_name (function)` | 核心内部接口 |
| `stable_value (function)` | 核心内部接口 |
| `iter_json_files (function)` | 核心内部接口 |
| `flatten_leaf_paths (function)` | Return leaf paths with [] used as a wildcard for list elements. |
| `flatten_config_leaf_paths (function)` | Flatten config while treating the root config list as a container. |
| `update_path_stats (function)` | 核心内部接口 |
| `nested_get (function)` | 核心内部接口 |
| `config_top_keys (function)` | 核心内部接口 |
| `graph_degrees (function)` | 核心内部接口 |
| `connected_components (function)` | 核心内部接口 |
| `write_json (function)` | 核心内部接口 |
| `write_jsonl (function)` | 核心内部接口 |
| `write_csv (function)` | 核心内部接口 |
| `counter_json (function)` | 核心内部接口 |
| 其他内部接口 | 另有 2 个辅助接口，详见源码。 |

## 输入、输出与口径

- 输入字段、候选筛选和异常状态以“核心逻辑”及源码校验条件为准。
- 统计脚本需区分扫描文件数、有效文件数和参与数值计算的样本数，避免分母混淆。
- 输出目录不会自动上传，也不应覆盖原始数据集。

[返回 通用数据分析与配置生成索引](README.md)
