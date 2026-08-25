# analyze_lsw_link_interfaces.py

> 代码位置：[`scripts/vlan_analysis/analyze_lsw_link_interfaces.py`](../../../scripts/vlan_analysis/analyze_lsw_link_interfaces.py)

## 功能与业务价值

匹配直连交换机链路两端的 LSW 接口配置。

**业务价值：** 将物理链路端口与交换机接口配置对齐，是 VLAN 链路与路径分析的基础。

## 核心逻辑

1. 仅保留非自环的 LSW-LSW 直连链路。
2. 按 link.source/LEFTPORT 和 link.target/RIGHTPORT 匹配 interface-name。
3. 只输出双端唯一匹配详情，其余情况按原因计数。

## 参数

| 参数 | 说明 |
|---|---|
| `dataset_root` | 数据集根目录，目录下应包含 train/val，默认: datasets |
| `-h, --help` | 显示当前脚本的完整命令帮助后退出。 |
| `-o OUTPUT_FILE, --output-file OUTPUT_FILE` | 单个分析结果 JSON 文件，默认: /tmp/lsw_link_interface_analysis.json |
| `--split {train,val,all}` | 分析 train、val 或全部数据，默认: all |
| `--config-fields CONFIG_FIELDS [CONFIG_FIELDS ...]` | 需要扫描的节点配置字段，默认只扫描 configs |
| `--progress-interval PROGRESS_INTERVAL` | 每处理 N 个文件打印一次进度，0 表示关闭，默认: 100 |

参数表以当前代码的 `--help` 为准。路径参数均相对于运行命令所在目录解析。

### 关键默认值

| 常量 | 当前值 |
|---|---|
| `DEFAULT_DATASET_ROOT` | `'datasets'` |
| `DEFAULT_OUTPUT_FILE` | `'/tmp/lsw_link_interface_analysis.json'` |
| `DEFAULT_SPLIT` | `'all'` |
| `DEFAULT_CONFIG_FIELDS` | `('configs',)` |
| `DEFAULT_PROGRESS_INTERVAL` | `100` |

## 运行方式

```bash
python scripts/vlan_analysis/analyze_lsw_link_interfaces.py --help
```

确认数据路径和输出路径后，可去掉 `--help` 并传入上表参数执行。

## 关键接口

| 接口 | 职责 |
|---|---|
| `iter_json_files (function)` | 核心内部接口 |
| `load_json_object (function)` | 核心内部接口 |
| `object_items (function)` | 核心内部接口 |
| `scalar_text (function)` | 核心内部接口 |
| `node_device (function)` | 核心内部接口 |
| `is_lsw_node (function)` | 核心内部接口 |
| `collect_interface_configs (function)` | 返回端口匹配状态、全部匹配结果及扫描到的接口对象数。 |
| `endpoint_result (function)` | 核心内部接口 |
| `analyze_graph (function)` | 核心内部接口 |
| `rejected_link_categories (function)` | 核心内部接口 |
| `counter_summary (function)` | 核心内部接口 |
| `run (function)` | 核心内部接口 |

## 输入、输出与口径

- 输入字段、候选筛选和异常状态以“核心逻辑”及源码校验条件为准。
- VLAN 表达式可能包含整数、逗号列表、连续范围和 `all`，解析失败应单独统计。
- 物理图按无向关系计算，但 `LEFTPORT` 始终属于 source，`RIGHTPORT` 始终属于 target。
- 空集合、缺失字段、接口未匹配和确实不允许 VLAN 是不同业务状态。

[返回 VLAN 专项分析索引](README.md)
