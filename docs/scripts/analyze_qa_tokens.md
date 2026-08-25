# analyze_qa_tokens.py

> 代码位置：[`scripts/analyze_qa_tokens.py`](../../scripts/analyze_qa_tokens.py)

## 功能与业务价值

统计 QA 样本 input 的 token 分布，并生成柱状图。

默认读取 build_config_generation_dataset.py 生成的 QA 目录：

QA/
  train/
    node_config_qa/*.json
    device_config_qa/*.json
  val/
    node_config_qa/*.json
    device_config_qa/*.json

注意：不同大模型 tokenizer 不完全一致。这个脚本默认使用 rough_bpe 近似估算，
用于快速判断上下文长度量级；如果后续确定具体模型，可以在这里新增对应 tokenizer。

**业务价值：** 量化配置生成上下文长度，辅助选择模型上下文窗口和裁剪策略。

## 核心逻辑

1. 按 split 和任务目录递归读取 QA JSON。
2. 对指定 input/prompt/output 字段序列化后采用 rough_bpe 或 simple_unit 估算。
3. 输出分布、CDF、上下文阈值覆盖率、分位数、节点数及任务级汇总。

## 参数

| 参数 | 说明 |
|---|---|
| `qa_root` | QA root directory. Default: QA |
| `-h, --help` | 显示当前脚本的完整命令帮助后退出。 |
| `-o OUTPUT_DIR, --output-dir OUTPUT_DIR` | Output directory. Default: QA_token_analysis |
| `--splits SPLITS [SPLITS ...]` | Split names to scan. |
| `--field {input,prompt,output}` | Sample field to tokenize. Default: input |
| `--tokenizer {rough_bpe,simple_unit}` | Tokenizer estimate method. |
| `--bins BINS` | Approximate histogram bin count when token count is above 100. |
| `--progress-interval PROGRESS_INTERVAL` | Print progress every N QA files. Use 0 to disable. Default: 500 |

参数表以当前代码的 `--help` 为准。路径参数均相对于运行命令所在目录解析。

### 关键默认值

| 常量 | 当前值 |
|---|---|
| `DEFAULT_QA_ROOT` | `'QA'` |
| `DEFAULT_OUTPUT_DIR` | `'QA_token_analysis'` |
| `DEFAULT_FIELD` | `'input'` |
| `DEFAULT_PROGRESS_INTERVAL` | `500` |

## 运行方式

```bash
python scripts/analyze_qa_tokens.py --help
```

确认数据路径和输出路径后，可去掉 `--help` 并传入上表参数执行。

## 关键接口

| 接口 | 职责 |
|---|---|
| `TokenRow (class)` | 核心内部接口 |
| `iter_qa_files (function)` | 枚举 QA/<split>/<task_dir>/*.json 文件。 |
| `list_qa_files (function)` | 预先列出 QA 文件，方便知道进度总数。 |
| `stable_json_text (function)` | 把 input/output 等字段转成稳定 JSON 文本，并保留原字段顺序。 |
| `rough_bpe_token_count (function)` | 粗略估算 BPE token 数。 |
| `simple_unit_token_count (function)` | 更直观的单位切分：CJK 单字、英文数字片段、非空白符号。 |
| `token_count (function)` | 核心内部接口 |
| `input_node_count (function)` | 核心内部接口 |
| `load_sample_field (function)` | 核心内部接口 |
| `collect_rows (function)` | 核心内部接口 |
| `percentile (function)` | 核心内部接口 |
| `number_summary (function)` | 核心内部接口 |
| `histogram_bins (function)` | 核心内部接口 |
| `build_summary (function)` | 核心内部接口 |
| `ok_rows (function)` | 核心内部接口 |
| `context_threshold_rows (function)` | 核心内部接口 |
| 其他内部接口 | 另有 12 个辅助接口，详见源码。 |

## 输入、输出与口径

- 输入字段、候选筛选和异常状态以“核心逻辑”及源码校验条件为准。
- 统计脚本需区分扫描文件数、有效文件数和参与数值计算的样本数，避免分母混淆。
- 输出目录不会自动上传，也不应覆盖原始数据集。

[返回 通用数据分析与配置生成索引](README.md)
