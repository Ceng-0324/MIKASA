# Mikasa 功能规划（MVP）

更新日期：2026-09-20。本文区分已确认方向、本地实现和外部验收。人格与工程规则 1.1 已形成，Mikasa 运行时 0.1 已实现下述核心工作流，已通过隔离测试和 Hermes/CCH 合成任务真实联调；账号权限和 VM 运行尚未验收。证据见 [验证记录](docs/VALIDATION.md)。

## 已确认的目标

Mikasa 是基于原生 Hermes、通过 CCH 使用模型、拥有持续身份和协作记忆的仿生程序员。优先复用 Hermes 的会话、命令、工具、记忆、skills、任务调度与渠道；自研只补真实集成缺口。协作规范通过身份、工程 skills 和持久记忆承载，不另建强制审批业务引擎。迁移清单与阶段验收见 [收窄决定](docs/decisions/0006-hermes-native-mikasa.md)。MVP 需要实现仓库审计，以及按需求拆解、派发或解决任务，并跟进成员任务和交付证据。

- 名字是 Mikasa，人格参考《进击的巨人》的三笠并进行本地适配。
- 主人为 GitHub 个人账号 `Ceng-0324`，Mikasa 称其为 `Shawn` 或 `Ceng`；当前 `origin` 为 `git@github.com:Ceng-0324/MIKASA.git`，飞书对应人为曾俊轩。
- 成员可以询问进度、讨论 Issue、提出需求并参与协作。
- 在已授权范围内，允许写代码、commit、创建 Issue 和 PR；Mikasa 不自动合并。
- 默认由 Mikasa 审查人类 PR，负责人审查 Mikasa 产出；通过已确认交互更新协作约定，不把分工写成专属程序门禁。
- 技术方向为 [Hermes Agent](https://github.com/NousResearch/hermes-agent)、本地 CCH 相关模型配置及部分工程 skills，部署目标为 VM。
- 代码托管在 GitHub；飞书作为外部接入，与 GitHub 权限接入安排在 VM 部署前，具体账号和应用配置仍需落实。
- 试点仓库为 [Ceng-0324/FluxCore](https://github.com/Ceng-0324/FluxCore)，由负责人于 2026-09-20 明确指定，随后明确其仅用于测试 Mikasa 是否正常运行。先完成 Mikasa 本体开发，再使用 FluxCore 联调验收；不先开发 FluxCore 或将其业务任务作为本体开发前置。

## 已确认的推进顺序

负责人已调整优先级：先搭好底层与接入，再部署 VM；聊天工程任务与试点仓库一起放在最后。

1. **Hermes 底层 agent**：完善主动检索、分段上下文、实现/检查/修复循环、运行证据、取消与失败恢复；扩大合成任务验收，明确资源上限。直接采用官方 Hermes harness 负责推理、上下文管理和工具调度，现有宿主仍管理任务、快照及副作用校验，按收窄决定逐步迁往原生能力；身份、工程规范与记忆保持加载。后续扩展以协作开发、质量监督和交付推进为判断依据；优先官方扩展点，不因能力可用而自动扩大范围。
   终端已直接调用 Hermes 官方 CLI，完整命令分派、会话恢复和默认偏好均由原生实现；HTTP/单条消息暂留旧 API 命令适配并通过 Gateway 运行。同账号两个入口共用 SessionDB、MEMORY/USER，进程互斥，详见 [原生 CLI](docs/decisions/0007-native-cli.md)。工程任务使用原生 Docker 文件/终端、SOUL、skills 和持续 SessionDB，会话按任务隔离，长期记忆与提交账号共用；旧任务记忆留档，见 [工程续话与记忆](docs/decisions/0008-engineering-state.md)。宿主外层修复循环已删除，Mikasa 暂保留快照和最终独立验收，审批分工交给规则与记忆，见 [原生修复](docs/decisions/0009-native-repair-loop.md)。下一步迁移 Kanban 任务事实源和调度，再接 Cron、事件和备份。聊天工程任务仍在最后接入，见 [工程工具归属](docs/decisions/0005-native-engineering-tools.md)。
2. **CCH 模型路由**：继续采用 CCH 提供模型路由，收口模型配置、故障行为和路由验证。`default` 是网关 Key 的 provider 分组，不是模型名；当前分组尚未取得网关侧证据，不能标记为已切换。不新增重复路由网关。

   本地已补齐 Codex/Claude/环境来源的统一校验、`doctor --probe-model --model MODEL_ID` 连接诊断与 Hermes 官方错误钩子的固定故障反馈；`/model` 作为宿主系统命令按受信任路由同步选择模型、协议和凭据，GPT Responses ↔ Claude Messages 已完成真实会话切换与上下文保留验收。连接成功、响应标识与分组证据分开报告。剩余为网关侧 `default` 分组确认，具体见 [CCH 诊断](docs/runbooks/CCH.md)。后续可继续外部身份/权限接入的独立准备。
3. **外部权限接入**：接通 GitHub 的服务身份、仓库权限、事件与正式 Review，以及飞书应用身份、真实用户绑定与事件权限。先验证认证和接收链路；聊天转工程任务保留到最后。
4. **VM 部署**：在底层和外部接入具备运行条件后，落实专用用户、配置与凭据注入、固定 Hermes 依赖、隔离检查镜像、systemd、网络入口及恢复验证。
5. **聊天工程任务与 FluxCore 试点**：在部署环境中一起打通自然语言任务入口、进度交互、真实仓库执行与协作流程验收。

接入所需外部输入包括 Mikasa GitHub 身份的授权方式及范围、飞书应用/租户/用户标识和凭据来源、VM 地址/操作系统/登录方式与域名。这些输入未配置前可完成实现和本地验证，但不声称已经接通或部署。每轮已验证改动自动本地提交，不自动推送。

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
| 任务事实源 | SQLite 保存任务、依赖、负责人、状态、事件及发布回执；幂等提交、单 runner 锁、取消、暂停与中断恢复；执行阶段和工具证据实时入库，失败与超时后保留，旧执行令牌不能污染新任务运行 |
| 聊天与模型切换 | 终端使用 Hermes CLI 原生 /model、/new、/resume 和全局偏好；Mikasa 仅准备 profile 与 CCH 配置。HTTP/--message 暂保留中文切换和推理验证后保存的旧契约；工程默认配置独立 |
| 任务操作 | CLI、鉴权 HTTP API、成员查询与需求提交、负责人分配、拆解结果转实施任务、交付证据跟进 |
| 仓库审计 | GitHub Issue、PR 和 CI 读取与风险记录；可配置周期审计；不自动重复创建 Issue |
| 模型执行 | 固定版本 Hermes SDK 的 JSON 桥接、canonical 与按任务路由的 skill 注入、指纹证据、Responses/Chat/Messages 协议适配、按任务授予仓库工具与同会话修复循环、宿主调用证据、专用 home、模型环境变量白名单 |
| 代码实现 | 独立 clone、受限文件变更、配置化验证、默认最多 3 轮修复、本地 commit；生产检查采用无网络容器 |
| PR 协作 | 当前 head、目标基线与 CI 证据核对、Agent 审查结论、正式 Review、Issue 与草稿 PR 发布；不自动合并 |
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

默认审查分工见工程契约，可以通过负责人确认的交互更新。普通 comment 不等于正式 Review；平台已有权限照常生效，Mikasa 默认不自动合并，不维护自己的审批门禁。

## 后续待定

下列外部配置与后续可选接入不以候选方案冒充已完成验收：

- **运行验收**：Hermes/CCH、外部接入与 VM 部署完成后，与聊天工程任务一起使用 `Ceng-0324/FluxCore` 验证真实账号、模型、仓库操作和独立审批；届时确定无破坏性的验收任务。
- **工程 skills**：已从固定版本 mattpocock/skills 适配拆解、实现/TDD 和审查方法，并加入人格路由 skill；来源、MIT 许可和差异见 [skills/SOURCES.md](skills/SOURCES.md)。真实调用已验证注入与代表性行为，不等同于安装并执行完整上游工具工作流。
- **模型执行**：Hermes 0.21.3 与 CCH Responses 已完成真实联调，可显式只读选用本地 Codex provider 配置，认证仅在内存传递。请求模型名与服务端返回标识存在差异，见 [联调记录](docs/HERMES_CCH_VALIDATION.md)。Codex/Claude 执行器仍为可选项。
- **GitHub 身份与协作**：Mikasa 的 GitHub 账号已创建为 [`Mikasa-0910`](https://github.com/Mikasa-0910)；其仓库权限、token 管理、是否需要 GitHub App、正式 Review 能力待验收；不要求专属审批 status 或强制仓库保护。
- **事实源与记忆**：任务使用 SQLite；旧审批归属表仅为档案，不再读写；聊天已迁移原生 Hermes SessionDB、MEMORY/USER，按账号隔离，旧对话一次性导入。经确认的长期协作安排可更新记忆；未接入 Hermes Kanban 或其他外部看板。
- **成员协作**：实现了负责人派发和成员查询；成员名单与真实 token 绑定需配置。周期审计默认关闭，消息提醒与升级节奏仍待决定。
- **VM 运行**：已提供 Linux systemd、隔离验证和操作手册；目标 VM、模型服务、预装检查镜像、TLS 和平台权限尚未部署验收。
- **飞书接入**：负责人真实账号绑定、机器人形式、消息权限与事件处理安排在 VM 部署前；聊天工程任务转换安排在最后验收。

此前草案不自动构成已确认决定。当前任务授权先开发完整 Mikasa 本体，具体可逆工程选择记录在架构决定中；最新决定改变了协作规范的实现方式；稳定身份、实际平台权限及默认不自动合并继续有效。
