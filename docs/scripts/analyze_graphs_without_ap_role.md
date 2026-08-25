# analyze_graphs_without_ap_role.py

> 代码位置：[`scripts/analyze_graphs_without_ap_role.py`](../../scripts/analyze_graphs_without_ap_role.py)

## 功能与业务价值

统计原始拓扑数据中不包含 DEVICEROLE=AP 节点的 JSON 文件。

**业务价值：** 负责原始拓扑质量分析、配置生成 QA 构建以及模型辅助业务分析。

## 核心逻辑

1. 按 split 递归读取 JSON，并将坏 JSON、缺失字段和类型异常分开计数。
2. 依据模块定义的统计口径提取字段或构造无向图，完成逐文件计算。
3. 聚合全局及分组结果，输出 CSV/JSON/SVG 等可复核产物并打印进度。

## 参数

| 参数 | 说明 |
|---|---|
| `dataset_root` | 原始数据集根目录，目录下应包含 train/val，默认: datasets |
| `-h, --help` | 显示当前脚本的完整命令帮助后退出。 |
| `-o OUTPUT_DIR, --output-dir OUTPUT_DIR` | 统计结果目录，默认: /tmp/graphs_without_ap_role_analysis |
| `--split {train,val,all}` | 统计 train、val 或全部数据，默认: all |
| `--progress-interval PROGRESS_INTERVAL` | 每处理 N 个文件打印进度，0 表示关闭，默认: 100 |

参数表以当前代码的 `--help` 为准。路径参数均相对于运行命令所在目录解析。

### 关键默认值

| 常量 | 当前值 |
|---|---|
| `DEFAULT_DATASET_ROOT` | `'datasets'` |
| `DEFAULT_OUTPUT_DIR` | `'/tmp/graphs_without_ap_role_analysis'` |
| `DEFAULT_SPLIT` | `'all'` |
| `DEFAULT_PROGRESS_INTERVAL` | `100` |
| `SUMMARY_FILE` | `'graphs_without_ap_role_summary.json'` |
| `DETAIL_FILE` | `'graphs_without_ap_role.csv'` |
| `ERROR_FILE` | `'analysis_errors.csv'` |

## 运行方式

```bash
python scripts/analyze_graphs_without_ap_role.py --help
```

确认数据路径和输出路径后，可去掉 `--help` 并传入上表参数执行。

## 关键接口

| 接口 | 职责 |
|---|---|
| `iter_json_files (function)` | 核心内部接口 |
| `load_json_object (function)` | 核心内部接口 |
| `analyze_roles (function)` | 返回有效节点数量和严格 DEVICEROLE 字符串分布。 |
| `write_csv (function)` | 核心内部接口 |
| `run (function)` | 核心内部接口 |

## 输入、输出与口径

- 输入字段、候选筛选和异常状态以“核心逻辑”及源码校验条件为准。
- 统计脚本需区分扫描文件数、有效文件数和参与数值计算的样本数，避免分母混淆。
- 输出目录不会自动上传，也不应覆盖原始数据集。

[返回 通用数据分析与配置生成索引](README.md)
