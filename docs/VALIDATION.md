# 验证边界

固定 Hermes 0.21.3，revision `f9524d3f119c672e4a4444f56d582e7475716ba3`。本机为 macOS arm64 / Python 3.12.13，未执行目标 Linux VM 或远端 Python 3.13 CI。

## 本轮验证

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

GitHub 真实服务身份、仓库权限与正式写入，飞书应用/账号/事件，目标 VM、TLS 与恢复演练，以及聊天工程入口和 FluxCore 联合验收均未完成。CCH 管理端分组证据仍缺失；不重复绕过先前的 WAF 拒绝。

SDK/模型夹具证明协议、工具和存储链路，不能证明真实模型始终遵循人格、skills 和记忆。默认 doctor 不联网；`--probe-model` 才消耗模型额度。所有可重复探针及其前提见 [脚本说明](../scripts/README.md)。
