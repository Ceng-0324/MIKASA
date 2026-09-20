# 脚本

这里保存可重复的检查、生成、审计和运行辅助脚本。

保留的 probe 脚本是正式验收工具，不作为用户交互入口。重复的早期 Gateway 快速探针已删除，其身份、重启与持久化检查由 `probe_native_state.py` 覆盖；自研网页聊天调试入口也已移除。终端系统命令进入 Hermes 原生 CLI，鉴权消息接口暂留旧命令适配。

`check_docs.py` 是只读检查：验证文档相对链接、空白和 canonical 读取顺序，覆盖尚未纳入 Git 的文档。`probe_hermes.py` 显式调用真实模型，覆盖人格、拆解、审查、代码回归、完整任务链，以及主动源码检索、分页搜索/分段读取和同会话红绿修复工具循环；只使用合成仓库，报告放在被忽略的 runtime 下，命令见 [联调记录](../docs/HERMES_CCH_VALIDATION.md)。`probe_chat.py` 额外验证真实 HTTP 聊天、切换前后上下文和默认模型恢复，使用内存临时 API token，不需要配置生产聊天凭据。正式运行入口为 `python3.12 -m mikasa`，不维护第二套启动脚本。外部写入和部署边界以当前任务授权与工程契约为准。

`probe_commands.py --config CONFIG` 不调用模型，直接验证安装的 Hermes 命令注册表、别名、参数解析及 version 执行器。`probe_chat.py --slash --commands` 增加原生历史传递、/init 未执行、/new 幂等、旧记录保留与新会话上下文隔离验收。

`probe_native_state.py` 使用一次性 profile 验证真实原生记忆、skills、身份注入、账号隔离、重启、跨协议与取消。`probe_native_offline.py` 不调用模型，使用固定 SDK 验证旧库迁移、plugin 与工具策略。见 [原生验收](../docs/NATIVE_HERMES_VALIDATION.md)。

`probe_native_cli.py` 使用固定 SDK、一次性 profile、本地 HTTP 模型目录及合成凭据，直接执行官方 CLI 命令分派，验证 GPT/Claude 协议切换、历史保留、/new、/resume、全局偏好重载、persona 和正式入口启动退出。不会向 CCH 发起模型调用，不读取真实认证；验证范围见 [0007](../docs/decisions/0007-native-cli.md)。

`probe_native_sandbox.py --report runtime/state/hermes-cch/native-sandbox-proof.json` 使用真实 Docker 验证原生文件/终端与网络、密钥、资源和清理边界。`probe_hermes.py` 的 lifecycle、tool-loop、tool-plan、tool-review、paged-context 现使用原生工程路径，不再验证旧自研工具。

`probe_native_engineering_offline.py --report runtime/state/hermes-cch/native-engineering-offline-proof.json` 不调用模型，验证原生只读文件/shell、真实读取证据和杀死 SDK 进程后的容器回收。工程联调的宿主独立检查也使用真实 Docker check_image。

`python3.12 scripts/probe_engineering_state.py` 使用固定 SDK、真实 Docker、临时仓库和本地 HTTP 模型夹具，验证 Worker→bridge→AIAgent 的续话、工具历史去重、失败后恢复、压缩后续、账号记忆双向可见、并发原生记忆写入、身份/skills 注入及容器 ID/清理。需要本机固定 SDK 环境和已缓存工程镜像，不读取真实模型认证、不调用 CCH，也不证明真实模型一定遵循记忆约定。

该探针另走正式 Service 实施任务链：在同一次 Hermes 调用中原生写文件、调用真实 Docker 检查、修复并复查；验证最终验收通过才提交、未修好时 blocked、不启动外层修复、工具检查变绿后又改坏仍被最终检查拦截。所有提交仅在一次性夹具仓库内。

`python3.12 scripts/probe_native_events.py` 启动真实固定 Hermes Gateway，用临时 profile、本地模型夹具和合成 Key 验证 SSE 完成通知、同一 run 重放、取消与读取线程清理、重启恢复、原生记忆/工具历史及身份/skills 证据。不读取真实 CCH 配置，不使用正式 profile；它补充事件传输契约，不替代 `probe_native_state.py` 的真实 CCH 跨协议验收。见 [0012](../docs/decisions/0012-native-run-events.md)。
