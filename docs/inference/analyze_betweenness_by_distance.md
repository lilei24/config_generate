# analyze_betweenness_by_distance.py

> 代码位置：[`inference/analyze_betweenness_by_distance.py`](../../inference/analyze_betweenness_by_distance.py)

## 功能与业务价值

**中介中心性与同名配置距离分析。** 联合分析目标节点中介中心性分组、最近同名配置距离和生成指标。

**业务价值：** 用于验证拓扑位置与可参考配置距离之间是否存在交互效应。

## 核心逻辑

1. 构造目标节点所在无向图并计算归一化中介中心性。
2. 计算最近同名顶层 Key 节点的实际最短距离。
3. 按 `betweenness group × distance` 聚合，root key 仅作为逐文件解释字段。

## 代码实现说明

- 对每个 QA Input 构造无向简单图，先定位目标节点所在连通分量，再使用 Brandes 类最短路径累计过程计算目标节点归一化中介中心性。
- 最近同名配置距离使用目标节点 BFS 和节点配置顶层 Key 匹配计算，保留 0、所有实际有限 hop 与 `inf`。
- 中介中心性按 0.1 区间离散化，然后以 `split + task + betweenness_group + distance` 聚合；root key、中心性原值和距离原值仍保留在逐文件表中用于排查。
- 组指标由正确数、预测总数和答案总数累计后计算，属于 micro 口径。联合格样本很少时应结合 `evaluated_files` 解读。

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
| `DEFAULT_OUTPUT_ROOT` | `Path('metric-results/betweenness-by-distance')` |
| `DEFAULT_SPLITS` | `'val'` |
| `DEFAULT_TASKS` | `'node_config_qa'` |
| `DEFAULT_PRED_KEYS` | `'model-output,model_output,model-ouput'` |
| `DEFAULT_GOLD_KEY` | `'answer'` |
| `DEFAULT_PROGRESS_INTERVAL` | `500` |

## 运行方式

```bash
python inference/analyze_betweenness_by_distance.py --help
```

建议先用 `--limit` 小规模验证路径、服务和输出格式，再运行完整 split。

## 输入与输出

**主要输出：**

- `per_file_betweenness_by_distance.csv`
- `betweenness_by_distance_metrics.csv`
- `summary.json`

**统计口径与异常：**

- 扫描文件数、模型错误数、解析/评估错误数和有效评估数应分开理解，指标分母以代码实际纳入的有效对象为准。
- 推理结果目录属于实验产物，不应覆盖 QA 数据源；改变预测字段名时需同步检查 `pred-keys`。


## 相关文档

- [analyze_betweenness_distance_rootkey.py](analyze_betweenness_distance_rootkey.md)
- [plot_betweenness_distance.py](plot_betweenness_distance.md)

[返回 inference 脚本索引](README.md)
