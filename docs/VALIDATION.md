# 验证边界

固定 Hermes 0.21.3，revision `f9524d3f119c672e4a4444f56d582e7475716ba3`。已验证 macOS arm64 / Python 3.12.13，以及 OrbStack Ubuntu 26.04 arm64 / Python 3.12.14；未执行远端 Python 3.13 CI 或 Hermes 上游完整测试套件。

## 本地验证

当前全量 200 项 unittest 在 macOS 通过（323.921 秒）；本次原生 profile、消息接入与备份专项 36 项在 macOS 和目标 Linux VM 均通过。直接使用固定 Hermes `/sethome` handler 验证保存、profile 刷新、进程重启及不携带 `.env` 的恢复；原生投递目标的线程和身份信息通过配置备份保留。VM 上一次全量检查为 `a1a47d3` 的 198 项；本轮 Linux 仅复验受影响专项。

固定 SDK 与本地夹具已验证 CLI 命令、GPT/Claude 跨协议选择、SessionDB、MEMORY/USER、身份/skills、SSE、取消、幂等、Kanban、Cron 和状态恢复。Docker 夹具另验证工程续话、压缩、共享记忆、工具修复、隔离与最终验收。脚本及依赖见[验收脚本](../scripts/README.md)。这些结果不能替代真实模型或平台验收。

## 真实服务

| 范围 | 已验证 | 剩余边界 |
| --- | --- | --- |
| CCH | 合成工程任务、GPT Responses / Claude Messages 会话切换、真实聊天请求 | `default` 分组缺管理端同次路由证据；响应模型名不能证明底层模型身份 |
| GitHub | 真实 token 调用 `/user`，确认 `Mikasa-0910` | 仓库读写、正式 Review、webhook 未验收 |
| 飞书 | 官方应用探针、WebSocket、负责人 `/help` 和普通消息往返；开放群聊策略通过固定 SDK 检查 | 发言人以实际发送者元数据识别；同一 profile 共享长期记忆 |
| 微信 | 原生扫码、统一 Gateway、真实入站与 CCH 回复；VM 迁移后主人确认 `/help`、普通消息、切换 Claude 并切回 GPT 正常 | 记忆提示修复后使用隔离原生 API 自动复验，未重复手机端测试；普通微信群不在当前 iLink 接入能力内 |
| 身份与 skills | 真实请求中 identity、policy、persona_skill、skills_index 均为 true | 加载证据不保证每次模型回答均遵循规则 |
| 微信主人关联 | 真实发送者 ID 与本机绑定一致，关联 `Ceng-0324`；新 SOUL 与插件已加载，双平台恢复 connected | 新身份提示的称呼尚未通过后续模型回答单独验收 |
| OrbStack VM | `mylinux` Ubuntu 26.04，Python 3.12.14，固定 Hermes 及依赖检查、systemd 校验；GPT/Claude 真实探针、飞书认证、GitHub `/user` 通过；飞书/微信均 connected，主人确认双渠道 `/help` 与普通消息正常 | 未部署独立云主机、Docker 工程执行或公网 API |

2026-09-22 已将消息服务切换到 VM `/var/lib/mikasa`，专用用户 `mikasa`、单元 `mikasa-gateway.service` 已 enable，Mac 原 Gateway 已退出。迁移 534 个条目，保留 20 个会话、92 条消息、3 条原生会话路由；两份 MEMORY/USER 文件 SHA-256 与源一致（MEMORY 当前为空，不能据此声称已有跨会话记忆验收）。VM 实际停服、备份、恢复到新目录、重启后再次验证数据和双平台连接；尚未演练 Mac 重启或进程异常后的自动拉起。恢复点和运维命令见 [VM 手册](../deploy/vm/README.md)。

迁移后手机验收由主人确认全部所列步骤正常；VM 新增飞书、微信各一轮用户/助手消息，消息总数从 92 增至 96。原生 delivered 计数从飞书 8 / 微信 4 增至 9 / 6；新增请求的人格、工程规则、persona skill 与 skills 索引加载证据均为 true。手机确认的模型切换与独立 GPT/Claude 探针分别记录，不将加载布尔值当作每轮人格表达质量的保证。

日常交互修复后，在 VM 隔离 profile 中通过真实 CCH 验证自然语言明确要求记忆会调用原生 memory 并写入磁盘；关闭 Gateway 进程、保留合法投递 `.env`、启动新进程并创建空会话后，能正确读回随机标记。身份、工程规则、人格 skill 与 skills 索引加载证据均通过。测试未修改正式记忆或向消息平台发信，隔离状态已清理；正式消息服务更新后双渠道重新 connected。

## 运行限制

- 私聊、群聊与话题采用 Hermes 原生会话划分；同一 profile 共享长期记忆与系统命令能力，不是每人的独立沙箱。
- 微信启动曾出现一次 iLink 连接失败，随后恢复并成功投递；`connected` 本身不能证明持续收发正常。
- macOS profile 路径过长曾触发可选 liveness UNIX socket 警告；VM 已改用 `/var/lib/mikasa` 短路径，连接证据以当前进程写入的原生状态为准。
- `/sethome` 的 profile `.env` 冲突已修复并部署到 VM：允许飞书/微信原生投递字段，启动从 `config.yaml` 读回完整目标；外部凭据仍显式注入。历史 `native-home-channel.env.saved` 保留，原飞书目标已在 canonical 配置中，无需覆盖或重新设置。
- 自定义 CCH provider 下 `/new` 不可靠地恢复默认模型；同进程 `/model --global` 不刷新启动快照。显式 `/model ID` 可切换，保存默认值在重启后生效。
- OrbStack 依赖 Mac 在线；独立公网 VM、TLS、聊天工程入口及 FluxCore 联合验收尚未完成。消息服务主动出站，不以公网 API 为前提。推进顺序见[计划](../MIKASA_FUNCTION_PLAN.md)。

## 证据维护

本文件只维护当前结论和限制，逐轮记录保留在 Git 历史。清理前详细记录可用 `git show 18563e6:docs/VALIDATION.md` 查看；更早报告见 `git show 3b436b1:docs/VALIDATION.md`。旧验证不证明后续代码；功能变更更新对应验收结论，纯文档整理的检查结果记录在提交说明中。

运行状态、会话、记忆、凭据和请求回执留在本机。过期二维码、已关闭的调试日志和可再生成字节码可以清理；固定 Hermes 源码及 Python 环境虽位于 `runtime/cache`，仍是运行依赖。
