# generate_topology_visualizations.py

> 代码位置：[`topology_visualizer/generate_topology_visualizations.py`](../../topology_visualizer/generate_topology_visualizations.py)

## 功能与业务价值

为原始拓扑数据集生成无需外部依赖的交互式 HTML 可视化。

**业务价值：** 让不熟悉原始 JSON 的人员快速检查设备角色、类型、连通分量和拓扑异常。

## 核心逻辑

1. 解析拓扑节点、链路及任务扩展字段，构造适合前端消费的轻量数据。
2. 采用确定性初始布局和无外部依赖的 HTML/CSS/JavaScript 绘制交互视图。
3. 生成总索引和逐文件页面，支持筛选、缩放、详情检查及异常定位。

## 参数

| 参数 | 说明 |
|---|---|
| `dataset_root` | 数据集根目录。默认：datasets |
| `-h, --help` | 显示当前脚本的完整命令帮助后退出。 |
| `-o OUTPUT_ROOT, --output-root OUTPUT_ROOT` | 可视化输出目录。默认：/tmp/topology_visualizations |
| `--split {train,val,all}` | 处理 train、val 或全部数据。默认：all |
| `--max-files MAX_FILES` | 每个 split 最多处理的文件数，默认不限制。 |
| `--progress-interval PROGRESS_INTERVAL` | 每处理 N 个文件打印一次进度，0 表示关闭。默认：20 |

参数表以当前代码的 `--help` 为准。路径参数均相对于运行命令所在目录解析。

### 关键默认值

| 常量 | 当前值 |
|---|---|
| `DEFAULT_DATASET_ROOT` | `'datasets'` |
| `DEFAULT_OUTPUT_ROOT` | `'/tmp/topology_visualizations'` |
| `DEFAULT_PROGRESS_INTERVAL` | `20` |

## 运行方式

```bash
python topology_visualizer/generate_topology_visualizations.py --help
```

确认数据路径和输出路径后，可去掉 `--help` 并传入上表参数执行。

## 关键接口

| 接口 | 职责 |
|---|---|
| `GraphData (class)` | 核心内部接口 |
| `scalar_text (function)` | 核心内部接口 |
| `get_device (function)` | 核心内部接口 |
| `get_device_name (function)` | 核心内部接口 |
| `get_device_type (function)` | 核心内部接口 |
| `get_device_role (function)` | 核心内部接口 |
| `role_color (function)` | 核心内部接口 |
| `connected_components (function)` | 核心内部接口 |
| `calculate_initial_positions (function)` | 有 CORE 时按距离分层，否则按连通分量给出确定性的圆形初始布局。 |
| `parse_graph (function)` | 核心内部接口 |
| `json_for_script (function)` | 核心内部接口 |
| `graph_page (function)` | 核心内部接口 |
| `index_page (function)` | 核心内部接口 |
| `list_json_files (function)` | 核心内部接口 |
| `write_text (function)` | 核心内部接口 |
| `output_html_path (function)` | 核心内部接口 |
| 其他内部接口 | 另有 1 个辅助接口，详见源码。 |

## 输入、输出与口径

- 输入字段、候选筛选和异常状态以“核心逻辑”及源码校验条件为准。
- 输出为静态 HTML，可直接在浏览器打开，不依赖 CDN 或后端服务。
- 可视化用于人工检查，不改变原始拓扑或任务答案。

[返回 拓扑可视化索引](README.md)
