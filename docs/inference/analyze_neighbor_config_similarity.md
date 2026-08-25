# analyze_neighbor_config_similarity.py

> 代码位置：[`inference/analyze_neighbor_config_similarity.py`](../../inference/analyze_neighbor_config_similarity.py)

## 功能与业务价值

**邻居同名配置距离实验。** 计算目标节点到最近同名顶层配置节点的真实最短路径距离，并关联生成指标。

**业务价值：** 验证模型答案是否受局部可参考配置影响，以及参考过远或全图缺失时性能如何变化。

## 核心逻辑

1. 从答案提取目标顶层 Key，从 metadata 获取目标节点。
2. 在 Input 拓扑上 BFS，查找拥有同名配置的节点。
3. 距离保留实际整数；目标节点自身已有同名配置记为 0，全图不存在记为 `inf`。
4. 按距离聚合可评估样本的核心指标。

## 参数

| 参数 | 说明 | 默认值或约束 |
|---|---|---|
| `--result-root` | 推理结果根目录，目录下按 split/task 保存逐样本 JSON。 | 默认：`DEFAULT_RESULT_ROOT` |
| `--qa-root` | QA 数据根目录，用于读取 prompt、input、output 或关联同名样本。 | 默认：`DEFAULT_QA_ROOT` |
| `--output-root` | 本脚本产物输出目录。 | 默认：`DEFAULT_OUTPUT_ROOT` |
| `--splits` | 逗号分隔的数据划分，例如 `train,val`。 | 默认：`DEFAULT_SPLITS` |
| `--tasks` | 逗号分隔的任务目录，例如 `node_config_qa,device_config_qa`。 | 默认：`DEFAULT_TASKS` |
| `--pred-keys` | 按优先级查找预测内容的字段名列表，兼容历史命名。 | 默认：`DEFAULT_PRED_KEYS` |
| `--gold-key` | 结果 JSON 中监督答案字段名。 | 默认：`DEFAULT_GOLD_KEY` |
| `--array-mode` | JSON 数组路径口径：`wildcard` 统一为 `[]`，`index` 保留下标。 | 默认：`'wildcard'`；可选：`['wildcard', 'index']` |
| `--progress-interval` | 每处理多少个文件打印一次进度；非正数通常表示关闭周期打印。 | 默认：`DEFAULT_PROGRESS_INTERVAL` |
| `--limit` | 最多处理的文件数；`0` 表示不限制。 | 默认：`0` |

路径参数相对于执行命令时的当前工作目录解析；运行 `--help` 可查看代码中的即时说明。

### 关键默认值

| 常量 | 当前代码表达式 |
|---|---|
| `DEFAULT_RESULT_ROOT` | `Path('inference-results')` |
| `DEFAULT_QA_ROOT` | `Path('520QA')` |
| `DEFAULT_OUTPUT_ROOT` | `Path('metric-results/neighbor-config-similarity')` |
| `DEFAULT_SPLITS` | `'val'` |
| `DEFAULT_TASKS` | `'node_config_qa'` |
| `DEFAULT_PRED_KEYS` | `'model-output,model_output,model-ouput'` |
| `DEFAULT_GOLD_KEY` | `'answer'` |
| `DEFAULT_PROGRESS_INTERVAL` | `500` |

## 运行方式

```bash
python inference/analyze_neighbor_config_similarity.py --help
```

建议先用 `--limit` 小规模验证路径、服务和输出格式，再运行完整 split。

## 输入与输出

**主要输出：**

- `per_file_neighbor_config_similarity.csv`
- `nearest_same_top_key_distance_metrics.csv`
- `summary.json`

**统计口径与异常：**

- 扫描文件数、模型错误数、解析/评估错误数和有效评估数应分开理解，指标分母以代码实际纳入的有效对象为准。
- 推理结果目录属于实验产物，不应覆盖 QA 数据源；改变预测字段名时需同步检查 `pred-keys`。

## 关键接口

| 接口 | 类型 | 职责 |
|---|---|---|
| `parse_csv_values` | function | 实现该脚本的核心处理步骤。 |
| `iter_result_files` | function | 实现该脚本的核心处理步骤。 |
| `qa_path_for_result` | function | 实现该脚本的核心处理步骤。 |
| `normalize_json_value` | function | 实现该脚本的核心处理步骤。 |
| `answer_value` | function | 实现该脚本的核心处理步骤。 |
| `output_top_level_keys` | function | 实现该脚本的核心处理步骤。 |
| `target_node_id` | function | 实现该脚本的核心处理步骤。 |
| `config_items` | function | 实现该脚本的核心处理步骤。 |
| `node_has_top_key` | function | 实现该脚本的核心处理步骤。 |
| `graph_parts` | function | 实现该脚本的核心处理步骤。 |
| `distances_from_target` | function | 实现该脚本的核心处理步骤。 |
| `nearest_same_top_key_stats` | function | 实现该脚本的核心处理步骤。 |
| `empty_metric_values` | function | 实现该脚本的核心处理步骤。 |
| `collect_rows` | function | 实现该脚本的核心处理步骤。 |
| `group_sort_key` | function | 实现该脚本的核心处理步骤。 |
| `group_rows` | function | 实现该脚本的核心处理步骤。 |
| `strip_internal_fields` | function | 实现该脚本的核心处理步骤。 |
| `write_csv` | function | 实现该脚本的核心处理步骤。 |
| `write_json` | function | 实现该脚本的核心处理步骤。 |
| `run` | function | 实现该脚本的核心处理步骤。 |
| `parse_args` | function | 实现该脚本的核心处理步骤。 |
| `main` | function | 实现该脚本的核心处理步骤。 |

## 相关文档

- [analyze_distance_by_root_key.py](analyze_distance_by_root_key.md)
- [analyze_topology_position.py](analyze_topology_position.md)

[返回 inference 脚本索引](README.md)
