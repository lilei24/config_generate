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
