# 验证边界

固定 Hermes 0.21.3，revision `f9524d3f119c672e4a4444f56d582e7475716ba3`。本轮在 macOS arm64/Python 3.12.13 与 OrbStack Ubuntu 26.04 arm64/Python 3.12.14 验证，不修改上游源码。

## 当前迁移结果

工程入口直接启动完整 Hermes CLI。旧 worker JSON、快照容器、固定工具/skills 白名单、宿主预算、串行 runner、最终检查/提交与发布业务引擎已删除。身份、工程规则、方法 skills、CCH 路由和账号长期记忆保留；工程会话、工具、插件、MCP、Kanban/Cron 由原生配置管理。

两端 94 项 unittest 通过。退休功能对应旧测试已删除，当前测试覆盖聊天、路由、鉴权、配置、原生状态、备份与工程行为；测试数量变化不表示覆盖能力退化。固定 SDK 验证：

- 插件加载前后完整工程工具集合一致，用户工具、预算、backend、插件和工程 .env 配置在刷新后保留。
- 实际原生终端、文件工具操作 Git、二进制和 .github；后台进程启动、查询、终止。
- 外部仓库规则文件按 Hermes 原生审批后可写；没有 Mikasa 文件禁改门槛。
- 同一 Kanban 调度周期认领两个任务；Cron 创建、保存并执行本地脚本。调度测试使用生成的子进程回执，不是两个真实模型任务的无人值守验收。
- v3 备份、v2 兼容、WAL、Git 字节、内部记忆链接、工程会话/看板工作目录重定位。
- 原生 Gateway/SSE 探针通过幂等、取消、停止、备份和新目录恢复后的历史、记忆与回执。

## 真实模型与平台

| 范围 | 当前证据 | 未覆盖边界 |
| --- | --- | --- |
| 原生工程 + CCH | 本机 GPT、VM GPT Responses 与 Claude Messages 均完成 17 项合成验收：观察失败、修复、测试、二进制、.github、原生后台进程、委派、memory、skill_view、本地 Git 提交、退出后恢复原生会话并读回记忆；主会话身份/人格/索引加载通过 | 只证明这些模型和任务样本；未跑所有外部工具、浏览器、MCP 或语言生态 |
| GitHub | VM 专用账号以 gh 原生认证保存身份，Hermes 实际 terminal → gh → GitHub /user 确认 Mikasa-0910；Git credential helper 已设置 | 本轮没有远端仓库写入、推送、PR、Review 或外部消息；后续按指定任务验收 |
| 飞书 / 微信 | 正式服务更新后两个渠道均 connected；此前主人确认 /help、普通消息与 GPT/Claude 切换正常 | 本轮未要求重复手机验收；微信 iLink 普通群聊仍不可用 |
| 记忆与身份 | 工程 profile 链接同账号 memories；本轮真实工程保存及续话读回通过。正式两份 MEMORY/USER 文件与升级前一致，21 个会话、103 条消息保留 | 同一实例的记忆快照不承诺外部改动即时刷新；同 profile 共享记忆不等于每个发言人独立隔离 |
| VM | mylinux 专用 mikasa 用户，Git/gh、Node 22/npm、ripgrep 和固定 Hermes；原生工程入口已部署，消息 Gateway 仍统一运行 | OrbStack 依赖 Mac；未部署独立云主机或公网 API，未做 VM 重启/故障注入演练 |
| CCH default 分组 | 模型连接与双协议路由通过 | 仍缺网关管理端同次 providerGroup/供应商日志，响应模型名不能证明分组或底层身份 |

真实工程使用临时 profile 和合成仓库，未访问 FluxCore、未触碰正式记忆或向平台发送消息。完整工程执行不再受 Mikasa 的 worker.timeout 限制，模型服务延迟及 Hermes 原生预算仍有效。

## 部署与恢复

正式代码在 /opt/mikasa，状态在 /var/lib/mikasa；消息 Gateway 与工程 profile 独立运行。工程默认 workspace 持久，memories 链接正式账号。无工程 platform_toolsets 或 agent 预算覆写，CCH 来源与原生偏好继续保存。

2026-09-22 升级前确认无活跃 Agent 后停服，保存 536 项状态到 `/var/backups/mikasa/native-engineering-20260922`；旧代码和配置保存在 `/var/backups/mikasa-service/native-engineering-20260922`。新代码成功将该真实 v2 备份恢复到临时新目录，核验会话、消息与记忆后删除演练副本。正式历史和微信绑定未清空，重启后飞书、微信均连接。旧任务数据库和工作区继续作为档案，未自动重跑。

GitHub 登录使用 VM 独立用户的原生 gh 认证，文件 0600，不复制个人 Codex/Claude/GitHub 认证文件。gh 凭据位于用户 .config/gh，属于普通受管状态备份之外的独立认证；轮换或恢复使用原生登录流程。

## 保留的原生边界

- 聊天尚未接入仓库执行，仍使用 memory、skills 与当前 profile 历史检索；聊天工程与 FluxCore 最后联合验收。
- 工程工具的确认、凭据清理、规则文件保护、工具依赖、操作系统和平台权限与相同配置的 Hermes 一致。例如默认文件工具修改仓库 AGENTS.md 需交互批准，--yolo 不取消这项原生保护；GH_TOKEN 不直接继承给 terminal，VM 已通过 gh 自身认证解决。
- 不同聊天会话并发，同会话 FIFO；有限准入上限满额时仍按原生行为拒绝，不是全局队列。群上下文共享，区分发言人与不转述私人内容依靠身份约定。
- 固定版本原生 CLI 的自定义 CCH provider 下 /new 不可靠地重置默认模型，同进程 --global 不刷新启动快照；显式 /model ID 可切换，保存值重启生效。
- 外部 cwd、原生 Git worktree 的外部链接、自定义工具存储、Cron 脚本内绝对路径需独立备份和核对。GitHub token scope 与仓库权限没有被本地工具恢复自动扩大。
- 未运行 Python 3.13 远端 CI、Hermes 全部上游测试或所有原生工具的外部服务验收；不能把“完整复用原生入口”写成“每个外部能力均已验收”。

旧轮次和已退休快照执行器的验证保留在 Git 历史，不作为当前入口的完成证据。当前推进顺序见 [计划](../MIKASA_FUNCTION_PLAN.md)，原生使用方式见 [运维](runbooks/OPERATIONS.md)。
