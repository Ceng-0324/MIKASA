# 聊天模型切换与 CCH 路由

日期：2026-09-20。目标：用户在与 Mikasa 聊天时说“切换为某个模型”，后续回复采用该请求模型，并保留对话上下文。

## 实际调研

负责人确认网关为 [ding113/claude-code-hub](https://github.com/ding113/claude-code-hub)。本站首页标识为 AutoBits Claude Code Hub；无法从公开入口确认部署版本。上游源码核对固定 commit `dfeb14331cb350f672e92a3684adecf1052dd476`，不能把上游最新版能力全部当成本站已部署事实。

| 核对对象 | 证据与结论 |
| --- | --- |
| CCH 模型路由 | [provider-selector.ts](https://github.com/ding113/claude-code-hub/blob/dfeb14331cb350f672e92a3684adecf1052dd476/src/app/v1/_lib/proxy/provider-selector.ts)：基于请求模型、供应商 allowedModels 等条件选择供应商；会话绑定不支持新模型时清除旧绑定并重新选择。checkFormatProviderTypeCompatibility 限定 Responses → codex，Messages → claude/claude-auth，Chat → openai-compatible，跨协议不能只改 model |
| CCH 模型重写 | [model-redirector.ts](https://github.com/ding113/claude-code-hub/blob/dfeb14331cb350f672e92a3684adecf1052dd476/src/app/v1/_lib/proxy/model-redirector.ts)：依据供应商 modelRedirects 改写请求 body.model，并记录原始模型及目标模型 |
| CCH 配置热更新 | [provider-cache.ts](https://github.com/ding113/claude-code-hub/blob/dfeb14331cb350f672e92a3684adecf1052dd476/src/lib/cache/provider-cache.ts)：更新发布缓存失效消息；Redis 通知不可用时依赖 30 秒 TTL。生效针对后续请求，不迁移正在生成的流 |
| CCH 回归用例 | [模型不匹配绑定测试](https://github.com/ding113/claude-code-hub/blob/dfeb14331cb350f672e92a3684adecf1052dd476/tests/unit/proxy/provider-selector-model-mismatch-binding.test.ts)：覆盖原会话绑定不能处理新模型时的清除行为。本轮阅读源码，未运行 CCH 上游测试 |
| 模型列表 | [available-models.ts](https://github.com/ding113/claude-code-hub/blob/dfeb14331cb350f672e92a3684adecf1052dd476/src/app/v1/_lib/models/available-models.ts)：支持 models 及 Responses 格式筛选；本站实际 GET 返回 403，错误明确为 Cloudflare 1010 browser_signature_banned，不能推断为 API key 模型权限不足。确认原因后未继续尝试绕过；列表发现不是本次切换的前置条件 |
| Hermes | 固定 `f9524d3f119c672e4a4444f56d582e7475716ba3` 的 [agent_runtime_helpers.py](https://github.com/NousResearch/hermes-agent/blob/f9524d3f119c672e4a4444f56d582e7475716ba3/agent/agent_runtime_helpers.py) 提供 switch_model 与回滚；Gateway 有会话覆盖。Mikasa 当前是一次调用一个 AIAgent，不需要改造成常驻 Gateway 来实现切换 |
| 返回模型证据 | 同一 Hermes 版本的 [turn_response_intake.py](https://github.com/NousResearch/hermes-agent/blob/f9524d3f119c672e4a4444f56d582e7475716ba3/agent/turn_response_intake.py) 在 post_api_request 提供 response_model。bridge 使用公开 PluginContext.register_hook 在进程内记录该字段，不改 SDK 源码、不抓取响应正文或认证头 |

## 决策

复用 CCH 作为唯一上游网关。Mikasa 聊天控制面解释直接用户命令、验证候选模型、保存会话选择，然后用现有 Hermes bridge 将选择放进请求。无需新增 HTTP 代理，也无需 CCH 管理员凭据或修改网关全局映射。

切换范围为当前聊天，用户之间及聊天之间隔离；原工程任务继续使用运行配置。若以后把聊天直接关联到工程任务，需要单独定义任务继承模型的语义。不暗中改变已有任务或个人 Codex/Claude 配置。当前已增加由受信任配置定义的 model_routes，按模型选择对应端点、凭据引用和协议；用户入口统一为 `/model`，不暴露认证设置。

## 行为与失败处理

- 支持“切换为 gpt-5.6-luna”“请把模型切换为 gpt-6-astra”“换成 …”、`/model MODEL_ID`、“恢复默认模型”。模型使用完整 ID；不把“那个”“最强的”等歧义称呼猜成具体模型。复合请求、引用和讨论不会执行切换。
- 切换前以候选模型执行一次真实 Hermes 调用，验证严格 JSON 与 canonical/skill 注入；失败不修改当前模型。请求成功仅证明该名称可被处理；如果返回标识不同，回复明确指出差异，不伪称精确底层模型已切换。
- 每条消息使用独立 worker，并固定 model 到本次进程环境。当前聊天正在处理消息时拒绝并发修改；其他会话不受影响。运行暂停时不提交新选择。
- SQLite 原子保存会话模型、revision、回复与切换事件；进程重建后可继续。Idempotency-Key 防止已完成请求重放；进程在模型调用后、事务提交前崩溃，重试可能再次消耗模型调用，但不会产生仓库副作用。
- 会话全量历史保存在本地数据库，展示和模型上下文取最近 40 轮，并受 max_context_bytes 限制；截断会告知模型。人格与规则每轮重新加载，不依靠上一模型的隐式记忆。
- 模型切换根据受信任 model_routes 选择来源，同步切换本次 worker 的端点、凭据与协议；源配置文件保持只读。桥接支持 Hermes 官方 Responses/Chat/Messages；GPT 与 Claude 可以走各自原生协议，不保证任意 CCH 名称或尚未实现的其他协议可用。

## 入口与验证

提供标准库 CLI 聊天和鉴权 HTTP API，见 [聊天用法](../runbooks/CHAT.md)。早期 `/chat` 网页调试入口已按负责人要求清除，系统命令不依赖网页；任何会话读取与写入都核对账号归属。

真实 HTTP → Chat → Hermes → CCH 验收见 [聊天切换验证](../CHAT_VALIDATION.md)。单元测试覆盖失败保留、跨账号拒绝、会话隔离、重放、并发锁、暂停、上下文截断和真实 worker 参数传递。CCH 后台供应商配置及管理端写入没有执行。

后续收口增加统一配置校验、显式连接探针和安全故障反馈，见 [CCH 诊断](../runbooks/CCH.md)。固定 Hermes 的 [api_request_hooks.py](https://github.com/NousResearch/hermes-agent/blob/f9524d3f119c672e4a4444f56d582e7475716ba3/agent/api_request_hooks.py) 公开 `api_request_error`，携带分类 reason/status；bridge 只取结构化分类并映射固定词表，丢弃 message/request。恢复成功时清除此前错误，避免误报。`default` 分组仍需网关侧 Key 配置与路由证据，本地探针通过不把它自动标记为已切换。

跨协议依据：同一 Hermes revision 的 [agent_init.py](https://github.com/NousResearch/hermes-agent/blob/f9524d3f119c672e4a4444f56d582e7475716ba3/agent/agent_init.py) 接受显式 anthropic_messages，并在 provider=custom 时使用显式 Key，不触发个人 Anthropic OAuth；[命令定义](https://github.com/NousResearch/hermes-agent/blob/f9524d3f119c672e4a4444f56d582e7475716ba3/hermes_cli/commands.py) 确认 /model、/new、/init 为 CLI/Gateway 命令。Mikasa 的嵌入式入口通过 Hermes 共享组件解析 /model，复用 AIAgent 及官方 transport；模型验证和会话事务由宿主处理，详见 [命令与会话归属](0003-hermes-commands-sessions.md)。不启动另一套 CLI 会话或推理循环。
