# 执行 workers

当前执行器为 [Hermes JSON 桥接](hermes/README.md)；Codex、Claude 保留为可选接入，不是当前运行依赖。协议由 `mikasa/worker.py` 定义：单次 stdin JSON 请求、stdout `{"version":1,"result":{...},"runtime":{...}}`，result 字段按任务类型校验，runtime 保存规则/skill 指纹、SDK 版本、请求模型和工具禁用证据，错误输出不持久化，以免泄露模型凭据。

worker 是执行单元，不是权限来源。它的报告、commit 和 PR 都必须按当前 revision 核实；由 Mikasa 或其 worker 实现的 PR 不能通过更换 worker 身份绕过负责人审批。

进程具有环境变量白名单、超时、输出上限和整组取消。Hermes 工具关闭；文件变更和验证由宿主在独立工作区完成。Codex/Claude 的本地 `config.toml`、`auth.json`、环境变量和 home 目录不迁入本目录，生产凭据由专用运行环境注入。
