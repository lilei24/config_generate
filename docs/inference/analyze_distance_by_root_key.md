# analyze_distance_by_root_key.py

> 代码位置：[`inference/analyze_distance_by_root_key.py`](../../inference/analyze_distance_by_root_key.py)

## 功能与业务价值

**同名配置距离与顶层 Key 联合分析。** 在最近同名配置距离基础上进一步按答案 root key 细分生成指标。

**业务价值：** 区分“距离影响”与“配置类别本身难度”，避免由高频或简单 Key 主导总体趋势。

## 核心逻辑

1. 关联结果、QA、目标节点和答案 root key。
2. BFS 计算最近同名配置距离并保留 0、实际 hop 和 inf。
3. 按 `distance × root_key` 聚合字段路径、叶子三元组和值指标。

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
| `DEFAULT_OUTPUT_ROOT` | `Path('metric-results/distance-by-root-key')` |
| `DEFAULT_SPLITS` | `'val'` |
| `DEFAULT_TASKS` | `'node_config_qa'` |
| `DEFAULT_PRED_KEYS` | `'model-output,model_output,model-ouput'` |
| `DEFAULT_GOLD_KEY` | `'answer'` |
| `DEFAULT_PROGRESS_INTERVAL` | `500` |

## 运行方式

```bash
python inference/analyze_distance_by_root_key.py --help
```

建议先用 `--limit` 小规模验证路径、服务和输出格式，再运行完整 split。

## 输入与输出

**主要输出：**

- `per_file_distance_by_root_key.csv`
- `distance_by_root_key_metrics.csv`
- `summary.json`

**统计口径与异常：**

- 扫描文件数、模型错误数、解析/评估错误数和有效评估数应分开理解，指标分母以代码实际纳入的有效对象为准。
- 推理结果目录属于实验产物，不应覆盖 QA 数据源；改变预测字段名时需同步检查 `pred-keys`。

## 关键接口

| 接口 | 类型 | 职责 |
|---|---|---|
| `evaluate_json` | function | 实现该脚本的核心处理步骤。 |
| `empty_metric_accumulator` | function | 实现该脚本的核心处理步骤。 |
| `add_metric` | function | 实现该脚本的核心处理步骤。 |
| `finalize_accumulator` | function | 实现该脚本的核心处理步骤。 |
| `metric_row_values` | function | 实现该脚本的核心处理步骤。 |
| `evaluate_one_record` | function | 实现该脚本的核心处理步骤。 |
| `parse_csv_values` | function | 实现该脚本的核心处理步骤。 |
| `read_json` | function | 实现该脚本的核心处理步骤。 |
| `write_csv` | function | 实现该脚本的核心处理步骤。 |
| `write_json` | function | 实现该脚本的核心处理步骤。 |
| `iter_result_files` | function | 实现该脚本的核心处理步骤。 |
| `qa_path_for_result` | function | 实现该脚本的核心处理步骤。 |
| `graph_parts` | function | 实现该脚本的核心处理步骤。 |
| `distances_from_target` | function | 实现该脚本的核心处理步骤。 |
| `target_node_id` | function | 实现该脚本的核心处理步骤。 |
| `config_items` | function | 实现该脚本的核心处理步骤。 |
| `node_has_top_key` | function | 实现该脚本的核心处理步骤。 |
| `nearest_same_top_key_stats` | function | 实现该脚本的核心处理步骤。 |
| `answer_value` | function | 实现该脚本的核心处理步骤。 |
| `output_top_level_keys` | function | 实现该脚本的核心处理步骤。 |
| `empty_metric_values` | function | 实现该脚本的核心处理步骤。 |
| `collect_rows` | function | 实现该脚本的核心处理步骤。 |
| `group_rows_two_level` | function | Group by (split, task, nearest_same_top_key_group, target_top_level_key). |
| `strip_internal_fields` | function | 实现该脚本的核心处理步骤。 |
| `run` | function | 实现该脚本的核心处理步骤。 |
| `parse_args` | function | 实现该脚本的核心处理步骤。 |
| `main` | function | 实现该脚本的核心处理步骤。 |

## 相关文档

- [analyze_neighbor_config_similarity.py](analyze_neighbor_config_similarity.md)
- [plot_distance_rootkey.py](plot_distance_rootkey.md)

[返回 inference 脚本索引](README.md)
