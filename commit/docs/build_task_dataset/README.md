# 任务数据集构造

七个构造脚本相互独立，均从原始 `train/val` 拓扑选择满足业务约束的任务对象，自动计算标准答案，并生成有答案和隐藏答案两套数据。

[返回文档总览](../README.md)

## 任务与脚本映射

| 中文任务名称 | 构造脚本 | 独立文档 |
|---|---|---|
| 节点最短路径查询 | `build_shortest_path_dataset.py` | [查看](node_shortest_path_query.md) |
| 上行节点路径查询 | `build_uplink_node_path_dataset.py` | [查看](uplink_node_path_query.md) |
| 可达下游终端节点 | `build_downstream_reachable_terminal_dataset.py` | [查看](downstream_reachable_terminal.md) |
| 节点故障约束路径查询 | `build_node_failure_reroute_dataset.py` | [查看](node_failure_constrained_path_query.md) |
| 指定CORE约束的AP间最短路径查询 | `build_ap_pair_via_core_path_dataset.py` | [查看](ap_path_via_required_core.md) |
| vlan约束的交换机路径查询 | `build_vlan_constrained_shortest_path_dataset.py` | [查看](vlan_constrained_lsw_path_query.md) |
| 故障影响AP节点 | `build_node_failure_ap_impact_dataset.py` | [查看](node_failure_impacted_ap.md) |

## 公共输入结构

```text
datasets/
├── train/**/*.json
└── val/**/*.json
```

每个 JSON 表示一张拓扑图。构造脚本递归扫描选定 split，并按文件路径字典序处理。

## 公共输出结构

```text
<task_dataset>/
├── with_answer/
│   ├── train/**/*.json
│   └── val/**/*.json
├── without_answer/
│   ├── train/**/*.json
│   └── val/**/*.json
├── build_summary.json
├── *_stats.csv
└── build_issues.jsonl
```

- `with_answer`：保留 `task_answer`，用于自动评估和可视化。
- `without_answer`：删除 `task_answer`，用于模型或 Agent 推理。
- `build_summary.json`：扫描数量、生成数量和跳过原因汇总。
- `*_stats.csv`：逐任务或逐图的构造统计。
- `build_issues.jsonl`：JSON 读取失败、候选不足、答案规模超限等逐文件问题。

## 公共任务字段

- `task_question`：自然语言任务、JSON Schema 和输出示例。
- `task_answer`：由图算法计算的标准答案。
- `task_metadata`：任务名称、来源文件、构造策略和业务口径。
- 其他 `task_*` 字段：当前任务指定的源、目标、故障节点、CORE 或 VLAN。

各任务的候选限制和答案字段以对应独立文档为准。
