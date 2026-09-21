# 验证边界

固定 Hermes 0.21.3，revision `f9524d3f119c672e4a4444f56d582e7475716ba3`。本机为 macOS arm64 / Python 3.12.13，未执行目标 Linux VM 或远端 Python 3.13 CI。

## 本轮验证

微信已完成真实扫码，本机完整绑定检查为 ready。排查“登录后无法使用”发现当时 Gateway 仅启用飞书；现已正常重启为单进程飞书 + 微信，两个适配器均报告 connected，飞书 WebSocket 已恢复。真实微信消息已进入 `source=weixin` 的 SessionDB，CCH Responses 请求返回 `gpt-6-astra`，对应请求证据中 identity、policy、persona_skill、skills_index 均为 true。启动后曾出现一次 iLink 连接失败，随后收到消息并完成模型回复，检查时没有发送失败记录。手机端收悉、系统命令、模型切换与跨会话记忆尚需单独确认，不以 connected 或模型输出代替完整消息验收。本轮只调整运行配置和接入文档，未修改运行代码。

补充投递证据：两条真实微信请求各有一条 assistant 回复，原生 `delivery_obligations` 中对应两条记录均为 delivered、无 last_error，运行状态已回到空闲。该证据确认原生发送流程成功，不代表用户已读。文档链接、diff 和本机配置 doctor 检查通过；未修改运行代码，未重复执行上一轮全量测试。

## 上轮飞书开放验证

飞书准入改为直接配置 Hermes 原生开放策略：所有用户、群聊和机器人可进入，不要求 @；负责人 ID 不再作为接入前提或白名单。身份注入区分 profile 所属账号和消息发送者，保留负责人 ID 的关系说明。微信扫码单聊、凭据隔离和聊天工具范围保持原有配置。

专项 26 项、全量 **194 项 unittest 通过（250.467 秒）**；文档、默认及本机配置 doctor、diff 检查通过。固定 Hermes/lark SDK 实际执行了用户/机器人 × 私聊/未 @ 群聊准入、Gateway 二次授权、启动开放确认、原生会话区分、自身消息过滤和机器人循环保护；身份注入与无凭据落盘也通过回归。未使用真实群消息代替测试夹具，未调用真实模型。

本机现有飞书 Gateway 已正常停止并通过统一 `gateway --platform feishu` 入口重启。新生成配置为 `default_group_policy=open`、`allow_bots=all`、`require_mention=false`；原生运行状态与进程 PID 对齐，飞书为 connected，日志确认 WebSocket 握手，更新的身份/规则插件已加载。清理了一个前一天遗留、同 profile 且空闲的孤立 Gateway，避免它继续覆盖当前状态；未删除会话或记忆。已知 macOS liveness socket 路径过长警告仍在，未影响长连接。**本次未验收真实群聊、其他成员或其他机器人的消息往返**；飞书可用范围和群消息权限仍需按接入手册核对。

## 上轮微信与统一 Gateway 验证

微信第一阶段增加 Hermes 原生扫码入口、本机凭据绑定与不联网诊断，并将飞书和微信接入同一个 Hermes 多平台 Gateway。专项 24 项、全量 192 项通过（260.461 秒），文档、doctor、编译和 diff 检查通过。覆盖缺少扫码用户标识时拒绝覆盖、0600 凭据、错误脱敏、临时登录 home 隔离、飞书 profile 保留、双平台单进程及 token 不落盘。真实 iLink 已成功返回登录二维码，尚未完成扫码或消息验收；统一 Gateway 的真实启动仍待微信绑定后进行。

## 上轮飞书与人格验证

飞书真实联调已完成：应用凭据探针通过后，Hermes 原生 WebSocket 日志记录已连接；负责人实际收到 `/help` 和普通自我介绍消息的回复。SQLite 生成了 `source=feishu` 的原生会话，模型回执为 `gpt-6-astra`；运行证据显示身份、工程规则、persona skill 与 skills 索引均加载。新版人格规则再用两条真实 CCH 对话验证，自我介绍与情绪回应已从职责清单改为自然短答。发送与接收无错误。

联调中发现并修复两处启动问题：固定依赖快照缺少 Hermes 飞书平台注册需要的 `qrcode`，以及显式飞书 Gateway 配置未传入 App ID；同时加入启动前平台准入检查，阻止依赖/配置准入失败后退化为“仅运行 Cron”的假成功。连接后的网络失败仍由 Hermes 原生重试和状态处理。固定环境补装 `qrcode==7.4.2` 与 `pypng==0.20220715.0`，未修改 Hermes 源码。全量 188 项通过（254.206 秒）；人格调整后 27 项接入/原生/persona 回归通过（5.129 秒），文档与 diff 检查通过。

macOS 本机还记录一个 Hermes 可选 liveness UNIX socket 路径过长警告；飞书 WebSocket 不受影响，后续 VM 部署时使用较短 `HERMES_HOME` 路径复验。旧 profile 的 `.env` 仅含此前 `/sethome` 写入的飞书默认投递字段，已移出并保留为本机 `native-home-channel.env.saved`，不含模型或应用凭据。

## 飞书认证与消息前

飞书应用凭据已从本机 JSON 的误填字段移至 `config/local/platforms.env`，文件权限为 0600，JSON 恢复为环境变量名称，两份文件均被 Git 忽略。复用固定 Hermes 官方探针完成真实机器人认证，返回 `configuration=ready`、`connection=passed`、`bot_identity=passed`、`owner_bound=true`。未输出凭据、建立长连接或发送消息；负责人真实消息身份和收发仍为 `not_checked`。应用发布、权限生效与事件订阅待消息联调核实。

## GitHub 认证

2026-09-21，使用负责人指定的本机 token 文件，通过现有 `connections` 诊断调用真实 GitHub `/user`，确认账号为 **Mikasa-0910**，`connection=passed`、`identity=passed`。token 仅在检查进程内读取并注入环境，未打印、复制或写入配置；没有建立常驻服务的凭据注入。仓库配置为空，`repository_access`、`write_access`、`webhook` 均为 `not_checked`。未创建内容、推送或向任何人发送消息。飞书负责人 Open ID 已写入本机配置，App ID、App Secret 和应用发布状态仍待准备。

## 账号接入调整

按负责人要求，GitHub 先接独立账号，不再以指定仓库为前提。账号探针在空仓库配置下只检查 `/user`；身份正确时通过，仓库与写权限保持未验证。专项 7 项通过（2.759 秒），最终全量 **188 项通过（323.463 秒）**，文档、doctor 与 diff 检查通过。该次代码验证时尚未提供真实 token；当前真实账号验证结果见上节。

## 接入初版

GitHub/飞书接入准备：全量 **187 项 unittest 通过（323.032 秒）**；追加 Gateway 启动加载验证后，接入测试 **7 项通过（2.493 秒）**，其中固定 SDK 检查在本机实际运行、未跳过。文档检查、默认 doctor 和 diff 检查通过。默认示例仍未配置模型，doctor 的执行成功不表示模型连接已验证。

新增覆盖 GitHub GET-only 身份/仓库/base/列表探针、不把 push 角色当作 token 写权限、缺配置诊断不初始化任务库、飞书凭据隔离、owner profile 互斥与无密钥落盘。真实固定 Hermes/lark SDK 验证负责人准入、陌生人/机器人/群聊拒绝、Open ID 与可选 User ID 解析、事件处理器构造及 Gateway 配置。官方 Gateway `--help` 路径经过 Mikasa plugin/persona 加载检查；未建立飞书连接或调用模型。精简 CI 依赖不包含完整飞书/模型包时，这两项完整 SDK 检查明确 skip，其余接入回归照常执行；远端 CI 本轮未执行。

本机 `config/local/hermes-cch.json` 的只读配置检查显示：GitHub token 未注入、授权仓库为空；飞书 App ID/Secret 未注入、负责人 ID 未绑定。真实 GitHub/飞书探针、应用发布、消息往返、正式 Review、webhook 与 VM 均未验收；未启动或重启现有正式 profile。外部信息获取与联调步骤见[接入手册](runbooks/CONNECTIONS.md)。

## 上一轮基础

完整受管状态备份提交 `011248c`：177 项 unittest 通过（244.515 秒），文档检查、doctor 与 diff 检查通过。`probe_native_events.py` 的 15 项真实 SDK/本地模型夹具检查通过，覆盖新目录恢复后的原回执、会话、记忆、Key、身份/skills、取消与幂等，无重复推理。

备份回归包含 WAL、任务/回执配对、Cron 文件、Git 对象/执行位、记忆链接、运行路径迁移、凭据排除、并发拒绝、篡改拒绝和失败不发布目标。这里的“完整”限定为受管 runtime；不含外部凭据、依赖、外部 provider 状态或日志缓存。

清理阶段：全量 **179 项通过（267.076 秒）**，修复原生 API 错误响应未显式关闭的问题，资源警告未再出现。最终补充工作区数据库按字节保留后，受影响的备份、Cron、CLI 和双库配对恢复 **16 项通过（43.445 秒）**。真实 Gateway 事件/恢复探针再次 **15 项通过**；文档、doctor 与 diff 检查通过。原生 Cron 在新目录保留 job、下次时间和旧 execution，并能继续向新 Kanban 入板。

清理删除 38 个重复或过时跟踪文件，重写 README、当前架构和推进计划；删除 22 份本地历史探针报告、2 份旧执行器日志及约 50 MiB 字节码缓存。身份、规范、skills/许可、正式会话/记忆、凭据和 Hermes 依赖保留；检测到活跃 Gateway，其 profile 日志未清除，也未重启。没有请求真实 CCH、GitHub、飞书或 FluxCore。

## 历史实测

以下是已有版本的真实验证，不能替代当前 checkout 的重新验收。旧完整文档和脱敏 JSON 已收归 Git：`git show 3b436b1:docs/VALIDATION.md`，相同 revision 下还可读取原 `HERMES_CCH_VALIDATION.md`、`NATIVE_HERMES_VALIDATION.md` 与 `*-evidence.json`。本机旧临时探针报告已清理。

| 范围 | 已有证据与限制 |
| --- | --- |
| CCH 真实请求 | 2026-09-20 完成 persona、拆解、审查、实现及合成任务链，后续完成原生 Docker 工程与 GPT Responses ↔ Claude Messages 会话切换；不是 FluxCore 验收 |
| 模型身份 | 曾请求 gpt-6-astra 而响应标识为 gpt-5.6-luna；响应名不能独立证明底层模型，default 分组仍未验证 |
| 原生 CLI | 13 项真实 SDK/本地目录夹具检查；其中一项记录 `/new` 自定义 provider 的上游限制，并非修复它 |
| 工程与记忆 | 47 项固定 SDK/真实 Docker/本地模型夹具检查：续话、压缩链、共享记忆、工具修复、最终验收、容器清理与身份/skills |
| 旧数据与 skills | 12 项固定 SDK 离线检查：原生导入、账号隔离、persona、三类工程 skills 与 MEMORY/USER 持久化 |
| Kanban 与 Cron | 当前 unittest 直接调用固定 SDK，覆盖迁移、租约、并发、依赖、原生 tick、脚本子进程、execution 及故障恢复 |

本机 Hermes 是官方 archive 的经 Git blob 校验的运行源码子集，不是完整开发 checkout；没有运行 Hermes 上游测试套件。正常安装使用固定官方 Git revision，见 [执行器安装](../workers/hermes/README.md)。

## 尚未验收

GitHub 真实账号身份及飞书应用机器人认证、负责人单聊消息往返已验证；GitHub 仓库权限、正式写入与 webhook，飞书群聊、目标 VM、TLS 与恢复演练，以及聊天工程入口和 FluxCore 联合验收均未完成。CCH 管理端分组证据仍缺失；不重复绕过先前的 WAF 拒绝。

SDK/模型夹具证明协议、工具和存储链路，不能证明真实模型始终遵循人格、skills 和记忆。默认 doctor 不联网；`--probe-model` 才消耗模型额度。所有可重复探针及其前提见 [脚本说明](../scripts/README.md)。
