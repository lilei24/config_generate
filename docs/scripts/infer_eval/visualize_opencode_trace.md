# visualize_opencode_trace.py

> 代码位置：[`scripts/infer_eval/visualize_opencode_trace.py`](../../../scripts/infer_eval/visualize_opencode_trace.py)

## 功能与业务价值

将 OpenCode stdout JSON 事件流转换为离线 HTML 轨迹查看器。

**业务价值：** 把 Agent 事件流还原为可读轨迹，支持定位工具调用、权限、超时和答案生成问题。

## 核心逻辑

1. 解析拓扑节点、链路及任务扩展字段，构造适合前端消费的轻量数据。
2. 采用确定性初始布局和无外部依赖的 HTML/CSS/JavaScript 绘制交互视图。
3. 生成总索引和逐文件页面，支持筛选、缩放、详情检查及异常定位。

## 参数

| 参数 | 说明 |
|---|---|
| `input_path` | 单个 *.stdout.txt 文件或包含这些文件的目录 |
| `-h, --help` | 显示当前脚本的完整命令帮助后退出。 |
| `--output OUTPUT` | 单文件模式可指定 HTML 文件；批量模式指定输出目录 |
| `--result-root RESULT_ROOT` | 包含推理结果 train/val 目录的根目录；默认根据 `_raw` 所在位置自动推断 |
| `--title TITLE` | 页面标题，默认: OpenCode Agent 轨迹 |
| `--max-detail-chars MAX_DETAIL_CHARS` | 单个事件在 HTML 中最多保留的字符数，0 表示不限制 |

参数表以当前代码的 `--help` 为准。路径参数均相对于运行命令所在目录解析。

### 关键默认值

| 常量 | 当前值 |
|---|---|
| `DEFAULT_INPUT_PATH` | `'opencode-results/_raw'` |
| `DEFAULT_OUTPUT_PATH` | `'opencode-traces'` |
| `DEFAULT_MAX_DETAIL_CHARS` | `200000` |

## 运行方式

```bash
python scripts/infer_eval/visualize_opencode_trace.py --help
```

确认数据路径和输出路径后，可去掉 `--help` 并传入上表参数执行。

## 关键接口

| 接口 | 职责 |
|---|---|
| `TraceEvent (class)` | 核心内部接口 |
| `TraceSummary (class)` | 核心内部接口 |
| `compact_text (function)` | 核心内部接口 |
| `stringify (function)` | 核心内部接口 |
| `nested_value (function)` | 核心内部接口 |
| `event_part (function)` | 核心内部接口 |
| `event_type_name (function)` | 核心内部接口 |
| `event_timestamp (function)` | 核心内部接口 |
| `event_text (function)` | 核心内部接口 |
| `tool_name (function)` | 核心内部接口 |
| `tool_state (function)` | 核心内部接口 |
| `tool_arguments (function)` | 核心内部接口 |
| `tool_output (function)` | 核心内部接口 |
| `classify_event (function)` | 核心内部接口 |
| `parse_json_stream (function)` | 解析连续 JSON，并将无法解析的非空行作为普通日志保留。 |
| `truncate_detail (function)` | 核心内部接口 |
| 其他内部接口 | 另有 18 个辅助接口，详见源码。 |

## 输入、输出与口径

- 输入字段、候选筛选和异常状态以“核心逻辑”及源码校验条件为准。
- 推理结果以原答案文档为基础增加 `model-output` 和运行状态，错误原因不得静默丢弃。
- 评估时必须区分扫描样本、模型成功样本、结构可解析样本和实际参与指标平均的样本。
- SwanLab 是观测渠道，本地 CSV/JSON 才是可重复复核的指标结果。

[返回 批量推理与评估索引](README.md)
