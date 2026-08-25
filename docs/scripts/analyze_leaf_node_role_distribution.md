# analyze_leaf_node_role_distribution.py

> 代码位置：[`scripts/analyze_leaf_node_role_distribution.py`](../../scripts/analyze_leaf_node_role_distribution.py)

## 功能与业务价值

统计原始拓扑数据中叶子节点的 DEVICEROLE 分布。

叶子节点严格定义为物理邻居数量 degree == 1 的节点：

- links 统一按无向物理连接处理，不考虑 source/target 方向；
- 同一对节点之间的重复链路只贡献一个邻居；
- 自环不计入邻居；
- degree == 0 的节点单独统计为孤立节点，不算叶子节点。

脚本输出一个格式化 JSON，顶层包含 summary 和 per_file；终端打印处理进度、
速度、ETA，以及叶子节点内部的 DEVICEROLE 分布。

**业务价值：** 检验图论叶子与业务角色的关系，避免把 CORE 等拓扑端点误当作接入终端。

## 核心逻辑

1. 按 split 递归读取 JSON，并将坏 JSON、缺失字段和类型异常分开计数。
2. 依据模块定义的统计口径提取字段或构造无向图，完成逐文件计算。
3. 聚合全局及分组结果，输出 CSV/JSON/SVG 等可复核产物并打印进度。

## 参数

| 参数 | 说明 |
|---|---|
| `dataset_root` | 数据集根目录，内含 train/ 和 val/。默认：datasets |
| `-h, --help` | 显示当前脚本的完整命令帮助后退出。 |
| `-o OUTPUT_DIR, --output-dir OUTPUT_DIR` | 统计结果输出目录。默认：/tmp/leaf_node_role_analysis |
| `--split {train,val,all}` | 统计范围：train、val 或 all。默认：all |
| `--progress-interval PROGRESS_INTERVAL` | 每 N 张图打印一次进度。0 表示不打印。默认：50 |

参数表以当前代码的 `--help` 为准。路径参数均相对于运行命令所在目录解析。

### 关键默认值

| 常量 | 当前值 |
|---|---|
| `DEFAULT_DATASET_ROOT` | `'datasets'` |
| `DEFAULT_OUTPUT_DIR` | `'/tmp/leaf_node_role_analysis'` |
| `DEFAULT_PROGRESS_INTERVAL` | `50` |

## 运行方式

```bash
python scripts/analyze_leaf_node_role_distribution.py --help
```

确认数据路径和输出路径后，可去掉 `--help` 并传入上表参数执行。

## 关键接口

| 接口 | 职责 |
|---|---|
| `GraphLeafRoleResult (class)` | 核心内部接口 |
| `iter_json_files (function)` | 核心内部接口 |
| `list_split_json_files (function)` | 核心内部接口 |
| `load_graph (function)` | 核心内部接口 |
| `get_device_role (function)` | 核心内部接口 |
| `analyze_graph (function)` | 核心内部接口 |
| `distribution (function)` | 核心内部接口 |
| `build_role_leaf_rates (function)` | 计算每种角色内部的叶子节点比例，而不是角色在叶子节点中的占比。 |
| `build_scope_statistics (function)` | 核心内部接口 |
| `write_json (function)` | 核心内部接口 |
| `terminal_bar (function)` | 核心内部接口 |
| `print_terminal_summary (function)` | 核心内部接口 |
| `build_statistics (function)` | 核心内部接口 |

## 输入、输出与口径

- 输入字段、候选筛选和异常状态以“核心逻辑”及源码校验条件为准。
- 统计脚本需区分扫描文件数、有效文件数和参与数值计算的样本数，避免分母混淆。
- 输出目录不会自动上传，也不应覆盖原始数据集。

[返回 通用数据分析与配置生成索引](README.md)
