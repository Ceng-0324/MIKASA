# 脚本

这里保存可重复的检查、生成、审计和运行辅助脚本。

`check_docs.py` 是只读检查：验证文档相对链接、空白和 canonical 读取顺序，覆盖尚未纳入 Git 的文档。`probe_hermes.py` 显式调用真实模型，覆盖人格、拆解、审查、代码回归、完整任务链，以及主动源码检索、分页搜索/分段读取和同会话红绿修复工具循环；只使用合成仓库，报告放在被忽略的 runtime 下，命令见 [联调记录](../docs/HERMES_CCH_VALIDATION.md)。`probe_chat.py` 额外验证真实 HTTP 聊天、切换前后上下文和默认模型恢复，使用内存临时 API token，不需要配置生产聊天凭据。正式运行入口为 `python3.12 -m mikasa`，不维护第二套启动脚本。外部写入和部署边界以当前任务授权与工程契约为准。

`probe_commands.py --config CONFIG` 不调用模型，直接验证安装的 Hermes 命令注册表、别名、参数解析及 version 执行器。`probe_chat.py --slash --commands` 增加原生历史传递、/init 未执行、/new 幂等、旧记录保留与新会话上下文隔离验收。

`probe_native_gateway.py` 是真实 Gateway 启动与持久化快速探针；`probe_native_state.py` 使用一次性 profile 验证真实原生记忆、skills、身份注入、账号隔离、重启、跨协议与取消。`probe_native_offline.py` 不调用模型，使用固定 SDK 验证旧库迁移、plugin 与工具策略。见 [原生验收](../docs/NATIVE_HERMES_VALIDATION.md)。

`probe_native_sandbox.py --report runtime/state/hermes-cch/native-sandbox-proof.json` 使用真实 Docker 验证原生文件/终端与网络、密钥、资源和清理边界。`probe_hermes.py` 的 lifecycle、tool-loop、tool-plan、tool-review、paged-context 现使用原生工程路径，不再验证旧自研工具。

`probe_native_engineering_offline.py --report runtime/state/hermes-cch/native-engineering-offline-proof.json` 不调用模型，验证原生只读文件/shell、真实读取证据和杀死 SDK 进程后的容器回收。工程联调的宿主独立检查也使用真实 Docker check_image。
