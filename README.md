# Mikasa

基于 [Hermes Agent](https://github.com/NousResearch/hermes-agent) 运行、通过 [Claude Code Hub](https://github.com/ding113/claude-code-hub) 使用模型，拥有持续身份和协作记忆的程序员。目标是参与仓库审计、需求拆解、代码实现、审查和交付跟进。

## 分工

| 组件 | 负责什么 |
| --- | --- |
| Hermes | 原生 CLI、系统命令、模型调用与工具循环、SessionDB、MEMORY/USER、skills、Kanban、Cron、运行事件及 SQLite 快照 |
| CCH | 模型供应、协议对应的供应商路由、模型重写和分组 |
| Mikasa | 身份与工程 skills、配置和账号绑定、工程隔离与最终验收、必要的 API/平台/备份适配 |

优先复用 Hermes，不另建 Agent harness 或审批引擎。审查分工等协作约定由身份、skills、会话和原生记忆承载，实际权限由平台配置决定。Mikasa 默认不自动合并。

## 运行

需要 Python 3.12+、Git 和[固定 Hermes 环境](workers/hermes/README.md)；工程执行另需 Docker 及预装镜像。按[配置说明](config/README.md)建立 `config/local/mikasa.json`，配置模型来源及授权仓库。

```sh
python3.12 -m mikasa --config config/local/mikasa.json doctor
python3.12 -m mikasa --config config/local/mikasa.json chat
```

`chat` 直接进入 Hermes，使用 `/model 完整模型ID`、`/new`、`/resume` 等原生命令。GPT/Claude 需配置相应 CCH provider 和协议；聊天目前开放记忆与 skills，仓库工程任务仍走独立入口。API 与任务 runner 分别启动：

```sh
python3.12 -m mikasa --config config/local/mikasa.json serve
python3.12 -m mikasa --config config/local/mikasa.json run
```

默认示例未配置模型、仓库或外部发布，`doctor` 只检查本地条件。聊天差异、工程操作及完整备份/恢复见[运行手册](docs/runbooks/OPERATIONS.md)和[聊天手册](docs/runbooks/CHAT.md)。

## 当前进度

原生交互、工程续话与共享记忆、工具内修复、Kanban、Cron、运行事件和完整受管状态备份已接入。当前仍保留 HTTP 兼容、单任务 runner、结构化交付及工程快照验收。

历史真实 CCH 联调已验证合成工程任务和 GPT/Claude 会话切换；`default` 分组仍缺网关侧确认。GitHub 适配已实现但真实权限未验收，飞书与目标 VM 尚未接通。后续顺序为 **GitHub/飞书 → VM → 聊天工程任务与 FluxCore 联合验收**，详见[推进计划](MIKASA_FUNCTION_PLAN.md)与[验证边界](docs/VALIDATION.md)。

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
