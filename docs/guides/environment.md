# 运行环境

## 基础要求

- Python 3.9 及以上。
- 大部分数据分析和任务构建脚本只依赖 Python 标准库。
- vLLM 推理入口需要 OpenAI-compatible 服务和 `openai` Python 包。
- SwanLab 评估需要安装并登录 `swanlab`。
- OpenCode 入口需要可执行的 `opencode`、正确的模型 Provider 配置、工作目录权限和拓扑 Provider 环境变量。

## 建议执行方式

从仓库根目录运行脚本，使相对路径默认值稳定：

```bash
cd /path/to/config_generate
python scripts/<script>.py --help
```

批量任务先在少量文件上测试，再扩展到完整 train/val。输出目录应与原始数据目录分离。
