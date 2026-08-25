# visualize_vlan_inference_results.py

> 代码位置：[`scripts/vlan_analysis/visualize_vlan_inference_results.py`](../../../scripts/vlan_analysis/visualize_vlan_inference_results.py)

## 功能与业务价值

将 VLAN 约束路径推理结果生成为可交互的静态 HTML。

**业务价值：** 将模型答案、标准路径、端口配置和 VLAN 通行状态统一呈现，支持人工误差分析。

## 核心逻辑

1. 批量读取同时含 task_answer 和 model-output 的结果 JSON。
2. 匹配链路端口和接口配置，解析目标 VLAN 在每条链路上的通行状态。
3. 生成索引和独立 HTML，交互对比答案路径、预测路径、节点接口与异常链路。

## 参数

| 参数 | 说明 |
|---|---|
| `result_path` | 单个推理结果 JSON 或结果根目录，默认: vllm-results/vlan_constrained_shortest_path |
| `-h, --help` | 显示当前脚本的完整命令帮助后退出。 |
| `-o OUTPUT_ROOT, --output-root OUTPUT_ROOT` | HTML 输出目录，默认: vlan-inference-visualizations |
| `--split {train,val,all}` | 目录输入时处理的数据划分，默认: all |
| `--max-range-size MAX_RANGE_SIZE` | VLAN 连续范围允许展开的最大数量，默认: 4096 |
| `--progress-interval PROGRESS_INTERVAL` | 每处理 N 个文件打印进度，0 表示关闭，默认: 50 |

参数表以当前代码的 `--help` 为准。路径参数均相对于运行命令所在目录解析。

### 关键默认值

| 常量 | 当前值 |
|---|---|
| `DEFAULT_RESULT_PATH` | `'vllm-results/vlan_constrained_shortest_path'` |
| `DEFAULT_OUTPUT_ROOT` | `'vlan-inference-visualizations'` |
| `DEFAULT_SPLIT` | `'all'` |
| `DEFAULT_MAX_RANGE_SIZE` | `4096` |
| `DEFAULT_PROGRESS_INTERVAL` | `50` |

## 运行方式

```bash
python scripts/vlan_analysis/visualize_vlan_inference_results.py --help
```

确认数据路径和输出路径后，可去掉 `--help` 并传入上表参数执行。

## 关键接口

| 接口 | 职责 |
|---|---|
| `PageRecord (class)` | 核心内部接口 |
| `scalar_text (function)` | 核心内部接口 |
| `object_items (function)` | 核心内部接口 |
| `node_device (function)` | 核心内部接口 |
| `collect_interfaces (function)` | 保留接口原始配置及其所在位置，便于页面定位配置来源。 |
| `parse_vlan_value (function)` | 核心内部接口 |
| `support_text (function)` | 核心内部接口 |
| `normalize_paths (function)` | 核心内部接口 |
| `path_edges (function)` | 核心内部接口 |
| `result_exact_match (function)` | 核心内部接口 |
| `initial_positions (function)` | 以任务源节点为起点分层，无法到达的分量依次放在右侧。 |
| `json_for_script (function)` | 核心内部接口 |
| `parse_result (function)` | 核心内部接口 |
| `page_html (function)` | 核心内部接口 |
| `index_html (function)` | 核心内部接口 |
| `collect_files (function)` | 核心内部接口 |

## 输入、输出与口径

- 输入字段、候选筛选和异常状态以“核心逻辑”及源码校验条件为准。
- VLAN 表达式可能包含整数、逗号列表、连续范围和 `all`，解析失败应单独统计。
- 物理图按无向关系计算，但 `LEFTPORT` 始终属于 source，`RIGHTPORT` 始终属于 target。
- 空集合、缺失字段、接口未匹配和确实不允许 VLAN 是不同业务状态。

[返回 VLAN 专项分析索引](README.md)
