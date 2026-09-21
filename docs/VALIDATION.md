# 验证边界

固定 Hermes 0.21.3，revision `f9524d3f119c672e4a4444f56d582e7475716ba3`。本机为 macOS arm64 / Python 3.12.13；没有执行目标 Linux VM、远端 Python 3.13 CI 或 Hermes 上游完整测试套件。

## 本地验证

最近一次全量代码验证对应 `06d50bf`：专项 27 项、全量 195 项 unittest 通过（257.557 秒），文档、默认及本机配置 doctor、CLI 帮助和 diff 检查通过。覆盖账号绑定、凭据隔离、原生启动、消息准入、任务/调度、回执、备份恢复及失败路径；该版本已移除旧 `feishu` 别名，消息统一走 `gateway --platform`。

固定 SDK 与本地夹具已验证 CLI 命令、GPT/Claude 跨协议选择、SessionDB、MEMORY/USER、身份/skills、SSE、取消、幂等、Kanban、Cron 和状态恢复。Docker 夹具另验证工程续话、压缩、共享记忆、工具修复、隔离与最终验收。脚本及依赖见[验收脚本](../scripts/README.md)。这些结果不能替代真实模型或平台验收。

## 真实服务

| 范围 | 已验证 | 剩余边界 |
| --- | --- | --- |
| CCH | 合成工程任务、GPT Responses / Claude Messages 会话切换、真实聊天请求 | `default` 分组缺管理端同次路由证据；响应模型名不能证明底层模型身份 |
| GitHub | 真实 token 调用 `/user`，确认 `Mikasa-0910` | 仓库读写、正式 Review、webhook 未验收 |
| 飞书 | 官方应用探针、WebSocket、负责人 `/help` 和普通消息往返 | 开放用户、未 @ 群聊与机器人策略通过固定 SDK 检查，真实群聊未验收 |
| 微信 | 原生扫码、与飞书共用一个 Gateway、真实入站、CCH 回复；两条原生投递记录为 delivered，主人确认 `/help` 与普通消息收到回复 | `/model`、`/new` 和跨会话记忆仍待微信渠道验收；普通微信群不在当前 iLink 接入能力内 |
| 身份与 skills | 真实请求中 identity、policy、persona_skill、skills_index 均为 true | 加载证据不保证每次模型回答均遵循规则 |
| 微信主人关联 | 真实发送者 ID 与本机绑定一致，关联 `Ceng-0324`；新 SOUL 与插件已加载，双平台恢复 connected | 新身份提示的称呼尚未通过后续模型回答单独验收 |

## 运行限制

- 私聊、群聊与话题采用 Hermes 原生会话划分；同一 profile 共享长期记忆与系统命令能力，不是每人的独立沙箱。
- 微信启动曾出现一次 iLink 连接失败，随后恢复并成功投递；`connected` 本身不能证明持续收发正常。
- macOS profile 路径过长会触发可选 liveness UNIX socket 警告；消息连接正常，VM 使用短路径后复验。
- 原生 `/sethome` 生成的 profile `.env` 与禁止额外环境注入的检查冲突。历史投递设置已保存在本机 `native-home-channel.env.saved`，不应当作缓存删除。
- 自定义 CCH provider 下 `/new` 不可靠地恢复默认模型；同进程 `/model --global` 不刷新启动快照。显式 `/model ID` 可切换，保存默认值在重启后生效。
- VM、TLS、部署恢复演练、聊天工程入口及 FluxCore 联合验收尚未完成。推进顺序见[计划](../MIKASA_FUNCTION_PLAN.md)。

## 证据维护

本文件只维护当前结论和限制，逐轮记录保留在 Git 历史。清理前详细记录可用 `git show 18563e6:docs/VALIDATION.md` 查看；更早报告见 `git show 3b436b1:docs/VALIDATION.md`。旧验证不证明后续代码；功能变更更新对应验收结论，纯文档整理的检查结果记录在提交说明中。

运行状态、会话、记忆、凭据和请求回执留在本机。过期二维码、已关闭的调试日志和可再生成字节码可以清理；固定 Hermes 源码及 Python 环境虽位于 `runtime/cache`，仍是运行依赖。
