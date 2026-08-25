# build_structure_hints_from_csv.py

> 代码位置：[`inference/build_structure_hints_from_csv.py`](../../inference/build_structure_hints_from_csv.py)

## 功能与业务价值

**从结构分布生成 Prompt 提示。** 读取结构分布 CSV，把高频 Path 还原为带类型占位符的嵌套 JSON，并生成 `TOP_LEVEL_KEY_STRUCTURE_HINTS` Python 文件。

**业务价值：** 把离线结构统计转化为可直接用于推理 Prompt 的兜底先验，减少缺少同名上下文时的结构幻觉。

## 核心逻辑

1. 筛选 `sample_count` 大于配置阈值的结构，可按 split/task 过滤。
2. 解析对象路径与数组 `[]`，合并为树形结构。
3. 按叶子类型生成 `<string>`、`<number>`、`<boolean>` 等占位值。
4. 同一顶层 Key 保留多个满足阈值的常见结构。

## 参数

| 参数 | 说明 | 默认值或约束 |
|---|---|---|
| `--input-csv` | 控制该脚本对应处理行为。 | 默认：`DEFAULT_INPUT_CSV` |
| `--output-file` | 控制该脚本对应处理行为。 | 默认：`DEFAULT_OUTPUT_FILE` |
| `--min-sample-count` | Keep rows whose sample_count is strictly greater than this value. Default: 5. | 默认：`DEFAULT_MIN_SAMPLE_COUNT` |
| `--splits` | 逗号分隔的数据划分，例如 `train,val`。 | 默认：`''` |
| `--tasks` | 逗号分隔的任务目录，例如 `node_config_qa,device_config_qa`。 | 默认：`''` |

路径参数相对于执行命令时的当前工作目录解析；运行 `--help` 可查看代码中的即时说明。

### 关键默认值

| 常量 | 当前代码表达式 |
|---|---|
| `DEFAULT_INPUT_CSV` | `Path('output-structure-analysis/output_structure_distribution.csv')` |
| `DEFAULT_OUTPUT_FILE` | `Path('top_level_key_structure_hints.py')` |
| `DEFAULT_MIN_SAMPLE_COUNT` | `5` |
| `VALUE_PLACEHOLDER` | `'<VALUE>'` |

## 运行方式

```bash
python inference/build_structure_hints_from_csv.py --help
```

建议先用 `--limit` 小规模验证路径、服务和输出格式，再运行完整 split。

## 输入与输出

**主要输出：**

- 默认生成包含 `TOP_LEVEL_KEY_STRUCTURE_HINTS` 的 Python 文件。

**统计口径与异常：**

- 扫描文件数、模型错误数、解析/评估错误数和有效评估数应分开理解，指标分母以代码实际纳入的有效对象为准。
- 推理结果目录属于实验产物，不应覆盖 QA 数据源；改变预测字段名时需同步检查 `pred-keys`。

## 关键接口

| 接口 | 类型 | 职责 |
|---|---|---|
| `PathNode` | class | 实现该脚本的核心处理步骤。 |
| `parse_csv_values` | function | 实现该脚本的核心处理步骤。 |
| `unescape_path_key` | function | 实现该脚本的核心处理步骤。 |
| `parse_path` | function | Parse paths emitted by analyze_output_structures.py. |
| `insert_path` | function | 实现该脚本的核心处理步骤。 |
| `path_tree` | function | 实现该脚本的核心处理步骤。 |
| `node_to_value` | function | Convert a path trie into a JSON-like skeleton. |
| `structure_from_paths` | function | 实现该脚本的核心处理步骤。 |
| `read_distribution_rows` | function | 实现该脚本的核心处理步骤。 |
| `build_hints` | function | 实现该脚本的核心处理步骤。 |
| `write_python_file` | function | 实现该脚本的核心处理步骤。 |
| `parse_args` | function | 实现该脚本的核心处理步骤。 |
| `main` | function | 实现该脚本的核心处理步骤。 |

## 相关文档

- [analyze_output_structures.py](analyze_output_structures.md)
- [batch_infer_qa.py](batch_infer_qa.md)

[返回 inference 脚本索引](README.md)
