# 配置生成数据集构造脚本

本目录记录 `inference` 分支中的配置生成 QA 数据集构造代码。生成的数据由 `inference/` 下的批量推理与评估脚本使用。

## 重点代码

| 脚本 | 构建方式 | 适用场景 |
|---|---|---|
| [build_config_generation_dataset.py](build_config_generation_dataset.md) | 从原始 `datasets/<split>/*.json` 直接构建配置生成 QA，不限制 Input Token。 | 构建完整上下文版本的基础数据集。 |
| [build_config_generation_dataset_pruned.py](build_config_generation_dataset_pruned.md) | 从原始 `datasets/<split>/*.json` 构建数据集；当图超过指定 Input Token 阈值时，先删除距离随机中心最远的部分节点，再选择配置目标并生成 QA。 | 从原始数据重新构建满足指定 Input Token 上限的数据集。 |

这两个脚本都是从原始拓扑开始构建数据集，彼此独立：

- 不需要限制上下文长度时，使用 `build_config_generation_dataset.py`。
- 需要限制上下文长度并允许重新选择配置目标时，使用 `build_config_generation_dataset_pruned.py`。

## 已有 QA 的节点裁剪

[prune_config_generation_qa.py](prune_config_generation_qa.md) 不是另一种原始数据构建入口。它以 `build_config_generation_dataset.py` 等脚本已经生成的 QA 为输入，在现有样本的 `input` 上删除节点：

- 输入为 `QA/<split>/<task>/*.json`，不是原始 `datasets/<split>/*.json`。
- 使用样本已有的 `metadata.target.node_id` 作为主要裁剪中心。
- 保留原来的 `prompt`、`output` 和 `metadata.target`，不会重新选择目标节点或目标配置 Key。
- 只修改 `input.nodes` 和相关的 `input.links`，输出到新的 `QA_post_pruned` 目录。

因此，已经通过基础脚本构建好 QA，并希望在**不改变预测目标和答案**的情况下删除节点、限制 Input Token 时，直接使用 `prune_config_generation_qa.py`，不需要重新构建目标。

## 使用关系

```text
原始拓扑 JSON
  │
  ├─ build_config_generation_dataset.py
  │      └─> 完整上下文 QA
  │              └─ prune_config_generation_qa.py
  │                     └─> 保持原 target 不变的 QA_post_pruned
  │
  └─ build_config_generation_dataset_pruned.py
         └─> 从原始图重新构建的 Token 受限 QA
```

## 选择建议

| 当前情况 | 使用脚本 |
|---|---|
| 第一次构建，不限制 Input Token | `build_config_generation_dataset.py` |
| 从原始图重新构建 Token 受限数据集 | `build_config_generation_dataset_pruned.py` |
| 已有 QA，希望 target 和 answer 完全不变，只删除部分节点 | `prune_config_generation_qa.py` |

[返回文档中心](../README.md)
