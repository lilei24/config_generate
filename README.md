# config_generate

Initial repository for config generation work.

## Dataset analysis

Use `scripts/analyze_dataset.py` to summarize graph JSON datasets before model
development. The expected dataset layout is:

```text
dataset_root/
  train/
    *.json
  val/
    *.json
```

Run:

```bash
python3 scripts/analyze_dataset.py /path/to/dataset_root -o analysis_output
```

You can also edit the local defaults at the top of
`scripts/analyze_dataset.py`:

```python
DEFAULT_DATASET_ROOT = Path("/data/my_dataset")
DEFAULT_OUTPUT_DIR = Path("/tmp/config_analysis")
```

Then run without arguments:

```bash
python3 scripts/analyze_dataset.py
```

The script only uses the Python standard library and writes these reports:

- `dataset_summary.json`: split totals, graph-size summaries, top config keys.
- `graph_stats.csv`: one row per graph with node, edge, degree, component, and
  data-quality counts.
- `node_field_stats.csv`: node attribute JSON paths, presence ratios, type
  counts, and top values.
- `link_field_stats.csv`: link JSON paths, presence ratios, type counts, and
  top values.
- `config_path_stats.csv`: config leaf JSON paths using `[]` as the list
  wildcard, plus type and value distributions.
- `config_template_stats.csv`: frequent config path-set templates.
- `group_config_stats.csv`: config/template distribution grouped by common
  device and topology fields.
- `data_quality_issues.jsonl`: parse errors, malformed nodes/links, missing
  link endpoints, duplicate node ids, non-list config values, and related
  issues.
