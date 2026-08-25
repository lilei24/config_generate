# analyze_lsw_gvlan_union.py

> 代码位置：[`scripts/vlan_analysis/analyze_lsw_gvlan_union.py`](../../../scripts/vlan_analysis/analyze_lsw_gvlan_union.py)

## 功能与业务价值

分析节点 lsw-gvlan-business 是否等于接口 VLAN 配置的并集。

**业务价值：** 围绕交换机接口、VLAN 集合关系和 VLAN 约束路径开展数据验证。

## 核心逻辑

1. 按 split 递归读取 JSON，并将坏 JSON、缺失字段和类型异常分开计数。
2. 依据模块定义的统计口径提取字段或构造无向图，完成逐文件计算。
3. 聚合全局及分组结果，输出 CSV/JSON/SVG 等可复核产物并打印进度。

## 参数

| 参数 | 说明 |
|---|---|
| `dataset_root` | 数据集根目录，目录下应包含 train/val，默认: datasets |
| `-h, --help` | 显示当前脚本的完整命令帮助后退出。 |
| `-o OUTPUT_DIR, --output-dir OUTPUT_DIR` | 结果输出目录，默认: /tmp/lsw_gvlan_union_analysis |
| `--split {train,val,all}` | 分析 train、val 或全部数据，默认: all |
| `--config-fields CONFIG_FIELDS [CONFIG_FIELDS ...]` | 需要扫描的节点配置字段，默认只扫描 configs |
| `--max-range-size MAX_RANGE_SIZE` | 单个 VLAN 连续范围允许展开的最大数量，默认: 4096 |
| `--progress-interval PROGRESS_INTERVAL` | 每处理 N 个文件打印一次进度，0 表示关闭，默认: 100 |

参数表以当前代码的 `--help` 为准。路径参数均相对于运行命令所在目录解析。

### 关键默认值

| 常量 | 当前值 |
|---|---|
| `DEFAULT_DATASET_ROOT` | `'datasets'` |
| `DEFAULT_OUTPUT_DIR` | `'/tmp/lsw_gvlan_union_analysis'` |
| `DEFAULT_SPLIT` | `'all'` |
| `DEFAULT_CONFIG_FIELDS` | `('configs',)` |
| `DEFAULT_PROGRESS_INTERVAL` | `100` |
| `DEFAULT_MAX_RANGE_SIZE` | `4096` |
| `DETAIL_FILE` | `'lsw_gvlan_union_details.csv'` |
| `SUMMARY_FILE` | `'lsw_gvlan_union_summary.json'` |
| `ERROR_FILE` | `'analysis_errors.csv'` |

## 运行方式

```bash
python scripts/vlan_analysis/analyze_lsw_gvlan_union.py --help
```

确认数据路径和输出路径后，可去掉 `--help` 并传入上表参数执行。

## 关键接口

| 接口 | 职责 |
|---|---|
| `iter_json_files (function)` | 核心内部接口 |
| `load_json_object (function)` | 核心内部接口 |
| `object_items (function)` | 核心内部接口 |
| `parse_vlan_token (function)` | 核心内部接口 |
| `parse_vlan_value (function)` | 核心内部接口 |
| `collect_named_values (function)` | 递归收集对象中名称完全匹配的字段值。 |
| `parse_named_values (function)` | 核心内部接口 |
| `sorted_vlan_text (function)` | 核心内部接口 |
| `raw_json (function)` | 核心内部接口 |
| `contains_all_vlan (function)` | 判断 VLAN 表达式中是否包含独立的 all 通配值。 |
| `analyze_node (function)` | 核心内部接口 |
| `analyze_graph (function)` | 核心内部接口 |
| `write_csv (function)` | 核心内部接口 |
| `split_summary (function)` | 核心内部接口 |
| `run (function)` | 核心内部接口 |

## 输入、输出与口径

- 输入字段、候选筛选和异常状态以“核心逻辑”及源码校验条件为准。
- VLAN 表达式可能包含整数、逗号列表、连续范围和 `all`，解析失败应单独统计。
- 物理图按无向关系计算，但 `LEFTPORT` 始终属于 source，`RIGHTPORT` 始终属于 target。
- 空集合、缺失字段、接口未匹配和确实不允许 VLAN 是不同业务状态。

[返回 VLAN 专项分析索引](README.md)
