# analyze_topology_position.py

> 代码位置：[`inference/analyze_topology_position.py`](../../inference/analyze_topology_position.py)

## 功能与业务价值

**目标节点拓扑位置实验。** 统计目标节点累计 1/2/3-hop 邻居数、连通分量大小、是否孤立和归一化中介中心性，并关联生成指标。

**业务价值：** 用于判断局部密度、连通规模和网络枢纽位置是否增加配置生成难度。

## 核心逻辑

1. 将 nodes/links 构造成无向简单图并定位目标节点。
2. 2-hop 包含 1-hop，3-hop 包含 1-hop 和 2-hop。
3. 计算目标所在连通分量和归一化 betweenness centrality。
4. 整数因素按实际值逐项统计；中介中心性按 0.1 区间分组。

## 代码实现说明

- nodes 的 `id` 作为图节点，links 的 source/target 作为无向边；缺失端点和不在节点集合中的边不会参与目标节点图计算。
- 从目标节点 BFS 得到 hop 距离。累计 2-hop 和 3-hop 数量包含所有更近节点，不是仅统计恰好距离等于 2 或 3 的节点。
- connected component size 是目标节点所在连通分量节点数；目标节点度数为 0 时 `is_isolated=true`。无法定位目标节点的样本进入异常状态。
- 中介中心性按无向、无权图最短路径计算并归一化到 0-1，再按 `[0.0,0.1)` 等 0.1 区间分组，最高值进入 `0.9-1.0`。
- 邻居数、分量大小和孤立状态按实际整数/布尔值逐组统计，不合并成 0-5 等粗范围。

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
| `DEFAULT_OUTPUT_ROOT` | `Path('metric-results/topology-position')` |
| `DEFAULT_SPLITS` | `'val'` |
| `DEFAULT_TASKS` | `'node_config_qa'` |
| `DEFAULT_PRED_KEYS` | `'model-output,model_output,model-ouput'` |
| `DEFAULT_GOLD_KEY` | `'answer'` |
| `DEFAULT_PROGRESS_INTERVAL` | `500` |

## 运行方式

```bash
python inference/analyze_topology_position.py --help
```

建议先用 `--limit` 小规模验证路径、服务和输出格式，再运行完整 split。

## 输入与输出

**主要输出：**

- `per_file_topology_position.csv`
- 每个拓扑因素对应的 `*_metrics.csv`
- `summary.json`

**统计口径与异常：**

- 扫描文件数、模型错误数、解析/评估错误数和有效评估数应分开理解，指标分母以代码实际纳入的有效对象为准。
- 推理结果目录属于实验产物，不应覆盖 QA 数据源；改变预测字段名时需同步检查 `pred-keys`。


[返回 inference 脚本索引](README.md)
