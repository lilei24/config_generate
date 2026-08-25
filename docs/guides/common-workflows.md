# 标准工作流

## 1. 原始数据检查

先运行节点数、边数、字段结构、名称唯一性和角色分布分析，确认坏 JSON、空图和长尾大图比例。

## 2. 构造任务数据集

选择 `scripts/build_task_dataset/` 下的任务构建器。检查终端 `skip reasons`、样本数和 with/without_answer 文件是否一一对应。

## 3. 批量推理

使用 `scripts/infer_eval/batch_infer_*_vllm.py` 或 `*_opencode.py`。先确认模型、服务地址、split、输入根目录、输出根目录和断点续跑参数。

## 4. 自动评估

使用同任务的 `evaluate_*_results.py`。指标从结果 JSON 的 `task_answer` 与 `model-output` 计算；路径任务必须区分跳数准确率、路径有效率、路径集合 Precision/Recall/F1 和完全正确率。

## 5. 误差分析

结合逐文件指标、SwanLab 曲线、OpenCode 轨迹和拓扑可视化定位问题。VLAN 任务还需检查每条路径链路两端端口是否都允许目标 VLAN。
