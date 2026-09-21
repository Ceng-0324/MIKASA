# Mikasa

基于 [Hermes Agent](https://github.com/NousResearch/hermes-agent) 运行、通过 [Claude Code Hub](https://github.com/ding113/claude-code-hub) 使用模型，拥有持续身份和协作记忆的程序员。目标是参与仓库审计、需求拆解、代码实现、审查和交付跟进。

## 分工

| 组件 | 负责什么 |
| --- | --- |
| Hermes | 原生 CLI 与多平台 Gateway、系统命令、模型调用与工具循环、SessionDB、MEMORY/USER、skills、Kanban、Cron、运行事件及 SQLite 快照 |
| CCH | 模型供应、协议对应的供应商路由、模型重写和分组 |
| Mikasa | 身份与工程 skills、配置和账号绑定、工程隔离与最终验收、必要的 API/平台/备份适配 |

优先复用 Hermes，不另建 Agent harness 或审批引擎。审查分工等协作约定由身份、skills、会话和原生记忆承载，实际权限由平台配置决定。Mikasa 默认不自动合并。

## 运行

需要 Python 3.12+、Git 和[固定 Hermes 环境](workers/hermes/README.md)。按[配置说明](config/README.md)准备本机 JSON 与模型来源；以下沿用接入手册的 `config/local/hermes-cch.json`，其他机器替换为自己的路径。纯聊天无需配置仓库；工程任务另需授权仓库、Docker 及预装镜像。

```sh
python3.12 -m mikasa --config config/local/hermes-cch.json doctor
```

按用途选择入口；命令均追加在 `python3.12 -m mikasa --config config/local/hermes-cch.json` 后：

| 用途 | 命令 | 说明 |
| --- | --- | --- |
| 飞书与微信聊天 | `gateway --platform feishu --platform weixin` | 一个 Hermes Gateway；先配置飞书应用并完成微信扫码，可只选一个平台 |
| 终端聊天 | `chat` | 直接进入 Hermes CLI |
| HTTP 接口 | `serve` | 鉴权聊天与任务 API，聊天按账号启动原生 Gateway |
| 工程任务执行 | `run` | 消费任务队列；提交任务见[操作手册](docs/runbooks/OPERATIONS.md) |

**同一账号 profile 的终端、HTTP 聊天和消息 Gateway 互斥**，切换入口前需停止占用它的进程。飞书和微信应在同一条 Gateway 命令中启动。

原生聊天使用 `/model 完整模型ID`、`/new`、`/help` 等系统命令；GPT/Claude 需配置相应 CCH provider 和协议。聊天模型工具目前为记忆与只读 skills，仓库工程任务仍走独立入口；HTTP 命令兼容范围见[聊天手册](docs/runbooks/CHAT.md)。

默认示例未配置模型、仓库或外部发布，`doctor` 只检查本地条件。平台凭据与扫码见[接入手册](docs/runbooks/CONNECTIONS.md)，模型配置见 [CCH 手册](docs/runbooks/CCH.md)。

## 当前进度

原生交互、工程续话与共享记忆、工具内修复、Kanban、Cron、运行事件和完整受管状态备份已接入。当前仍保留 HTTP 兼容、单任务 runner、结构化交付及工程快照验收。

飞书、微信共用 Hermes Gateway，负责人私聊和 `/help` 已真实接通；微信用于主人私聊，团队群协作用飞书。飞书已开放群聊准入，群聊实际收发仍待验收；同一 profile 共享长期记忆与系统命令能力。GitHub 已确认 `Mikasa-0910` 账号身份，仓库操作待验收。

当前推进 **OrbStack VM 部署与消息验收 → 工程部署条件 → 聊天工程任务与 FluxCore 联合验收**。详细状态与限制只维护在[验证边界](docs/VALIDATION.md)，下一步见[推进计划](MIKASA_FUNCTION_PLAN.md)，平台配置见[接入手册](docs/runbooks/CONNECTIONS.md)。

## 开发

```sh
python3.12 -m unittest discover -v
python3.12 scripts/check_docs.py
python3.12 -m mikasa doctor
git diff --check
```

从 [AGENTS.md](AGENTS.md) 读取身份、工程契约与工作流。每轮验证后自动创建本地提交，**不自动推送**，见 [CONTRIBUTING.md](CONTRIBUTING.md)。本地配置、认证、会话和日志不进入 Git。

| 入口 | 内容 |
| --- | --- |
| [当前架构](docs/architecture/README.md) / [API](docs/architecture/API.md) | 所有权、状态与兼容边界 |
| [CCH](docs/runbooks/CCH.md) / [VM](deploy/vm/README.md) | 模型路由与部署准备 |
| [skills](skills/README.md) / [验收脚本](scripts/README.md) | 工程方法、来源许可与可复现验证 |
| [身份来源](docs/ADAPTATION_SOURCES.md) | 官方角色依据与本地适配 |

运行代码位于 `mikasa/`，Hermes 集成位于 `workers/hermes/`。`runtime/` 保存本机依赖和私密状态。历史决策与旧验收报告保留在 Git，当前文档只描述仍有效的行为。
