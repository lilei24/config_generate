# visualize_downstream_reachable_terminal_dataset.py

> 代码位置：[`topology_visualizer/visualize_downstream_reachable_terminal_dataset.py`](../../topology_visualizer/visualize_downstream_reachable_terminal_dataset.py)

## 功能与业务价值

将 `downstream_reachable_terminal_dataset/with_answer` 中的下游可达终端任务转换为交互式静态 HTML，用于核查所选 CORE/Firewall、同角色竞争上游和答案叶子节点之间的拓扑关系。

页面使用以下视觉语义：

- 蓝色节点：问题指定的核心上游节点。
- 绿色节点：`task_answer.downstream_terminal_node_ids` 中的下游终端节点。
- 绿色链路：从所选上游到每个答案叶子的一条确定性最短连接路径，仅用于解释拓扑关系。
- 紫色虚线节点：其他同角色 CORE 或 Firewall，是叶子归属距离比较的竞争节点。
- 灰色节点和链路：其他原始物理拓扑。

## 核心逻辑

1. 读取 `task_upstream_node_id`、Question、Answer 和完整原始拓扑。
2. 将链路按无向简单图处理，计算节点度数和到所选上游的最短距离。
3. 校验答案节点存在、度数等于 1、设备类型为 AP/LSW、自身不是 CORE/Firewall、能够到达所选上游，并确认没有距离更近或等距的同角色竞争上游。
4. 为每个答案叶子恢复一条按节点 ID 确定性选择的最短连接路径，构成绿色解释子图；该路径不是任务答案的一部分。
5. 按距所选上游的跳数分层布局，答案叶子在同层优先排列；与所选上游不可达的分量在主图下方紧凑排列，避免横向拉伸。
6. 节点圆内只显示 ID 和 `DEVICEROLE`，点击节点后在右侧展示名称、TYPE、MODEL、度数、距离和任务身份。
7. 右侧固定展示 Question、格式化 Answer 和答案连接路径，点击对象不会覆盖任务内容。
8. 生成逐样本 HTML、可筛选索引和 `visualization_summary.json`。

页面支持完整拓扑/任务相关视图切换、节点拖拽、节点搜索、缩放、适配视图及节点和链路详情检查，不依赖外部服务。

## 参数

| 参数 | 说明 |
|---|---|
| `dataset_root` | `with_answer` 根目录、split 目录或单个任务 JSON。默认：`downstream_reachable_terminal_dataset/with_answer`。 |
| `-o, --output-root` | HTML 输出目录。默认：`/tmp/downstream_reachable_terminal_visualizations`。 |
| `--split {train,val,all}` | 选择数据划分。默认：`all`。 |
| `--max-files` | 按文件名字典序限制处理数量，默认不限制。 |
| `--progress-interval` | 每处理多少个文件打印进度，`0` 表示关闭。默认：`20`。 |

## 输入输出

输入必须包含 `nodes`、`links`、`task_upstream_node_id` 和 `task_answer.downstream_terminal_node_ids`。脚本只读取任务样本，不修改数据集。

输出目录保持输入相对路径结构，入口为 `index.html`；`visualization_summary.json` 汇总页面数、答案叶子总数、校验异常和错误文件。

[返回 拓扑可视化索引](README.md)
