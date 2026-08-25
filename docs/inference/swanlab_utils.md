# swanlab_utils.py

> 代码位置：[`inference/swanlab_utils.py`](../../inference/swanlab_utils.py)

## 功能与业务价值

**SwanLab 公共工具。** 集中封装 SwanLab 导入、运行配置、指标命名、micro/macro 累计、样本表格和结束逻辑。

**业务价值：** 保证多个推理与评估入口上传相同字段，减少实验之间因日志实现差异造成的不可比。

## 核心逻辑

1. 记录 Python 版本、Git commit、脚本名和命令行参数。
2. 将指标映射为稳定的 `field_path/*`、`leaf_triple/*` 等名称。
3. macro 对有效样本指标求算术平均；micro 先累计正确数和预测/答案总数再计算。
4. 统一样本表头和 JSON 可读格式。

## 代码实现说明

- SwanLab 采用延迟导入，未安装依赖时只在实际使用实验功能时抛出明确错误，不影响纯本地评估脚本。
- 运行配置从 `argparse.Namespace` 转成可序列化字典，并补充 Python 版本、当前脚本和 `git rev-parse --short HEAD`；Path 自动转成字符串。
- 单样本日志统一映射为九条数值曲线。macro 聚合对有效样本同名指标求 `mean`；micro 聚合调用离线评估累加器，先汇总原始计数再生成指标。
- 样本表固定列顺序，并将 prompt、input、预测和答案转成带缩进的可读 JSON 文本。表格通过 `swanlab.echarts.Table` 构造，当前 SwanLab 版本缺少该能力时会显式报错。

## 参数

该文件是公共库模块，没有独立命令行参数，供其他脚本导入调用。


## 输入与输出

**主要输出：**

- 该文件是库模块，不直接写文件。

**统计口径与异常：**

- 扫描文件数、模型错误数、解析/评估错误数和有效评估数应分开理解，指标分母以代码实际纳入的有效对象为准。
- 推理结果目录属于实验产物，不应覆盖 QA 数据源；改变预测字段名时需同步检查 `pred-keys`。


[返回 inference 脚本索引](README.md)
