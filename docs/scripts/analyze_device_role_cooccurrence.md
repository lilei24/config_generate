# analyze_device_role_cooccurrence.py

> 代码位置：[`scripts/analyze_device_role_cooccurrence.py`](../../scripts/analyze_device_role_cooccurrence.py)

## 功能与业务价值

统计多个 DEVICEROLE 在同一个拓扑 JSON 中同时出现的文件数。

**业务价值：** 负责原始拓扑质量分析、配置生成 QA 构建以及模型辅助业务分析。

## 核心逻辑

1. 按 split 递归读取 JSON，并将坏 JSON、缺失字段和类型异常分开计数。
2. 依据模块定义的统计口径提取字段或构造无向图，完成逐文件计算。
3. 聚合全局及分组结果，输出 CSV/JSON/SVG 等可复核产物并打印进度。

## 参数

| 参数 | 说明 |
|---|---|
| `dataset_root` | 数据集根目录，目录下应包含 train/val，默认: datasets |
| `-h, --help` | 显示当前脚本的完整命令帮助后退出。 |
| `--device-roles ROLE [ROLE ...]` | 要求在同一文件中同时存在的角色，默认: AP CORE |
| `--split {train,val,all}` | 统计的数据划分，默认: all |
| `-o OUTPUT_DIR, --output-dir OUTPUT_DIR` | 统计结果目录，默认: /tmp/device_role_cooccurrence_analysis |
| `--progress-interval PROGRESS_INTERVAL` | 每处理 N 个文件打印进度，0 表示关闭，默认: 100 |

参数表以当前代码的 `--help` 为准。路径参数均相对于运行命令所在目录解析。

### 关键默认值

| 常量 | 当前值 |
|---|---|
| `DEFAULT_DATASET_ROOT` | `'datasets'` |
| `DEFAULT_OUTPUT_DIR` | `'/tmp/device_role_cooccurrence_analysis'` |
| `DEFAULT_DEVICE_ROLES` | `('AP', 'CORE')` |
| `DEFAULT_SPLIT` | `'all'` |
| `DEFAULT_PROGRESS_INTERVAL` | `100` |
| `SUMMARY_FILE` | `'device_role_cooccurrence_summary.json'` |
| `MATCHED_FILES_FILE` | `'matching_files.csv'` |
| `ERROR_FILE` | `'analysis_errors.csv'` |

## 运行方式

```bash
python scripts/analyze_device_role_cooccurrence.py --help
```

确认数据路径和输出路径后，可去掉 `--help` 并传入上表参数执行。

## 关键接口

| 接口 | 职责 |
|---|---|
| `iter_json_files (function)` | 核心内部接口 |
| `load_json_object (function)` | 核心内部接口 |
| `collect_role_counts (function)` | 核心内部接口 |
| `write_csv (function)` | 核心内部接口 |
| `run (function)` | 核心内部接口 |

## 输入、输出与口径

- 输入字段、候选筛选和异常状态以“核心逻辑”及源码校验条件为准。
- 统计脚本需区分扫描文件数、有效文件数和参与数值计算的样本数，避免分母混淆。
- 输出目录不会自动上传，也不应覆盖原始数据集。

[返回 通用数据分析与配置生成索引](README.md)
