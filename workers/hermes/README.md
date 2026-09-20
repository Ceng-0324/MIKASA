# Hermes 执行器

接口依据：NousResearch/hermes-agent 提交 `f9524d3f119c672e4a4444f56d582e7475716ba3` 的 `run_agent.py`、`agent/turn_facade.py` 和 `model_tools.py`。已读取这些官方源码核对构造参数、空工具集和 `final_response` 返回结构；尚未完成真实模型联调。

`bridge.py` 使用 Hermes 的 `AIAgent`，以独立进程接收一份 JSON 请求、输出一份 JSON 结果。将 Hermes 安装到独立虚拟环境后，在配置中设置：

```json
"command": ["/opt/hermes/.venv/bin/python", "/opt/mikasa/workers/hermes/bridge.py"]
```

Hermes 必须安装到该解释器可导入的位置。模型环境变量为 `MIKASA_MODEL`、`MIKASA_MODEL_BASE_URL`、`MIKASA_MODEL_API_KEY`；它们可以指向 CCH 提供的兼容端点。`HERMES_HOME` 必须设置为 Mikasa 专用绝对路径，不能复用个人 home。不复制本机 Codex/Claude 认证。

桥接明确关闭 Hermes 工具、上下文自动发现、记忆和后台 review；Mikasa 注入三份 canonical 规则和有大小限制的仓库快照。写文件、验证、提交、发布、身份检查由宿主完成，模型不能直接获得 GitHub 或控制面 token。持久任务记忆由 Mikasa SQLite 保存。

实现任务采用结构化生成和宿主验证；验证失败时回传失败证据和当前 diff，默认最多修复 3 轮。超过上限后保留工作区和阻塞状态，通过 `retry` 发起新尝试。上下文优先读取规则和变更文件；大型仓库被截断时记录 omitted，任何变更文件被省略都会阻止批准，其他省略项写入审查限制。此适配尚不具备交互式源码检索工具，不能宣称覆盖任意规模的仓库。
