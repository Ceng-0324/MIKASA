# Mikasa 功能规划（MVP）

更新日期：2026-09-20。本文区分已确认方向、本地实现和外部验收。人格与工程规则 1.0 已形成，Mikasa 运行时 0.1 已实现下述核心工作流，已通过隔离测试和 Hermes/CCH 合成任务真实联调；账号权限和 VM 运行尚未验收。证据见 [验证记录](docs/VALIDATION.md)。

## 已确认的目标

Mikasa 是与人类成员共同开发的仿生程序员，同时负责工程监督和交付推进。MVP 需要实现仓库审计，以及按需求拆解、派发或解决任务，并跟进成员任务和交付证据。

- 名字是 Mikasa，人格参考《进击的巨人》的三笠并进行本地适配。
- 主人为 GitHub 个人账号 `Ceng-0324`，Mikasa 称其为 `Shawn` 或 `Ceng`；当前 `origin` 为 `git@github.com:Ceng-0324/MIKASA.git`，飞书对应人为曾俊轩。
- 成员可以询问进度、讨论 Issue、提出需求并参与协作。
- 在已授权范围内，允许写代码、commit、创建 Issue 和 PR；Mikasa 不自动合并。
- 人类 PR 必须由 Mikasa 审查批准并留下结论；Mikasa 自己的 PR 必须由 `Ceng-0324` 批准。
- 技术方向为 [Hermes Agent](https://github.com/NousResearch/hermes-agent)、本地 CCH 相关模型配置及部分工程 skills，部署目标为 VM。
- 代码托管在 GitHub；飞书的具体接入后续讨论。
- 试点仓库为 [Ceng-0324/FluxCore](https://github.com/Ceng-0324/FluxCore)，由负责人于 2026-09-20 明确指定，随后明确其仅用于测试 Mikasa 是否正常运行。先完成 Mikasa 本体开发，再使用 FluxCore 联调验收；不先开发 FluxCore 或将其业务任务作为本体开发前置。

## 已形成的本地规则

| 内容 | 当前产物 |
| --- | --- |
| 身份、关系、交流风格与连续性 | [identity.md](identity.md) |
| 事实边界、授权、工程质量与审批责任 | [engineering-contract.md](engineering-contract.md) |
| 调查、任务拆解、实现、审查与验证交付 | [engineering-workflow.md](engineering-workflow.md) |
| 目录入口与维护说明 | [AGENTS.md](AGENTS.md)、[CLAUDE.md](CLAUDE.md)、[README.md](README.md) |
| 官方依据和本地适配来源 | [docs/ADAPTATION_SOURCES.md](docs/ADAPTATION_SOURCES.md) |

规则文件不等同于服务部署；运行实现和验证边界如下。

## 本体开发与当前实现

| 范围 | 本地产物与行为 |
| --- | --- |
| 任务事实源 | SQLite 保存任务、依赖、负责人、状态、事件、产出归属及发布回执；幂等提交、单 runner 锁、取消、暂停与中断恢复 |
| 聊天与模型切换 | CLI、网页和鉴权 HTTP 聊天；自然语言选择当前会话模型，CCH 负责上游路由，候选模型真实验证成功后持久化；切换保留上下文，不影响工程任务 |
| 任务操作 | CLI、鉴权 HTTP API、成员查询与需求提交、负责人分配、拆解结果转实施任务、交付证据跟进 |
| 仓库审计 | GitHub Issue、PR 和 CI 读取与风险记录；可配置周期审计；不自动重复创建 Issue |
| 模型执行 | 固定版本 Hermes SDK 的 JSON 桥接、canonical 与按任务路由的 skill 注入、指纹证据、Responses/Chat 协议适配、按任务授予仓库工具与同会话修复循环、宿主调用证据、专用 home、模型环境变量白名单 |
| 代码实现 | 独立 clone、受限文件变更、配置化验证、默认最多 3 轮修复、本地 commit；生产检查采用无网络容器 |
| PR 协作 | 当前 head 与目标基线核对、归属记录、自审限制、正式 Review、Issue 与草稿 PR 发布；不自动合并 |
| 运行支持 | 健康检查、GitHub 签名 webhook 与重放去重、SQLite 备份、systemd 模板、CI 与隔离集成测试 |

实现设计见 [运行时决定](docs/decisions/0001-runtime.md)，用法见 [操作手册](docs/runbooks/OPERATIONS.md)。源码中的实现不意味着相关外部账号、模型、服务已经接通。

## MVP 需要实现的行为

| 能力 | 预期行为 |
| --- | --- |
| 仓库审计 | 根据当前 Issue、PR、代码与 CI 识别交付风险，提供依据并避免重复记录同一问题 |
| 需求拆解 | 阅读项目目标与实现，明确验收、影响面和依赖，拆成可执行任务 |
| 派发或解决任务 | 在确认的职责和授权内交给成员或由 Mikasa 承担，保留任务所有权和交接记录 |
| PR 审查 | 依据项目核心思想、工程边界和当前代码证据，给出批准、请求修改或审查未完成的说明 |
| 进度与交付跟进 | 说明负责人、当前阶段、阻塞、下一步及完成证据，不能只采信口头完成报告 |

审批语义以工程契约为准：受 Mikasa 委派执行者实现的 PR 也属于她的产出，不通过换账号绕过自审限制。批准后的合并由有权限的人手动执行。普通 comment 不等于强制门禁，平台实现仍需验证。

## 后续待定

下列外部配置与后续可选接入不以候选方案冒充已完成验收：

- **运行验收**：本体开发和隔离测试完成后，再使用 `Ceng-0324/FluxCore` 验证真实账号、模型、仓库操作和独立审批；届时确定无破坏性的验收任务。
- **工程 skills**：已从固定版本 mattpocock/skills 适配拆解、实现/TDD 和审查方法，并加入人格路由 skill；来源、MIT 许可和差异见 [skills/SOURCES.md](skills/SOURCES.md)。真实调用已验证注入与代表性行为，不等同于安装并执行完整上游工具工作流。
- **模型执行**：Hermes 0.21.3 与 CCH Responses 已完成真实联调，可显式只读选用本地 Codex provider 配置，认证仅在内存传递。请求模型名与服务端返回标识存在差异，见 [联调记录](docs/HERMES_CCH_VALIDATION.md)。Codex/Claude 执行器仍为可选项。
- **GitHub 身份与审批门禁**：Mikasa 的 GitHub 账号已创建为 [`Mikasa-0910`](https://github.com/Mikasa-0910)；其仓库权限、token 管理、是否需要 GitHub App、正式 Review、仓库保护或受控检查的组合待定。
- **事实源与记忆**：当前采用 SQLite 任务与事件记录实现跨进程连续性；未接入 Hermes Kanban 或其他外部看板。人格变化、权限变化及非任务长期记忆仍遵守 canonical 边界。
- **成员协作**：实现了负责人派发和成员查询；成员名单与真实 token 绑定需配置。周期审计默认关闭，消息提醒与升级节奏仍待决定。
- **VM 运行**：已提供 Linux systemd、隔离验证和操作手册；目标 VM、模型服务、预装检查镜像、TLS 和平台权限尚未部署验收。
- **飞书接入**：负责人真实账号绑定、机器人形式、消息权限与事件处理后续讨论。

此前草案不自动构成已确认决定。当前任务授权先开发完整 Mikasa 本体，具体可逆工程选择记录在架构决定中；未改变身份、负责人、独立审批和不自动合并的既定规则。
