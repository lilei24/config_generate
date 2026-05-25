# config_generate

配置生成任务项目。

## 数据集分析

在模型开发前，可以使用 `scripts/analyze_dataset.py` 对图 JSON 数据集做统计分析。
数据集目录结构应为：

```text
dataset_root/
  train/
    *.json
  val/
    *.json
```

如果希望直接在命令行指定路径，运行：

```bash
python3 scripts/analyze_dataset.py /path/to/dataset_root -o analysis_output
```

也可以直接修改 `scripts/analyze_dataset.py` 顶部的默认路径：

```python
DEFAULT_DATASET_ROOT = Path("/data/my_dataset")
DEFAULT_OUTPUT_DIR = Path("/tmp/config_analysis")
```

然后不带参数运行：

```bash
python3 scripts/analyze_dataset.py
```

脚本只依赖 Python 标准库，运行后会输出以下文件：

- `dataset_summary.json`：train/val 总量、图规模概览、常见 config 顶层 key。
- `graph_stats.csv`：每张图一行，包含节点数、边数、度数、连通分量和数据质量统计。
- `node_field_stats.csv`：节点属性 JSON path、出现比例、类型分布和高频取值。
- `link_field_stats.csv`：链路字段 JSON path、出现比例、类型分布和高频取值。
- `config_path_stats.csv`：config 叶子字段 JSON path，其中 `[]` 表示 list 通配符，
  并统计类型分布和取值分布。
- `config_template_stats.csv`：常见 config path 集合模板。
- `group_config_stats.csv`：按常见设备字段和拓扑字段分组后的 config/template 分布。
- `data_quality_issues.jsonl`：JSON 解析错误、节点/链路格式异常、链路端点缺失、
  节点 id 重复、config 不是 list 等数据质量问题。

## 节点数核查

如果只想核查每个图的节点数，可以运行：

```bash
python3 scripts/analyze_node_counts.py datasets -o /tmp/node_count_analysis
```

也可以修改 `scripts/analyze_node_counts.py` 顶部的默认路径：

```python
DEFAULT_DATASET_ROOT = Path("datasets")
DEFAULT_OUTPUT_DIR = Path("/tmp/node_count_analysis")
```

然后直接运行：

```bash
python3 scripts/analyze_node_counts.py
```

输出文件包括：

- `node_count_summary.json`：节点数总体统计，包含 count、min、max、mean、median。
- `node_counts.csv`：每个 JSON 一行，包含 split、文件路径、节点数、状态和异常详情。
- `node_counts.txt`：便于直接查看和人工对照的逐图节点数文本。
- `node_count_histogram.csv`：节点数分布柱状图使用的数据。
- `node_count_histogram.svg`：节点数分布柱状图，可直接用浏览器打开。

## 配置生成训练集

使用 `scripts/build_config_generation_dataset.py` 可以从图 JSON 构造配置生成
训练样本。当前每个原始 JSON 最多生成两个样本：

- 从所有 node config 顶层 key 中随机选择 1 个，构造节点配置预测样本。
- 从所有 deviceGroup configs 顶层 key 中随机选择 1 个，构造全局设备配置预测样本。

每个样本只遮挡 1 个顶层配置 key，其他节点配置、deviceGroup 配置、节点信息和
链路信息仍保留在输入上下文中。当前默认遮挡策略会从输入 JSON 删除目标顶层 key；
如果该 key 所在的 config 对象被删空，则同时删除这个空 config 对象。

运行：

```bash
python3 scripts/build_config_generation_dataset.py datasets -o QA
```

也可以修改脚本顶部默认路径后直接运行：

```python
DEFAULT_DATASET_ROOT = Path("datasets")
DEFAULT_OUTPUT_DIR = Path("QA")
```

```bash
python3 scripts/build_config_generation_dataset.py
```

构造过程会默认每处理 100 个源 JSON 打印一次进度，包括已处理数量、百分比、
耗时、速度、预计剩余时间和已生成样本数。可以通过参数调整：

```bash
python3 scripts/build_config_generation_dataset.py datasets -o QA --progress-interval 50
```

如果不想打印进度：

```bash
python3 scripts/build_config_generation_dataset.py datasets -o QA --progress-interval 0
```

输出文件包括：

- `train/node_config_qa/*.json`：由 `datasets/train/` 构造的节点配置预测样本。
- `train/device_config_qa/*.json`：由 `datasets/train/` 构造的全局设备配置预测样本。
- `val/node_config_qa/*.json`：由 `datasets/val/` 构造的节点配置预测样本。
- `val/device_config_qa/*.json`：由 `datasets/val/` 构造的全局设备配置预测样本。
- `build_summary.json`：原始文件数、候选配置 key 数、生成样本数和缺失目标统计。
- `build_issues.jsonl`：无法解析或顶层结构异常的源 JSON。

每个样本文件使用和原始 JSON 相同的文件名。样本结构如下：

```json
{
  "prompt": "请根据给定网络图上下文预测...",
  "input": {
    "nodes": [],
    "links": []
  },
  "output": {
    "cloud-ap-interfaces": {}
  },
  "metadata": {
    "source_file": "train/example.json",
    "target": {
      "source_kind": "node",
      "config_key": "cloud-ap-interfaces"
    }
  }
}
```

目标选择与遮挡方式在脚本中分开注册：

- `TARGET_SELECTORS` 当前只有 `random`，后续可新增偏向前部或后部 key 的选择器。
- `MASK_STRATEGIES` 当前只有 `remove_random_key`，后续可新增占位符遮挡等方式。

## QA input token 分布

构造 QA 后，可以统计每个样本 `input` 的 token 数量，用来评估需要的模型上下文长度：

```bash
python3 scripts/analyze_qa_tokens.py QA -o QA_token_analysis
```

默认使用 `rough_bpe` 近似估算 token 数。不同大模型 tokenizer 会有差异，因此这个
结果适合先判断上下文长度量级；确定具体模型后，可以再接入对应 tokenizer 做精确统计。

输出文件包括：

- `qa_input_token_summary.json`：整体、按 train/val、按 node/device 的 token 统计。
- `qa_input_token_counts.csv`：每个 QA 文件一行的 token、字符、字节数明细。
- `qa_input_token_top_longest.csv`：token 最长的样本，方便优先排查超长输入。
- `qa_input_token_histogram.csv`：柱状图数据。
- `qa_input_token_histogram.svg`：token 分布柱状图，可直接用浏览器打开。
