# visualize_node_failure_ap_impact_dataset.py

> 代码位置：[`topology_visualizer/visualize_node_failure_ap_impact_dataset.py`](../../topology_visualizer/visualize_node_failure_ap_impact_dataset.py)

## 功能与业务价值

将 `node_failure_ap_impact_dataset/with_answer` 中的节点故障影响面任务转换为交互式静态 HTML，用于检查指定非 AP 节点故障后，标准答案中的失联 AP 是否与原始拓扑相符。

页面使用以下视觉语义：

- 红色虚线节点：`task_failed_node_id` 指定的故障节点。
- 红色虚线边和叉号：故障节点失效后被移除的全部关联链路。
- 橙色节点：`task_answer.disconnected_ap_ids` 中的失联 AP。
- 灰色节点和链路：未被答案判定为失联的其他节点及正常物理链路。

## 核心逻辑

1. 读取完整拓扑、故障节点、角色优先级、Question 和 Answer。
2. 根据故障节点 ID 标记故障设备及其全部关联边。
3. 根据 `disconnected_ap_ids` 标记答案中的失联 AP，并校验节点是否存在、角色是否为 AP。
4. 按节点到故障设备的最短距离进行确定性分层布局，同一层优先排列失联 AP。
5. 节点圆内只显示简化 ID 和 `DEVICEROLE`，设备名称、TYPE、MODEL、度数和影响状态在点击节点后显示。
6. 默认只显示故障节点的外部完整标签，避免 large 样本中大量失联 AP 标签遮挡；“显示完整标签”可以展开全部 `ID · DEVICEROLE`。
7. 右侧固定显示 Question 和格式化 Answer，节点或链路详情只更新右侧顶部区域。
8. 生成逐样本 HTML、可筛选索引和 `visualization_summary.json`。

页面支持节点拖拽、完整拓扑/仅影响面切换、节点搜索、缩放、适配视图及节点和链路详情检查，不依赖 CDN 或后端服务。

## 参数

| 参数 | 说明 |
|---|---|
| `dataset_root` | `with_answer` 根目录、split 目录或单个任务 JSON。默认：`node_failure_ap_impact_dataset/with_answer`。 |
| `-o, --output-root` | HTML 输出目录。默认：`/tmp/node_failure_ap_impact_visualizations`。 |
| `--split {train,val,all}` | 选择数据划分。默认：`all`。 |
| `--max-files` | 按文件名字典序限制处理数量，默认不限制。 |
| `--progress-interval` | 每处理多少个文件打印一次进度，`0` 表示关闭。默认：`20`。 |

## 输入输出

输入必须包含 `nodes`、`links`、`task_failed_node_id` 和 `task_answer.disconnected_ap_ids`。脚本不修改任务 JSON。

输出目录保持输入相对路径结构，入口为 `index.html`；`visualization_summary.json` 汇总页面数、失联 AP 总数、校验异常和错误文件。

[返回 拓扑可视化索引](README.md)
