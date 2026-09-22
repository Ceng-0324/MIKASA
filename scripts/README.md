# 验收脚本

正式入口是 `python3.12 -m mikasa`。这些脚本用于可重复验收，不是聊天 UI；输出报告放在被忽略的 runtime，勿提交认证或原始会话。

| 脚本 | 依赖与范围 |
| --- | --- |
| `package_vm.py PATH` | 标准库/Git；从干净提交生成带文件清单的 VM 发布包 |
| `check_docs.py` | 标准库；相对链接、空白及 canonical 顺序 |
| `probe_native_cli.py` | 固定 SDK/本地模型目录夹具；原生命令、跨协议选择、偏好、恢复与启动退出 |
| `probe_native_offline.py` | 固定 SDK；身份、按需工程 skills、历史检索及工具发现、原生记忆与工具策略 |
| `probe_native_state.py --config CONFIG --model MODEL` | **真实 CCH 调用**；原生会话重启续接、新会话历史检索、聊天/工程共享记忆与临时进度不入长期记忆 |

`probe_engineering.py --config CONFIG --model MODEL` 通过完整原生 CLI 使用真实 CCH 完成合成仓库修复、测试、后台进程、委派、本地提交、共享记忆与会话续接。平台显示与实际投递由原生 Gateway 单独验收。隔离 profile，不访问 GitHub 或消息平台；默认只输出结果，`--report PATH` 可选。

有参数的探针先查看 `--help`；无参数脚本直接运行。固定 SDK、模型来源准备见 [执行器](../workers/hermes/README.md)。探针使用临时 profile/合成仓库，不发布 GitHub 或飞书内容。真实模型验证与本地夹具的证据分别记录，见 [验证边界](../docs/VALIDATION.md)。
