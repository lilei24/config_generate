# 配置生成数据集构造脚本

本目录记录 `inference` 分支中的配置生成 QA 数据集构造代码。三个脚本对应基础构造、构造前裁剪和构造后二次裁剪，生成的数据由 `inference/` 下的批量推理与评估脚本使用。

## 脚本导航

| 脚本 | 输入 | 主要作用 |
|---|---|---|
| [build_config_generation_dataset.py](build_config_generation_dataset.md) | 原始 `datasets/train|val/*.json` | 随机选择节点配置和设备组配置的一个顶层 Key，构造两类 QA 样本。 |
| [build_config_generation_dataset_pruned.py](build_config_generation_dataset_pruned.md) | 原始 `datasets/train|val/*.json` | 先将过长原始图裁剪到 Token 阈值，再构造 QA。 |
| [prune_config_generation_qa.py](prune_config_generation_qa.md) | 已生成的 `QA/<split>/<task>/*.json` | 使用既有 metadata 中的目标节点，对 QA 的 `input` 做二次裁剪。 |

## 三者关系

```text
原始拓扑 JSON
  ├─ build_config_generation_dataset.py ───────────> QA
  └─ build_config_generation_dataset_pruned.py ────> QA（包含 context_pruning metadata）
                                                        │
                                                        └─ prune_config_generation_qa.py
                                                           └─> QA_post_pruned
```

- 前两个脚本是两种独立的首次构造方案，不是前后串联关系。
- `build_config_generation_dataset_pruned.py` 不读取基础脚本的输出，而是从原始图重新选择裁剪中心和配置目标。
- `prune_config_generation_qa.py` 才是构造后的处理步骤；它保留既有 `prompt`、`output` 和 `metadata.target`，只改变 `input`。

[返回文档中心](../README.md)
