# visualize_node_failure_reroute_dataset.py

> 代码位置：[`topology_visualizer/visualize_node_failure_reroute_dataset.py`](../../topology_visualizer/visualize_node_failure_reroute_dataset.py)

## 功能与业务价值

将 `node_failure_reroute_dataset_from_raw/with_answer` 中的节点故障绕行任务转换为可交互静态 HTML，用于直观核查故障注入、链路失效和标准绕行答案是否一致。

页面以原始完整拓扑作为底图，并明确区分：

- 红色虚线节点：`task_failed_node_id` 指定的故障节点。
- 红色虚线边与红色叉号：节点故障后被移除的全部关联链路。
- 绿色粗线：`task_answer.paths` 中的标准绕行路径。
- 蓝色节点：任务源节点。
- 紫色节点：任务目标节点。
- 灰色细线：故障后未参与标准答案的其他物理链路。

## 核心逻辑

1. 读取任务样本中的完整 `nodes`、`links`、任务节点字段和 `task_answer`。
2. 因为节点故障会同时移除该节点及其全部关联边，脚本从原始链路中筛选所有端点包含 `task_failed_node_id` 的链路作为失效边。
3. 将答案中的每条节点序列转换为无向边集合，标记答案路径经过的节点和链路。
4. 校验答案的起止节点、跳数、故障节点排除情况，以及每一跳是否存在于原始拓扑。
5. 以源节点最短距离进行确定性分层布局，并优先排列答案路径节点。
6. 默认只显示源节点、目标节点、故障节点和答案路径节点的标签；开启“全部节点标签”后，使用多候选位置和矩形碰撞检测减少标签遮挡。
7. 生成逐样本 HTML、可筛选总索引和 `visualization_summary.json` 汇总。

页面支持完整拓扑/任务相关视图切换、单条答案路径高亮、节点搜索、缩放、适配视图，以及节点和链路详情检查。所有资源均内嵌在 HTML 中，不依赖外部服务。

## 参数

| 参数 | 说明 |
|---|---|
| `dataset_root` | `with_answer` 根目录、某个 split 目录或单个任务 JSON。默认：`node_failure_reroute_dataset_from_raw/with_answer`。 |
| `-o, --output-root` | HTML 和汇总文件输出目录。默认：`/tmp/node_failure_reroute_visualizations`。 |
| `--split {train,val,all}` | 根目录包含 `train/val` 时选择处理范围。默认：`all`。 |
| `--max-files` | 按文件名字典序最多处理多少个 JSON，默认不限制。 |
| `--progress-interval` | 每处理多少个文件输出一次进度，`0` 表示关闭。默认：`20`。 |

## 输入输出

输入必须保留任务构造阶段的完整拓扑，并包含 `task_source_node_id`、`task_target_node_id`、`task_failed_node_id` 和 `task_answer.paths`。脚本只读取数据，不修改原始 JSON。

输出目录保持输入的相对路径结构。`index.html` 用于选择样本，逐样本页面用于拓扑检查，`visualization_summary.json` 记录扫描文件数、生成页面数、校验异常和错误文件。

[返回 拓扑可视化索引](README.md)
