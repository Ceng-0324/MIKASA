# 0009：修复循环交回 Hermes

日期：2026-09-21。延续 [0006](0006-hermes-native-mikasa.md) 的原生优先目标及 [0008](0008-engineering-state.md) 的持续会话。固定 Hermes 0.21.3，revision `f9524d3f119c672e4a4444f56d582e7475716ba3`，不修改上游。

## 已实现的收窄

此前 Hermes 已能在原生工具循环内检查、修复和复查，但 Service 最终检查失败后仍根据 max_attempts 再次启动 worker，形成两层修复调度。现在删除 Service 的固定轮数循环、repair diff 构造和 attempts 聚合，每次认领只调用一次 worker。

Hermes 根据工具返回的实际失败继续修改，使用同一 AIAgent 的上下文、原生工具与资源预算。Mikasa 的 `mikasa_run_checks` 仍只执行仓库配置的检查、导入合法差异和返回结果，不代替 Agent 决定下一步。结束后宿主独立验收一次最终树，通过才创建本地提交；未配置 checks 或检查失败时返回 blocked，保留现场，不自动重启 Agent。

平台取消、超时、输出上限及失效执行令牌的保护保持有效。工程单次 24 次原生迭代、128 个工具证据事件及 worker.timeout 继续限制资源。这里没有新审批引擎，也没有模型路由变更：Hermes 拥有推理/修复循环，CCH 负责模型供应，Mikasa 保留当前隔离、数据保护、身份/skills 和交付适配。

## 重试与兼容

显式 retry 仍使用新工作区并恢复同任务的原生 SessionDB；若上次结果含最终 checks，以 `context.previous_validation` 传递历史检查及版本，并明确旧改动未自动复制。旧现场、会话与记忆不删除。失败信息不自动写入长期记忆，临时工程事实留在会话和任务证据中。

第三方 worker v1 的 stdin/stdout 和 RPC 结构不变，工具内修复由其自行负责；不再提供宿主重启式修复。新任务结果不生成 attempts，使用 execution.tool_events 和 checks 表示工具内检查及最终验收。旧结果中的 attempts 保持原样可读。

旧部署配置中的 worker.max_attempts 暂时可读取，但不再有执行作用；doctor 返回 deprecated_settings 提示，示例已移除此项。此兼容仅针对现有 v1 配置，下一版配置迁移时删除；不增加新旧运行模式开关。不自动编辑本机认证或运行配置。

## 验证

正式探针 `python3.12 scripts/probe_engineering_state.py` 使用本地 HTTP 模型夹具、固定 SDK 和真实 Docker，在临时仓库经过 Service→Worker→AIAgent：

- 原生 write_file 产生错误实现，检查返回失败；同次会话修复并复查变绿，宿主最终验收后创建本地提交。
- Agent 带未修复结果结束，宿主 blocked，单次 worker 调用、单次最终验收，无提交、无自动重新排队。
- 工具检查通过后再次写坏源码，最终验收发现失败，不能用先前绿灯交付新版本。
- 身份、工程 skills、账号记忆和续话的既有探针继续执行；数据与合成凭据不进入正式 profile。

这些检查证明原生循环与交付契约，不证明真实模型一定主动完成修复。未调用 CCH、修改上游或发送平台消息；CCH default 分组、GitHub/飞书、VM 和 FluxCore 验收仍未完成。

本阶段实际结果：全量 `python3.12 -m unittest discover -v` 141 项通过（67.319 秒）；扩展后的 SDK/Docker 探针 44 项全部通过；文档链接、canonical 顺序和 diff 检查通过。默认 doctor 正确报告示例未配置模型；本机 CCH 配置为 valid、connection=not_checked，并明确提示旧 max_attempts 已停用。

## Kanban 接入依据与下一阶段

本轮读取固定源码中的 hermes_cli/kanban_db.py、kanban_db_dispatch.py 和 kanban_ops.py。原生已有依赖、幂等任务创建、claim/run 租约、heartbeat、阻塞/完成、调度恢复和事件；dispatch_once 支持 spawn_fn，默认路径启动具名 profile 的原生 CLI。未注册为 profile 的 assignee 由默认调度跳过，不能直接把 Mikasa GitHub 昵称当作可执行 profile。

当前 Mikasa 仍使用业务 SQLite 队列、runner、任务 API 和发布回执；本阶段没有声称已接入 Kanban。下一阶段需一起处理：旧任务及依赖/结果/事件的映射、唯一任务事实源、原生账号与执行 profile、工作区及独立验收接入、认领/取消/恢复与幂等、既有 API 的迁移边界。采用原生调度或有实际集成职责的 spawn_fn；不仅套一层 Kanban 表读写而保留第二套队列，不启用原生可选 PR acceptance 门禁来重新建立已经删除的治理引擎。

该迁移后再接 Cron、事件和完整原生备份，随后 GitHub/飞书、VM，最后聊天工程任务与 FluxCore。外部信息仍按负责人要求稍后讨论。
