# analyze_vlan_config_locations.py

> 代码位置：[`scripts/analyze_vlan_config_locations.py`](../../scripts/analyze_vlan_config_locations.py)

## 功能与业务价值

按正则查找 node/deviceGroup 配置中的 VLAN Key，并输出源码行号和配置层级。

**业务价值：** 发现 VLAN 配置在不规则 JSON 中的具体位置和层级，为业务字段梳理提供证据。

## 核心逻辑

1. 按 split 递归读取 JSON，并将坏 JSON、缺失字段和类型异常分开计数。
2. 依据模块定义的统计口径提取字段或构造无向图，完成逐文件计算。
3. 聚合全局及分组结果，输出 CSV/JSON/SVG 等可复核产物并打印进度。

## 参数

| 参数 | 说明 |
|---|---|
| `dataset_root` | 原始数据集根目录，目录下应包含 train/val |
| `-h, --help` | 显示当前脚本的完整命令帮助后退出。 |
| `-o OUTPUT_ROOT, --output-root OUTPUT_ROOT` | 逐文件 TXT 和汇总输出目录，默认: vlan-config-analysis |
| `--splits SPLITS [SPLITS ...]` | 处理的数据划分，默认: train val |
| `--vlan-pattern VLAN_PATTERN` | 匹配配置 Key 的正则表达式，默认: (?i)vlan |
| `--progress-interval PROGRESS_INTERVAL` | 每处理 N 个文件打印进度，0 表示关闭 |
| `--max-value-length MAX_VALUE_LENGTH` | TXT 中匹配值的最大字符数，0 表示不限制 |
| `--max-source-line-length MAX_SOURCE_LINE_LENGTH` | TXT 中原始源码行的最大字符数，0 表示不限制 |

参数表以当前代码的 `--help` 为准。路径参数均相对于运行命令所在目录解析。

### 关键默认值

| 常量 | 当前值 |
|---|---|
| `DEFAULT_DATASET_ROOT` | `'datasets'` |
| `DEFAULT_OUTPUT_ROOT` | `'vlan-config-analysis'` |
| `DEFAULT_SPLITS` | `('train', 'val')` |
| `DEFAULT_VLAN_PATTERN` | `'(?i)vlan'` |
| `DEFAULT_PROGRESS_INTERVAL` | `100` |
| `DEFAULT_MAX_VALUE_LENGTH` | `1000` |
| `DEFAULT_MAX_SOURCE_LINE_LENGTH` | `1000` |
| `SUMMARY_FILE` | `'vlan_analysis_summary.csv'` |
| `KEY_SUMMARY_FILE` | `'vlan_key_summary.csv'` |
| `ERROR_FILE` | `'analysis_errors.jsonl'` |

## 运行方式

```bash
python scripts/analyze_vlan_config_locations.py --help
```

确认数据路径和输出路径后，可去掉 `--help` 并传入上表参数执行。

## 关键接口

| 接口 | 职责 |
|---|---|
| `KeyLocation (class)` | 核心内部接口 |
| `ConfigRoot (class)` | 核心内部接口 |
| `VlanMatch (class)` | 核心内部接口 |
| `iter_json_files (function)` | 核心内部接口 |
| `truncate (function)` | 核心内部接口 |
| `decode_key_token (function)` | 核心内部接口 |
| `scan_key_locations (function)` | 核心内部接口 |
| `walk_object_keys (function)` | 核心内部接口 |
| `build_location_map (function)` | 核心内部接口 |
| `config_container_items (function)` | 核心内部接口 |
| `node_owner (function)` | 核心内部接口 |
| `group_owner (function)` | 核心内部接口 |
| `iter_config_roots (function)` | 核心内部接口 |
| `format_json_path (function)` | 核心内部接口 |
| `hierarchy_text (function)` | 核心内部接口 |
| `list_hierarchy (function)` | 核心内部接口 |
| 其他内部接口 | 另有 7 个辅助接口，详见源码。 |

## 输入、输出与口径

- 输入字段、候选筛选和异常状态以“核心逻辑”及源码校验条件为准。
- 统计脚本需区分扫描文件数、有效文件数和参与数值计算的样本数，避免分母混淆。
- 输出目录不会自动上传，也不应覆盖原始数据集。

[返回 通用数据分析与配置生成索引](README.md)
