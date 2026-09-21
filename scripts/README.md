# 验收脚本

正式入口是 `python3.12 -m mikasa`。这些脚本用于可重复验收，不是聊天 UI；输出报告放在被忽略的 runtime，勿提交认证或原始会话。

| 脚本 | 依赖与范围 |
| --- | --- |
| `check_docs.py` | 标准库；相对链接、空白及 canonical 顺序 |
| `probe_commands.py --config CONFIG` | 固定 SDK；命令注册、别名、参数与版本，无模型请求 |
| `probe_native_cli.py` | 固定 SDK/本地模型目录夹具；原生命令、跨协议选择、偏好、恢复与启动退出 |
| `probe_native_offline.py` | 固定 SDK；旧会话迁移、身份、工程 skills、原生记忆与工具策略 |
| `probe_native_events.py` | 真实 Gateway/本地模型夹具；SSE、幂等、取消、完整备份及新目录恢复后的会话/记忆/回执 |
| `probe_engineering_state.py` | 固定 SDK、Docker 和本地模型夹具；工程续话、压缩、共享记忆、工具修复和最终验收 |
| `probe_native_sandbox.py` | 固定 SDK/Docker；文件与终端隔离、网络、密钥、资源和清理 |
| `probe_native_engineering_offline.py` | 固定 SDK/Docker；只读工程、读取证据与强制退出清理，无模型请求 |
| `probe_hermes.py --config CONFIG --report PATH` | **真实 CCH 调用**；合成人格、拆解、审查、实现、任务链、工具循环及分页上下文 |
| `probe_chat.py --config CONFIG --target MODEL --slash --commands --report PATH` | **真实 CCH 调用**；鉴权 HTTP 聊天、跨协议切换、命令与历史 |
| `probe_native_state.py` | **真实 CCH 调用**；原生记忆、skills、账号隔离、重启、跨协议和取消 |

有参数的探针先查看 `--help`；无参数脚本直接运行。固定 SDK、模型来源及镜像准备见 [执行器](../workers/hermes/README.md)。探针使用临时 profile/合成仓库，不发布 GitHub 或飞书内容；Docker 探针需要已缓存镜像。真实模型验证与本地夹具的证据分别记录，见 [验证边界](../docs/VALIDATION.md)。
