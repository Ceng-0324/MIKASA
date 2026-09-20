# 0003：Hermes 命令复用与会话归属

状态：会话所有权与关闭原生记忆的决定已由 [0004](0004-native-hermes-runtime.md) 取代；命令解析复用仍有效。以下保留原决策背景，不代表当前运行方式。

日期：2026-09-20。依据：负责人要求采用 Hermes harness、复用系统命令，并按整体架构交付。目标仍是协作开发、质量监督和交付推进。

## 官方实现与选择

核对固定 Hermes `f9524d3f119c672e4a4444f56d582e7475716ba3`，不修改上游源码。

| 官方接口 | 当前采用方式 |
| --- | --- |
| [commands.resolve_command](https://github.com/NousResearch/hermes-agent/blob/f9524d3f119c672e4a4444f56d582e7475716ba3/hermes_cli/commands.py) | bridge 直接调用共享注册表识别命令和别名，包括 `/reset` → `/new`、`/v` → `/version` |
| [model_switch.parse_model_switch_args](https://github.com/NousResearch/hermes-agent/blob/f9524d3f119c672e4a4444f56d582e7475716ba3/hermes_cli/model_switch.py) | 直接调用官方参数解析和冲突校验；允许无参数、完整 ID、`--session`；Mikasa 限定持久化范围与 CCH 凭据来源 |
| [slash_exec.execute_command](https://github.com/NousResearch/hermes-agent/blob/f9524d3f119c672e4a4444f56d582e7475716ba3/hermes_cli/slash_exec.py) | `/version` 调用共享执行器；该版本没有 `/model`、`/new`、`/init` 的无状态共享执行器，不能声称全量处理器已复用 |
| [Gateway 会话命令](https://github.com/NousResearch/hermes-agent/blob/f9524d3f119c672e4a4444f56d582e7475716ba3/gateway/slash_commands_session.py) | 完整 `/new` 依赖 Gateway 的缓存 agent、平台会话键、session store 和 hooks；不伪造 GatewayRunner 去调用。Mikasa 按官方新会话语义适配自己的事实源 |
| [init_command](https://github.com/NousResearch/hermes-agent/blob/f9524d3f119c672e4a4444f56d582e7475716ba3/hermes_cli/init_command.py) | 可复用仓库初始化 prompt builder，但它要求文件写入；随聊天工程任务与试点最后接入，目前只明确返回未执行 |

自然中文指令及已有 `/models` 菜单入口仅翻译到 `/model`，不保留第二套斜杠参数解析器。命令经现有 worker 独立进程协议 `operation=command` 调用固定 Hermes 环境；此路径不解析模型来源、不注入模型或平台凭据、不构造 AIAgent，也不发模型请求。组件失效时关闭命令路径并报错，不把命令转交模型猜测执行。`/help` 只列出实际开放的命令。

官方完整 `switch_model` 还会发现目录、读取全局 provider/认证和解析别名；当前 CCH 目录访问受 WAF 限制，且接入范围只允许显式来源。故只复用其参数解析，不直接启动完整 discovery 管道或写个人 Hermes 配置。`--global`、`--once`、`--provider`、`--reasoning`、`--refresh` 明确拒绝，不静默忽略。现有 CCH 适配继续同步选择完整模型 ID、端点、Key 来源及原生协议，真实验证成功才更新会话。

## 单一会话事实源

Mikasa SQLite 保存账号归属、聊天 ID、所选模型、对话及幂等回执。Hermes 接收原生 `conversation_history`，负责本次上下文管理、推理与工具循环；历史不再包在用户 JSON 内重复传入。只传普通聊天的 user/assistant 消息，不把命令控制回执混入模型历史。历史仍取最近 40 轮并受上下文字节预算限制，截断明确告知模型。

bridge 显式传 `session_db=None`，关闭原生记忆、trajectory 和自动上下文加载；没有另建 Hermes 业务会话库。SDK 仍可能生成运行诊断文件，这不构成第二套用户会话事实源。每轮新建 agent 适配当前模型与协议；不为了调用在位切换函数而先创建旧模型 agent。

`/new` 与 `/reset` 在同一事务创建新 ID、保留所选模型、记录事件和旧会话命令回执；新会话 revision=0、无历史。旧记录保留且仍按原账号鉴权。原请求幂等键重放只返回同一个新 ID；暂停或事务失败不创建半个会话。HTTP 回复的 `chat_id` 是下一条消息应使用的 ID，CLI 自动跟随，HTTP 客户端须跟随返回的 ID。手动恢复旧会话仍可继续它，因此新旧会话均保持独立有效。

## 分工和后续依赖

- Hermes：官方 harness、共享命令组件、原生历史接口、模型 transport、工具调度。
- CCH：供应商/分组选择、模型重写和请求路由；`default` 分组需要网关 Key 的权限证据，不能由 `/model default` 代替。
- Mikasa：身份与工程规则、授权、会话/任务事实、CCH 来源适配、工作区副作用限制、独立审批与交付证据。

完成本轮并不等于所有 Hermes CLI/Gateway 命令已经开放，也不等于生产部署。接下来依次推进 GitHub/飞书身份权限、VM、聊天工程任务与 FluxCore；后者包含 `/init` 的仓库选择及规则写入边界。现有聊天命令验证见 [验证记录](../VALIDATION.md)。

若以后采用 Hermes Gateway 作为统一接入层，必须整体迁移会话所有权、身份映射、取消与幂等，不在两套 session store 间同步“当前会话”。Hermes 升级则先运行独立命令探针和跨协议聊天验收；若命令接口不兼容，保持失败关闭并修复适配，不回退到复制官方解析器。
