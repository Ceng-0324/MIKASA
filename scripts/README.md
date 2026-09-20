# 脚本

这里保存可重复的检查、生成、审计和运行辅助脚本。

`check_docs.py` 是只读检查：验证文档相对链接、空白和 canonical 读取顺序，覆盖尚未纳入 Git 的文档。`probe_hermes.py` 显式调用真实模型，覆盖人格、拆解、审查、代码回归、完整任务链，以及主动源码检索、分页搜索/分段读取和同会话红绿修复工具循环；只使用合成仓库，报告放在被忽略的 runtime 下，命令见 [联调记录](../docs/HERMES_CCH_VALIDATION.md)。`probe_chat.py` 额外验证真实 HTTP 聊天、切换前后上下文和默认模型恢复，使用内存临时 API token，不需要配置生产聊天凭据。正式运行入口为 `python3.12 -m mikasa`，不维护第二套启动脚本。外部写入和部署边界以当前任务授权与工程契约为准。

`probe_commands.py --config CONFIG` 不调用模型，直接验证安装的 Hermes 命令注册表、别名、参数解析及 version 执行器。`probe_chat.py --slash --commands` 增加原生历史传递、/init 未执行、/new 幂等、旧记录保留与新会话上下文隔离验收。
