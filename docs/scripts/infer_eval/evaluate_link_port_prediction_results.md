# evaluate_link_port_prediction_results.py

> 代码位置：[`scripts/infer_eval/evaluate_link_port_prediction_results.py`](../../../scripts/infer_eval/evaluate_link_port_prediction_results.py)

## 功能与业务价值

评估链路 LEFTPORT、RIGHTPORT 预测结果。

**业务价值：** 统一执行 vLLM/OpenCode 推理、错误记录、指标计算和 SwanLab 观测。

## 核心逻辑

1. 读取同一结果 JSON 中的 task_answer 与 model-output，错误样本单独识别。
2. 按任务语义规范化路径或集合，计算每样本指标和截至当前样本的平均指标。
3. 输出逐文件指标、汇总结果，并可将曲线与样本表记录到 SwanLab。

## 指标口径

| 指标 | 含义 |
|---|---|
| `leftport_accuracy` | 预测 LEFTPORT 与标准答案完全一致的样本准确率。 |
| `rightport_accuracy` | 预测 RIGHTPORT 与标准答案完全一致的样本准确率。 |
| `port_pair_exact_match` | 按任务标准答案与模型输出逐样本计算。 |

脚本先计算单样本指标，再对参与评估的样本做算术平均；模型运行错误或输出结构错误的处理以代码中的有效样本判定为准。

## 参数

| 参数 | 说明 |
|---|---|
| `result_path` | 单个同时包含 task_answer 和 model-output 的结果 JSON，或包含 train/val 的结果目录，默认: vllm-results/link_port_prediction |
| `-h, --help` | 显示当前脚本的完整命令帮助后退出。 |
| `--output-dir OUTPUT_DIR` | 本地评估输出目录，默认: vllm-results/link_port_prediction-evaluation |
| `--split {train,val,all}` | 评估的数据划分，默认: val |
| `--progress-interval PROGRESS_INTERVAL` | 每处理 N 个文件打印进度，0 表示关闭，默认: 100 |
| `--swanlab-project SWANLAB_PROJECT` | SwanLab 项目名称，默认: topology-link-port-prediction |
| `--swanlab-experiment SWANLAB_EXPERIMENT` | SwanLab 实验名称，默认: link-port-prediction-evaluation |
| `--swanlab-mode SWANLAB_MODE` | SwanLab 运行模式，默认: cloud |
| `--swanlab-color-seed SWANLAB_COLOR_SEED` | 根据实验名生成确定性颜色的固定随机种子，默认: 20260727 |
| `--swanlab-color-key SWANLAB_COLOR_KEY` | 实验颜色区分键；默认使用 result_path，不同模型可显式传入不同键 |
| `--disable-swanlab` | 只生成本地评估文件，不初始化 SwanLab |

参数表以当前代码的 `--help` 为准。路径参数均相对于运行命令所在目录解析。

### 关键默认值

| 常量 | 当前值 |
|---|---|
| `DEFAULT_RESULT_PATH` | `'vllm-results/link_port_prediction'` |
| `DEFAULT_OUTPUT_DIR` | `'vllm-results/link_port_prediction-evaluation'` |
| `METRIC_NAMES` | `('leftport_accuracy', 'rightport_accuracy', 'port_pair_exact_match')` |
| `DETAIL_NAMES` | `('leftport_correct', 'rightport_correct', 'port_pair_correct')` |

## 运行方式

```bash
python scripts/infer_eval/evaluate_link_port_prediction_results.py --help
```

确认数据路径和输出路径后，可去掉 `--help` 并传入上表参数执行。

## 关键接口

| 接口 | 职责 |
|---|---|
| `valid_port (function)` | 核心内部接口 |
| `evaluate_document (function)` | 核心内部接口 |

## 输入、输出与口径

- 输入字段、候选筛选和异常状态以“核心逻辑”及源码校验条件为准。
- 推理结果以原答案文档为基础增加 `model-output` 和运行状态，错误原因不得静默丢弃。
- 评估时必须区分扫描样本、模型成功样本、结构可解析样本和实际参与指标平均的样本。
- SwanLab 是观测渠道，本地 CSV/JSON 才是可重复复核的指标结果。

[返回 批量推理与评估索引](README.md)
