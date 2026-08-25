# batch_evaluate_qa_swanlab.py

> 代码位置：[`inference/batch_evaluate_qa_swanlab.py`](../../inference/batch_evaluate_qa_swanlab.py)

## 功能与业务价值

**离线评估结果上传 SwanLab。** 先执行本地批量评估，再将 summary 中的聚合指标上传 SwanLab；支持恢复已有 run。

**业务价值：** 适合在推理完成后补充 eval 汇总，而不重新产生模型回答。

## 核心逻辑

1. 调用 `batch_evaluate_qa.run` 生成或刷新本地评估产物。
2. 读取 summary 的 overall 与 split/task 聚合指标。
3. 支持 `run_id + resume` 恢复实验，并通过日志前缀隔离 eval 指标。
4. `swanlab-log-step` 控制汇总点在横轴上的 step。

## 参数

| 参数 | 说明 | 默认值或约束 |
|---|---|---|
| `--result-root` | 推理结果根目录，目录下按 split/task 保存逐样本 JSON。 | 默认：`DEFAULT_RESULT_ROOT` |
| `--output-root` | 本脚本产物输出目录。 | 默认：`DEFAULT_OUTPUT_ROOT` |
| `--splits` | 逗号分隔的数据划分，例如 `train,val`。 | 默认：`DEFAULT_SPLITS` |
| `--tasks` | 逗号分隔的任务目录，例如 `node_config_qa,device_config_qa`。 | 默认：`DEFAULT_TASKS` |
| `--pred-keys` | 按优先级查找预测内容的字段名列表，兼容历史命名。 | 默认：`','.join(DEFAULT_PRED_KEYS)` |
| `--gold-key` | 结果 JSON 中监督答案字段名。 | 默认：`DEFAULT_GOLD_KEY` |
| `--array-mode` | JSON 数组路径口径：`wildcard` 统一为 `[]`，`index` 保留下标。 | 默认：`'wildcard'`；可选：`['wildcard', 'index']` |
| `--progress-interval` | 每处理多少个文件打印一次进度；非正数通常表示关闭周期打印。 | 默认：`DEFAULT_PROGRESS_INTERVAL` |
| `--limit` | 最多处理的文件数；`0` 表示不限制。 | 默认：`0` |
| `--swanlab-project` | SwanLab 项目名。 | 默认：`DEFAULT_SWANLAB_PROJECT` |
| `--swanlab-experiment` | SwanLab 实验名。 | 默认：`DEFAULT_SWANLAB_EXPERIMENT` |
| `--swanlab-mode` | SwanLab 运行模式，例如 `cloud` 或本地模式。 | 默认：`DEFAULT_SWANLAB_MODE` |
| `--swanlab-run-id` | Existing SwanLab experiment ID to resume. | 默认：`''` |
| `--swanlab-resume` | SwanLab resume mode. If --swanlab-run-id is set, default is must. | 默认：`''`；可选：`['', 'must', 'allow', 'never', 'true', 'false']` |
| `--swanlab-log-step` | Step used when logging aggregate evaluation metrics. | 默认：`DEFAULT_SWANLAB_LOG_STEP` |
| `--swanlab-log-prefix` | Metric namespace prefix for evaluation logs. Default: eval. | 默认：`DEFAULT_SWANLAB_LOG_PREFIX` |

路径参数相对于执行命令时的当前工作目录解析；运行 `--help` 可查看代码中的即时说明。

### 关键默认值

| 常量 | 当前代码表达式 |
|---|---|
| `DEFAULT_SWANLAB_PROJECT` | `'config-generation'` |
| `DEFAULT_SWANLAB_EXPERIMENT` | `'qwen3-8b-evaluation'` |
| `DEFAULT_SWANLAB_MODE` | `'cloud'` |
| `DEFAULT_SWANLAB_LOG_STEP` | `0` |
| `DEFAULT_SWANLAB_LOG_PREFIX` | `'eval'` |

## 运行方式

```bash
python inference/batch_evaluate_qa_swanlab.py --help
```

建议先用 `--limit` 小规模验证路径、服务和输出格式，再运行完整 split。

## 输入与输出

**主要输出：**

- 保留全部本地评估文件，并向 SwanLab 上传聚合指标。

**统计口径与异常：**

- 扫描文件数、模型错误数、解析/评估错误数和有效评估数应分开理解，指标分母以代码实际纳入的有效对象为准。
- 推理结果目录属于实验产物，不应覆盖 QA 数据源；改变预测字段名时需同步检查 `pred-keys`。

## 关键接口

| 接口 | 类型 | 职责 |
|---|---|---|
| `read_summary` | function | 实现该脚本的核心处理步骤。 |
| `normalize_resume` | function | 实现该脚本的核心处理步骤。 |
| `join_metric_name` | function | 实现该脚本的核心处理步骤。 |
| `log_summary` | function | 实现该脚本的核心处理步骤。 |
| `run` | function | 实现该脚本的核心处理步骤。 |
| `parse_args` | function | 实现该脚本的核心处理步骤。 |
| `main` | function | 实现该脚本的核心处理步骤。 |

## 相关文档

- [batch_evaluate_qa.py](batch_evaluate_qa.md)
- [swanlab_utils.py](swanlab_utils.md)

[返回 inference 脚本索引](README.md)
