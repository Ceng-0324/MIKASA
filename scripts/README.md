# 验收脚本

正式入口是 `python3.12 -m mikasa`。这些脚本用于可重复验收，不是聊天 UI；输出报告放在被忽略的 runtime，勿提交认证或原始会话。

| 脚本 | 依赖与范围 |
| --- | --- |
| `package_vm.py PATH` | 标准库/Git；从干净提交生成带文件清单的 VM 发布包 |
| `check_docs.py` | 标准库；相对链接、空白及 canonical 顺序 |
| `probe_commands.py --config CONFIG` | 固定 SDK；命令注册、别名、参数与版本，无模型请求 |
| `probe_native_cli.py` | 固定 SDK/本地模型目录夹具；原生命令、跨协议选择、偏好、恢复与启动退出 |
| `probe_native_offline.py` | 固定 SDK；旧会话迁移、身份、按需工程 skills、历史检索及工具发现、原生记忆与工具策略 |
| `probe_native_events.py` | 真实 Gateway/本地模型夹具；SSE、幂等、取消、完整备份及新目录恢复后的会话/记忆/回执 |
| `probe_chat.py --config CONFIG --target MODEL --slash --commands --report PATH` | **真实 CCH 调用**；鉴权 HTTP 聊天、跨协议切换、命令与历史 |
| `probe_native_state.py` | **真实 CCH 调用**；原生记忆、skills、账号隔离、重启、跨协议和取消 |

`probe_engineering.py --config CONFIG --model MODEL` 通过完整原生 CLI 使用真实 CCH 完成合成仓库修复、测试、后台进程、委派、本地提交、共享记忆与会话续接。加 `--entry gateway` 验证聊天 Gateway 的相同工程能力和原生进度/最终事件；平台显示与实际投递需单独验收。隔离 profile，不访问 GitHub 或消息平台；默认只输出结果，`--report PATH` 可选。

有参数的探针先查看 `--help`；无参数脚本直接运行。固定 SDK、模型来源准备见 [执行器](../workers/hermes/README.md)。探针使用临时 profile/合成仓库，不发布 GitHub 或飞书内容。真实模型验证与本地夹具的证据分别记录，见 [验证边界](../docs/VALIDATION.md)。
