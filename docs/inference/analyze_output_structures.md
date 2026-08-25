# analyze_output_structures.py

> 代码位置：[`inference/analyze_output_structures.py`](../../inference/analyze_output_structures.py)

## 功能与业务价值

**目标配置结构分布分析。** 按答案顶层 Key 统计 JSON Path 结构类型及样本频次。

**业务价值：** 用于识别同一配置名下的主流与长尾 Schema，并为 Prompt 结构提示或 SFT 分层采样提供依据。

## 核心逻辑

1. 直接读取 QA `output`，不依赖推理结果。
2. 将对象字段和数组层级编码为规范 Path，结构相同样本得到同一 structure id。
3. 按顶层 Key 聚合结构数量、样本数量和占比。
4. 单独输出坏 JSON、缺字段等异常。

## 参数

| 参数 | 说明 | 默认值或约束 |
|---|---|---|
| `--qa-root` | QA 数据根目录，用于读取 prompt、input、output 或关联同名样本。 | 默认：`DEFAULT_QA_ROOT` |
| `--output-root` | 本脚本产物输出目录。 | 默认：`DEFAULT_OUTPUT_ROOT` |
| `--splits` | 逗号分隔的数据划分，例如 `train,val`。 | 默认：`DEFAULT_SPLITS` |
| `--tasks` | 逗号分隔的任务目录，例如 `node_config_qa,device_config_qa`。 | 默认：`DEFAULT_TASKS` |
| `--progress-interval` | 每处理多少个文件打印一次进度；非正数通常表示关闭周期打印。 | 默认：`DEFAULT_PROGRESS_INTERVAL` |
| `--limit` | 最多处理的文件数；`0` 表示不限制。 | 默认：`0` |

路径参数相对于执行命令时的当前工作目录解析；运行 `--help` 可查看代码中的即时说明。

### 关键默认值

| 常量 | 当前代码表达式 |
|---|---|
| `DEFAULT_QA_ROOT` | `Path('520QA')` |
| `DEFAULT_OUTPUT_ROOT` | `Path('output-structure-analysis')` |
| `DEFAULT_SPLITS` | `'train'` |
| `DEFAULT_TASKS` | `'node_config_qa'` |
| `DEFAULT_PROGRESS_INTERVAL` | `500` |

## 运行方式

```bash
python inference/analyze_output_structures.py --help
```

建议先用 `--limit` 小规模验证路径、服务和输出格式，再运行完整 split。

## 输入与输出

**主要输出：**

- `output_structure_per_file.csv`
- `output_top_key_summary.csv`
- `output_structure_distribution.csv`
- `output_structure_paths.json`
- `output_structure_errors.csv`、`output_structure_summary.json`

**统计口径与异常：**

- 扫描文件数、模型错误数、解析/评估错误数和有效评估数应分开理解，指标分母以代码实际纳入的有效对象为准。
- 推理结果目录属于实验产物，不应覆盖 QA 数据源；改变预测字段名时需同步检查 `pred-keys`。

## 关键接口

| 接口 | 类型 | 职责 |
|---|---|---|
| `StructureRow` | class | 实现该脚本的核心处理步骤。 |
| `parse_csv_values` | function | 实现该脚本的核心处理步骤。 |
| `iter_qa_files` | function | Enumerate QA files as qa_root/<split>/<task>/**/*.json. |
| `read_json` | function | 实现该脚本的核心处理步骤。 |
| `escape_path_key` | function | 实现该脚本的核心处理步骤。 |
| `collect_structure_paths` | function | Collect unique JSON paths for one top-level key. |
| `structure_id` | function | 实现该脚本的核心处理步骤。 |
| `collect_rows` | function | 实现该脚本的核心处理步骤。 |
| `paths_text` | function | 实现该脚本的核心处理步骤。 |
| `per_file_rows` | function | 实现该脚本的核心处理步骤。 |
| `valid_rows` | function | 实现该脚本的核心处理步骤。 |
| `structure_counts` | function | 实现该脚本的核心处理步骤。 |
| `top_key_counts` | function | 实现该脚本的核心处理步骤。 |
| `structure_paths_map` | function | 实现该脚本的核心处理步骤。 |
| `build_distribution_rows` | function | 实现该脚本的核心处理步骤。 |
| `build_top_key_summary_rows` | function | 实现该脚本的核心处理步骤。 |
| `build_structure_paths_json` | function | 实现该脚本的核心处理步骤。 |
| `build_error_rows` | function | 实现该脚本的核心处理步骤。 |
| `write_csv` | function | 实现该脚本的核心处理步骤。 |
| `write_json` | function | 实现该脚本的核心处理步骤。 |
| `run` | function | 实现该脚本的核心处理步骤。 |
| `parse_args` | function | 实现该脚本的核心处理步骤。 |

## 相关文档

- [build_structure_hints_from_csv.py](build_structure_hints_from_csv.md)
- [batch_infer_qa.py](batch_infer_qa.md)

[返回 inference 脚本索引](README.md)
