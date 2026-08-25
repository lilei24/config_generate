# validate_vlan_task_unconstrained_paths.py

> 代码位置：[`scripts/vlan_analysis/validate_vlan_task_unconstrained_paths.py`](../../../scripts/vlan_analysis/validate_vlan_task_unconstrained_paths.py)

## 功能与业务价值

验证 VLAN 约束路径任务在忽略 VLAN 时的 LSW 最短路径。

**业务价值：** 用无约束基线验证 VLAN 任务确实体现约束带来的路径变化。

## 核心逻辑

1. 按 split 递归读取 JSON，并将坏 JSON、缺失字段和类型异常分开计数。
2. 依据模块定义的统计口径提取字段或构造无向图，完成逐文件计算。
3. 聚合全局及分组结果，输出 CSV/JSON/SVG 等可复核产物并打印进度。

## 参数

| 参数 | 说明 |
|---|---|
| `dataset_root` | with_answer 数据集根目录，目录下包含 train/val，默认: vlan_constrained_shortest_path_dataset/with_answer |
| `-h, --help` | 显示当前脚本的完整命令帮助后退出。 |
| `-o OUTPUT_FILE, --output-file OUTPUT_FILE` | 验证结果 JSON 文件，默认: /tmp/vlan_task_unconstrained_path_validation.json |
| `--split {train,val,all}` | 验证 train、val 或全部数据，默认: all |
| `--max-output-paths MAX_OUTPUT_PATHS` | 每个任务最多写入的无约束路径数，默认: 1000 |
| `--progress-interval PROGRESS_INTERVAL` | 每处理 N 个文件打印一次进度，0 表示关闭，默认: 100 |

参数表以当前代码的 `--help` 为准。路径参数均相对于运行命令所在目录解析。

### 关键默认值

| 常量 | 当前值 |
|---|---|
| `DEFAULT_DATASET_ROOT` | `'vlan_constrained_shortest_path_dataset/with_answer'` |
| `DEFAULT_OUTPUT_FILE` | `'/tmp/vlan_task_unconstrained_path_validation.json'` |
| `DEFAULT_SPLIT` | `'all'` |
| `DEFAULT_MAX_OUTPUT_PATHS` | `1000` |
| `DEFAULT_PROGRESS_INTERVAL` | `100` |

## 运行方式

```bash
python scripts/vlan_analysis/validate_vlan_task_unconstrained_paths.py --help
```

确认数据路径和输出路径后，可去掉 `--help` 并传入上表参数执行。

## 关键接口

| 接口 | 职责 |
|---|---|
| `iter_json_files (function)` | 核心内部接口 |
| `load_json_object (function)` | 核心内部接口 |
| `scalar_text (function)` | 核心内部接口 |
| `node_device (function)` | 核心内部接口 |
| `is_lsw_node (function)` | 核心内部接口 |
| `build_unconstrained_lsw_graph (function)` | 仅按物理连接构建 LSW 无向图，不检查端口和 VLAN 配置。 |
| `shortest_path_tree (function)` | 核心内部接口 |
| `restore_paths (function)` | 核心内部接口 |
| `constrained_answer_length (function)` | 核心内部接口 |
| `validate_task (function)` | 核心内部接口 |
| `counter_summary (function)` | 核心内部接口 |
| `run (function)` | 核心内部接口 |

## 输入、输出与口径

- 输入字段、候选筛选和异常状态以“核心逻辑”及源码校验条件为准。
- VLAN 表达式可能包含整数、逗号列表、连续范围和 `all`，解析失败应单独统计。
- 物理图按无向关系计算，但 `LEFTPORT` 始终属于 source，`RIGHTPORT` 始终属于 target。
- 空集合、缺失字段、接口未匹配和确实不允许 VLAN 是不同业务状态。

[返回 VLAN 专项分析索引](README.md)
