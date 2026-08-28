# 任务拓扑可视化

**对应代码目录：** [`task_visualizer/`](../task_visualizer/)

[返回文档总览](README.md)

可视化模块将三类 `with_answer` 任务数据集转换为可交互 HTML。每个样本生成独立拓扑页面，同时生成可筛选的 `index.html`，用于检查任务构造、演示答案和定位异常样本。

## 公共交互能力

- 节点圆内显示节点 ID 和 `DEVICEROLE`。
- 点击节点查看设备名称、物理类型、角色、型号和任务身份。
- 点击链路查看 source、target、`LEFTPORT`、`RIGHTPORT` 和链路标签。
- 右侧固定展示 `task_question` 和 `task_answer`。
- 支持拓扑缩放、视口拖动、节点拖动、搜索、标签开关和任务元素过滤。
- 缩放只作用于拓扑画布，不放大工具栏和详情面板。
- 汇总首页支持按文件名、任务节点和 train/val 划分筛选。

## 脚本与中文任务

| 中文任务名称 | 可视化脚本 | 展示重点 |
|---|---|---|
| 节点故障约束路径查询 | [`visualize_node_failure_reroute_dataset.py`](../task_visualizer/visualize_node_failure_reroute_dataset.py) | 故障节点、失效链路、源目标和标准绕行路径 |
| 故障影响AP节点 | [`visualize_node_failure_ap_impact_dataset.py`](../task_visualizer/visualize_node_failure_ap_impact_dataset.py) | 故障节点、关联失效链路和受影响 AP |
| 可达下游终端节点 | [`visualize_downstream_reachable_terminal_dataset.py`](../task_visualizer/visualize_downstream_reachable_terminal_dataset.py) | 所选上游、同角色上游、答案终端和连接路径 |

## 节点故障约束路径查询可视化

视觉编码：

- 红色虚线节点：故障节点。
- 红色虚线链路：随故障节点被删除的链路。
- 蓝色节点：源节点。
- 紫色节点：目标节点。
- 绿色节点和链路：标准答案路径。

右侧路径列表支持逐条点击高亮，适合检查多条等长路径共享的局部链路。

参数：

| 参数 | 默认值 | 作用 |
|---|---:|---|
| `dataset_root` | `node_failure_reroute_dataset_from_raw/with_answer` | with_answer 根目录、split 目录或单个 JSON |
| `-o, --output-root` | `/tmp/node_failure_reroute_visualizations` | HTML 输出目录 |
| `--split` | `all` | `train`、`val` 或 `all` |
| `--max-files` | 不限制 | 最多处理的 JSON 数量 |
| `--progress-interval` | `20` | 进度打印间隔 |

## 故障影响AP节点可视化

视觉编码：

- 红色虚线节点和链路：故障设备及其关联失效链路。
- 橙色节点：`task_answer.impacted_ap_ids` 中的 AP。
- 灰色节点和链路：未标记的原始物理拓扑。

页面摘要显示故障节点、受影响 AP 数量、影响等级和失效链路数量。

参数：

| 参数 | 默认值 | 作用 |
|---|---:|---|
| `dataset_root` | `node_failure_ap_impact_dataset/with_answer` | with_answer 根目录、split 目录或单个 JSON |
| `-o, --output-root` | `/tmp/node_failure_ap_impact_visualizations` | HTML 输出目录 |
| `--split` | `all` | `train`、`val` 或 `all` |
| `--max-files` | 不限制 | 最多处理的 JSON 数量 |
| `--progress-interval` | `20` | 进度打印间隔 |

## 可达下游终端节点可视化

视觉编码：

- 蓝色节点：任务指定的 CORE 或 Firewall 上游节点。
- 绿色节点和路径：答案中的下游终端及其连接路径。
- 紫色虚线节点：参与最近距离竞争的其他同角色上游节点。
- 灰色节点和链路：其他物理拓扑。

点击终端节点可查看原图度数及其到所选上游的距离，辅助检查唯一最近归属规则。

参数：

| 参数 | 默认值 | 作用 |
|---|---:|---|
| `dataset_root` | `downstream_reachable_terminal_dataset/with_answer` | with_answer 根目录、split 目录或单个 JSON |
| `-o, --output-root` | `/tmp/downstream_reachable_terminal_visualizations` | HTML 输出目录 |
| `--split` | `all` | `train`、`val` 或 `all` |
| `--max-files` | 不限制 | 最多处理的 JSON 数量 |
| `--progress-interval` | `20` | 进度打印间隔 |

## 输出文件

```text
<output_root>/
├── index.html
├── visualization_summary.json
└── <split>/**/*.html
```

- `index.html`：任务统计、样本列表和筛选入口。
- 单样本 HTML：数据内嵌，无需后端服务即可打开。
- `visualization_summary.json`：生成数量、失败数量和任务统计。

