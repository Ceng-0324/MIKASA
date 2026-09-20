# 验证

使用 `python3.12 -m unittest discover -v` 运行标准库 unittest。测试创建临时 Git 仓库，启动真正的 JSON worker 子进程和本地 HTTP 服务，GitHub 使用模拟适配器；不需要 token，不修改 FluxCore，不产生外部写入。

覆盖实现验证和提交、修复反馈、任务依赖与幂等、并发认领、中断恢复、取消、越界和符号链接拒绝、环境隔离、HTTP 鉴权、webhook 验签、审查版本/CI 证据过期、Agent 结论保留、旧审批档案保留及发布歧义恢复。聊天测试还覆盖自然语言命令边界、会话归属、验证失败保留、切换重放、并发/暂停与上下文截断。文档检查使用 `python3.12 scripts/check_docs.py`。

隔离测试不能证明真实模型效果；本轮额外执行了 [Hermes/CCH 联调](../docs/HERMES_CCH_VALIDATION.md)。GitHub 账号权限、分支保护、真实 Docker 镜像和 systemd 部署仍待验收。

命令/会话测试覆盖 `/new` 原子创建与重放、暂停回滚、跨账号隔离、控制回执不进入模型历史、命令进程不读或继承凭据。普通 Chat 测试使用明确的命令回执夹具；真实 Hermes 参数语义由 `scripts/probe_commands.py` 单独验收，不用夹具替代官方兼容证据。

以上 Chat 回执测试对应暂留的 HTTP/`--message` API。终端入口另验证直接启动原生 CLI、不创建业务服务、TTY 与凭据隔离、profile 互斥、SIGTERM 清理、配置偏好保留与坏文件保护。`scripts/probe_native_cli.py` 通过真实固定 SDK 和本地模型目录验证原生命令、跨协议解析及会话恢复，不消耗模型额度，不代替真实 CCH 可用性验收。

工程 profile 测试覆盖账号绑定、共享原生记忆但隔离会话、旧数据留档、同任务互斥与异常释放、链接及路径越界拒绝。`scripts/probe_engineering_state.py` 独立验证固定 SDK 与真实 Docker 的续话、压缩链和跨进程记忆，不以模拟 SDK 替代依赖兼容证据，详见 [0008](../docs/decisions/0008-engineering-state.md)。

修复循环回归确认最终检查失败只调用一次 worker、不自动重试、不提交失败版本；显式 retry 获得上次最终验收证据，旧 max_attempts 不恢复外层循环。真实 SDK/Docker 实施链验证见 [0009](../docs/decisions/0009-native-repair-loop.md)。

任务测试现在直接使用固定 Hermes Kanban SDK，先按 [worker 安装](../workers/hermes/README.md) 准备源码与 Python 环境。CI 仅安装 requirements-kanban.txt 的控制面依赖，完整模型/Docker 探针另用完整环境。迁移与并发场景见 [0010](../docs/decisions/0010-native-kanban.md)；缺少 SDK 时任务测试明确失败，不退回自研队列。
