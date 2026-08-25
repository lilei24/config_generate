# analyze_vlan_schema.py

> 代码位置：[`scripts/analyze_vlan_schema.py`](../../scripts/analyze_vlan_schema.py)

## 功能与业务价值

发现原始拓扑数据中所有 key 名包含 vlan 的 JSON Schema 路径。

**业务价值：** 建立 VLAN 相关 Key 的结构目录，辅助配置语义分析和任务设计。

## 核心逻辑

1. 按 split 递归读取 JSON，并将坏 JSON、缺失字段和类型异常分开计数。
2. 依据模块定义的统计口径提取字段或构造无向图，完成逐文件计算。
3. 聚合全局及分组结果，输出 CSV/JSON/SVG 等可复核产物并打印进度。

## 参数

| 参数 | 说明 |
|---|---|
| `dataset_root` | 原始数据集根目录，默认: datasets |
| `-h, --help` | 显示当前脚本的完整命令帮助后退出。 |
| `-o OUTPUT_DIR, --output-dir OUTPUT_DIR` | 统计结果目录，默认: /tmp/vlan_schema_analysis |
| `--split {train,val,all}` | 扫描 train、val 或全部数据，默认: all |
| `--progress-interval PROGRESS_INTERVAL` | 每处理 N 个文件打印一次进度，0 表示关闭，默认: 50 |
| `--max-examples MAX_EXAMPLES` | 每条路径最多保留的不同示例值数量，默认: 5 |
| `--max-example-length MAX_EXAMPLE_LENGTH` | 单个示例值的最大字符数，默认: 300 |

参数表以当前代码的 `--help` 为准。路径参数均相对于运行命令所在目录解析。

### 关键默认值

| 常量 | 当前值 |
|---|---|
| `DEFAULT_DATASET_ROOT` | `'datasets'` |
| `DEFAULT_OUTPUT_DIR` | `'/tmp/vlan_schema_analysis'` |
| `DEFAULT_PROGRESS_INTERVAL` | `50` |
| `DEFAULT_MAX_EXAMPLES` | `5` |
| `DEFAULT_MAX_EXAMPLE_LENGTH` | `300` |
| `FIELD_PATH_FILE` | `'vlan_field_path_summary.csv'` |
| `VALUE_TYPE_FILE` | `'vlan_value_type_summary.csv'` |
| `TOP_LEVEL_KEY_FILE` | `'vlan_top_level_key_summary.csv'` |
| `SUMMARY_FILE` | `'vlan_analysis_summary.json'` |

## 运行方式

```bash
python scripts/analyze_vlan_schema.py --help
```

确认数据路径和输出路径后，可去掉 `--help` 并传入上表参数执行。

## 关键接口

| 接口 | 职责 |
|---|---|
| `ScanContext (class)` | 核心内部接口 |
| `PathStatistics (class)` | 核心内部接口 |
| `TopLevelKeyStatistics (class)` | 核心内部接口 |
| `VlanSchemaAnalyzer (class)` | 核心内部接口 |
| `json_value_type (function)` | 核心内部接口 |
| `compact_example (function)` | 核心内部接口 |
| `scalar_text (function)` | 核心内部接口 |
| `get_device (function)` | 核心内部接口 |
| `get_device_type (function)` | 核心内部接口 |
| `get_device_role (function)` | 核心内部接口 |
| `child_path (function)` | 核心内部接口 |
| `walk_value (function)` | 核心内部接口 |
| `walk_mapping (function)` | 核心内部接口 |
| `scan_config_item (function)` | 核心内部接口 |
| `scan_config_container (function)` | 核心内部接口 |
| `scan_node (function)` | 核心内部接口 |
| 其他内部接口 | 另有 8 个辅助接口，详见源码。 |

## 输入、输出与口径

- 输入字段、候选筛选和异常状态以“核心逻辑”及源码校验条件为准。
- 统计脚本需区分扫描文件数、有效文件数和参与数值计算的样本数，避免分母混淆。
- 输出目录不会自动上传，也不应覆盖原始数据集。

[返回 通用数据分析与配置生成索引](README.md)
