# 数据与目录

## 原始数据

默认根目录为 `datasets/`，其下包含 `train/` 与 `val/`；每个 JSON 表示一个站点拓扑。核心字段为 `nodes`、`links`、可选的 `deviceGroups`，节点配置主要位于 `nodes[].configs`，历史数据可能使用 `config`。

链路按物理无向图处理，但端口方向保留：`LEFTPORT` 属于 `link.source`，`RIGHTPORT` 属于 `link.target`。

完整字段示例和兼容规则见[数据集格式说明](../dataset_format_notes.md)。

## 配置生成 QA

典型结构为 `QA/{train,val}/{node_config_qa,device_config_qa}/*.json`。样本保留 `prompt`、`input`、`output` 和 `metadata.target`；`output` 是被隐藏的目标配置。

## 图计算任务数据集

任务构建器通常同时产生：

- `with_answer/{train,val}`：包含 `task_answer`，用于评估和答案回填。
- `without_answer/{train,val}`：上下文相同但隐藏答案，用于盲推理。

任务相关节点必须使用 `nodes[].id`，不能依赖可能重名的设备名称。

## 推理结果

推理脚本在有答案文档基础上增加 `model-output` 和 `vllm-run` 或 `opencode-run`。运行状态中的 `success=false` 表示请求、解析或结构校验失败，评估时应明确错误样本是否计入平均值。
