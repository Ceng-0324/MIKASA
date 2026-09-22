# 验证边界

固定 Hermes 0.21.3，revision `f9524d3f119c672e4a4444f56d582e7475716ba3`。当前运行于独立的 OrbStack `mikasa` 隔离机器，Ubuntu 24.04 arm64、Python 3.12.14、SQLite 3.53.1；本机 macOS 使用 Python 3.12.13。不修改 Hermes 上游源码。

## 当前迁移结果

工程入口直接启动完整 Hermes CLI。旧 worker JSON、快照容器、固定工具/skills 白名单、宿主预算、串行 runner、最终检查/提交与发布业务引擎已删除。身份、工程规则、方法 skills、CCH 路由和账号长期记忆保留；工程会话、工具、插件、MCP、Kanban/Cron 由原生配置管理。

两端 94 项 unittest 通过，新机最终环境耗时 35.737 秒，本机 34.289 秒；新机 pip check 通过。退休功能对应旧测试已删除，当前测试覆盖聊天、路由、鉴权、配置、原生状态、备份与工程行为。固定 SDK 验证：

- 插件加载前后完整工程工具集合一致，用户工具、预算、backend、插件和工程 .env 配置在刷新后保留。
- 实际原生终端、文件工具操作 Git、二进制和 .github；后台进程启动、查询、终止。
- 外部仓库规则文件按 Hermes 原生审批后可写；没有 Mikasa 文件禁改门槛。
- 同一 Kanban 调度周期认领两个任务；Cron 创建、保存并执行本地脚本。调度测试使用生成的子进程回执，不是两个真实模型任务的无人值守验收。
- v3 备份、v2 兼容、WAL、Git 字节、内部记忆链接、工程会话/看板工作目录重定位。
- 原生 Gateway/SSE 探针通过幂等、取消、停止、备份和新目录恢复后的历史、记忆与回执。

## 真实模型与平台

| 范围 | 当前证据 | 未覆盖边界 |
| --- | --- | --- |
| 原生工程 + CCH | 原迁移阶段本机 GPT、旧机 GPT/Claude 均通过 17 项合成工程验收；本轮新机 GPT 再次通过全部 17 项，覆盖修复、测试、Git、后台进程、委派、skills、身份、记忆和续话。新机最终 Python 环境的 Claude 原生 Gateway 实际请求通过 | GPT 完整合成任务在新机初始 Python 3.12.3 下执行；切换 3.12.14 后以全量测试、原生管理员探针和 Claude 请求复验。未跑全部外部工具、浏览器、MCP 或语言生态 |
| GitHub | VM 专用账号以 gh 原生认证保存身份，Hermes 实际 terminal → gh → GitHub /user 确认 Mikasa-0910；Git credential helper 已设置 | 本轮没有远端仓库写入、推送、PR、Review 或外部消息；后续按指定任务验收 |
| 飞书 / 微信 | 正式服务更新后两个渠道均 connected；此前主人确认 /help、普通消息与 GPT/Claude 切换正常 | 本轮未要求重复手机验收；微信 iLink 普通群聊仍不可用 |
| 记忆与身份 | 工程 profile 链接同账号 memories；本轮真实工程保存及续话读回通过。正式两份 MEMORY/USER 文件与升级前一致，21 个会话、103 条消息保留 | 同一实例的记忆快照不承诺外部改动即时刷新；同 profile 共享记忆不等于每个发言人独立隔离 |
| 工作机权限 | 新机普通 mikasa 用户具有完整免密 sudo；Hermes 实际 terminal 验证取得 root、写入并清理 /etc 下测试文件、创建并执行临时 systemd 服务、gh 只读身份及本地 Docker 镜像构建/运行，5 项全通过 | GitHub 等外部平台权限独立；不代表已验收每种系统操作 |
| 机器与恢复 | mikasa 专用机启用宿主/机器网络隔离，无 Mac 挂载、宿主命令或 SSH Agent；root 访问 Mac 测试端口被拒，旧机对照可连。Gateway SIGKILL 后自动恢复，机器重启后 Gateway、Docker、sudo 和双平台连接恢复 | OrbStack 共享 Linux 内核并依赖 Mac；当前 Mac 登录自启关闭，未演练 Mac 重启或部署独立云主机 |
| Docker | 独立 Docker/Compose 已启用，普通用户经原生 terminal 成功构建并运行本地 scratch/BusyBox 镜像 | Docker Hub registry 当前 TLS/EOF 失败，公网镜像拉取未通过；没有通过开放宿主共享规避 |
| CCH default 分组 | 模型连接与双协议路由通过 | 仍缺网关管理端同次 providerGroup/供应商日志，响应模型名不能证明分组或底层身份 |

真实工程使用临时 profile 和合成仓库，未访问 FluxCore、未触碰正式记忆或向平台发送消息。完整工程执行不再受 Mikasa 的 worker.timeout 限制，模型服务延迟及 Hermes 原生预算仍有效。

## 部署与恢复

正式代码在 /opt/mikasa，状态在 /var/lib/mikasa；消息 Gateway 与工程 profile 独立运行。工程默认 workspace 持久，memories 链接正式账号。无工程 platform_toolsets 或 agent 预算覆写，CCH 来源与原生偏好继续保存。

2026-09-22 从 mylinux 停服备份 561 项状态，恢复到新机相同路径；21 个会话、103 条消息、MEMORY/USER 字节和单独传输的微信绑定均一致，工程记忆链接正确。旧 mylinux 服务已 disabled，旧机原始数据和 `/var/backups/mikasa/dedicated-machine-20260922` 恢复点保留；新机另存该快照。旧任务继续作为档案，未自动重跑。

新机配置 4 核、6 GiB 内存和 32 GiB 磁盘上限。Gateway/API 服务模板移除只读文件系统与禁止提权设置，普通用户可使用 sudo；Gateway 将正常 SIGTERM 对应的 143 视为成功。模拟主进程 SIGKILL 后 NRestarts 增加并恢复双平台连接；`orb restart mikasa` 后服务自动启动、sudo 及共享记忆配置保留。journal 限额 256 MiB、14 天。恢复点和日常命令见 [工作机手册](../deploy/vm/README.md)。

新机首次临时 Gateway 探针曾启动超时；保留 profile 的诊断复验通过，最终运行环境的全新临时探针也通过。未据此声称永不冷启动超时。Ubuntu 系统 Python 的旧 SQLite 会触发 Hermes 原生 DELETE journal 回退，正式 venv 已切换到上述已修复运行环境。

GitHub 登录使用 VM 独立用户的原生 gh 认证，文件 0600，不复制个人 Codex/Claude/GitHub 认证文件。gh 凭据位于用户 .config/gh，属于普通受管状态备份之外的独立认证；轮换或恢复使用原生登录流程。

## 保留的原生边界

- 聊天已开放原生工程工具和进度/结果反馈；本页早期迁移数据不代表消息平台工程交互或所有外部工具均已验收。FluxCore 真实仓库协作仍需指定任务。
- 专用机聊天和工程 profile 使用 Hermes 原生 approvals.mode=off，普通命令不逐次等待确认；默认规则文件保护及原生不可绕过的检查保留。例如 AGENTS.md 文件工具修改仍需交互批准。GH_TOKEN 不直接继承给 terminal，新机已通过 gh 自身认证解决。
- 不同聊天会话并发，同会话 FIFO；有限准入上限满额时仍按原生行为拒绝，不是全局队列。群上下文共享，区分发言人与不转述私人内容依靠身份约定。
- 固定版本原生 CLI 的自定义 CCH provider 下 /new 不可靠地重置默认模型，同进程 --global 不刷新启动快照；显式 /model ID 可切换，保存值重启生效。
- 外部 cwd、原生 Git worktree 的外部链接、自定义工具存储、Cron 脚本内绝对路径需独立备份和核对。GitHub token scope 与仓库权限没有被本地工具恢复自动扩大。
- 未运行 Python 3.13 远端 CI、Hermes 全部上游测试或所有原生工具的外部服务验收；不能把“完整复用原生入口”写成“每个外部能力均已验收”。

旧轮次和已退休快照执行器的验证保留在 Git 历史，不作为当前入口的完成证据。当前推进顺序见 [计划](../MIKASA_FUNCTION_PLAN.md)，原生使用方式见 [运维](runbooks/OPERATIONS.md)。
