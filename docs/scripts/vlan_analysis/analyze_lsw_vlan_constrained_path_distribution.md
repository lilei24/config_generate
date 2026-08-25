# analyze_lsw_vlan_constrained_path_distribution.py

> 代码位置：[`scripts/vlan_analysis/analyze_lsw_vlan_constrained_path_distribution.py`](../../../scripts/vlan_analysis/analyze_lsw_vlan_constrained_path_distribution.py)

## 功能与业务价值

统计至少有一个 VLAN 可端到端通过的 LSW 最短路径分布。

**业务价值：** 识别普通最短路不可用但存在 VLAN 约束绕行的高价值样本。

## 核心逻辑

1. 构造接口唯一匹配且双端 allow-through-vlan 可解析的 LSW 基础图。
2. 对每个 VLAN 构造仅含双端允许链路的约束子图。
3. 比较无约束与 VLAN 约束最短距离，统计端到端可达和约束绕行节点对。

## 参数

| 参数 | 说明 |
|---|---|
| `dataset_root` | 数据集根目录，目录下应包含 train/val，默认: datasets |
| `-h, --help` | 显示当前脚本的完整命令帮助后退出。 |
| `-o OUTPUT_FILE, --output-file OUTPUT_FILE` | 分析结果 JSON 文件，默认: /tmp/lsw_vlan_constrained_path_distribution.json |
| `--split {train,val,all}` | 分析 train、val 或全部数据，默认: all |
| `--config-fields CONFIG_FIELDS [CONFIG_FIELDS ...]` | 需要扫描的节点配置字段，默认只扫描 configs |
| `--max-range-size MAX_RANGE_SIZE` | 单个 VLAN 范围允许展开的最大数量，默认: 4096 |
| `--progress-interval PROGRESS_INTERVAL` | 每处理 N 个文件打印一次进度，0 表示关闭，默认: 100 |

参数表以当前代码的 `--help` 为准。路径参数均相对于运行命令所在目录解析。

### 关键默认值

| 常量 | 当前值 |
|---|---|
| `DEFAULT_DATASET_ROOT` | `'datasets'` |
| `DEFAULT_OUTPUT_FILE` | `'/tmp/lsw_vlan_constrained_path_distribution.json'` |
| `DEFAULT_SPLIT` | `'all'` |
| `DEFAULT_CONFIG_FIELDS` | `('configs',)` |
| `DEFAULT_PROGRESS_INTERVAL` | `100` |
| `DEFAULT_MAX_RANGE_SIZE` | `4096` |

## 运行方式

```bash
python scripts/vlan_analysis/analyze_lsw_vlan_constrained_path_distribution.py --help
```

确认数据路径和输出路径后，可去掉 `--help` 并传入上表参数执行。

## 关键接口

| 接口 | 职责 |
|---|---|
| `parse_vlan_value (function)` | 核心内部接口 |
| `intersect_support (function)` | 核心内部接口 |
| `union_support (function)` | 核心内部接口 |
| `support_is_empty (function)` | 核心内部接口 |
| `add_base_edge (function)` | 核心内部接口 |
| `add_vlan_edge (function)` | 核心内部接口 |
| `build_graphs (function)` | 构建普通候选图和边携带共同 VLAN 集合的约束图。 |
| `ordinary_distances (function)` | 核心内部接口 |
| `constrained_paths_from_source (function)` | 按节点和沿途 VLAN 交集状态执行分层 BFS。 |
| `analyze_paths (function)` | 核心内部接口 |
| `merge_distribution (function)` | 核心内部接口 |
| `sorted_numeric_distribution (function)` | 核心内部接口 |
| `sorted_vlan_count_distribution (function)` | 核心内部接口 |
| `counter_values (function)` | 核心内部接口 |
| `run (function)` | 核心内部接口 |

## 输入、输出与口径

- 输入字段、候选筛选和异常状态以“核心逻辑”及源码校验条件为准。
- VLAN 表达式可能包含整数、逗号列表、连续范围和 `all`，解析失败应单独统计。
- 物理图按无向关系计算，但 `LEFTPORT` 始终属于 source，`RIGHTPORT` 始终属于 target。
- 空集合、缺失字段、接口未匹配和确实不允许 VLAN 是不同业务状态。

[返回 VLAN 专项分析索引](README.md)
