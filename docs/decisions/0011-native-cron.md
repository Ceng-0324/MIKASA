# 0011：周期审计使用 Hermes Cron

日期：2026-09-21。承接 [Kanban 迁移](0010-native-kanban.md)，继续使用未修改的 Hermes 0.21.3、revision `f9524d3f119c672e4a4444f56d582e7475716ba3`。

## 分工与调用链

`Service.schedule()` 不再通过墙钟除法生成时间槽。宿主在 `run_once` 中唤醒官方 `cron.scheduler.tick(sync=True)`；Hermes 负责到期判断、锁、pending slot 恢复、执行记录、失败记录和下一次时间。宿主仍保留 CLI 唤醒循环与同步工程交接，本次没有宣称常驻 runner 已全部原生化。

当前 tick 位于单任务执行前；长工程任务期间不另起后台 tick，审计可能延迟至任务结束，再按原生漏跑策略处理。这是现有同步执行器的限制，不是精确定时服务。

独立 `runtime/scheduler` home 内只有一个定期审计 job；这里和其他文档中的 runtime 均指配置的 runtime 路径，默认是 `runtime/state`。Job 使用官方 `no_agent=True` 与 `deliver=local`，实际运行 `scripts/mikasa-audit.py`。脚本读取原生 execution 的 `scheduled_instant`，再调用现有 Kanban 适配入口；没有模型推理、第二套任务队列或外部消息。

脚本核对原生 execution 为 running，且 owner PID 是启动它的父进程。幂等键为 `cron:<job-id>:<scheduled-instant>:<repo>`；同一 occurrence 在提交后、原生记录完成前崩溃，重复入板仍返回原任务。已存在 queued/running audit 的仓库跳过本次触发，不积压补审任务。检查与创建同持 Kanban 适配锁，查询不受旧列表接口 500 条分页限制。

审计执行仍走原生 Kanban→现有 GitHub 只读审计实现；Cron 只入板，不执行仓库工作或发布。本次不修改身份、skills、记忆、工程会话或 CCH 路由。Hermes 的一般 Agent Cron 默认跳过长期记忆；本专用 job 更直接使用 no_agent，不能据此声称定时任务加载了人格或工程记忆。

## 配置与生命周期

沿用 `schedules.audit_interval_seconds`：0 关闭，60–604800 秒启用。通过官方 schedule mapping 的 fractional minutes 保留秒精度，例如 90 秒为 1.5 分钟。首次启用后等待一个间隔，**不再像旧实现一样启动即立即建审计任务**。

同一原生 job 内 `mikasa_interval_seconds` 只记录已应用的宿主配置值。没有独立 schedule store；真正的 schedule、next_run_at、暂停和执行结果由 Hermes 管理。重启且配置不变时保留原生的暂停与 schedule 编辑，不重置倒计时。明确修改间隔会应用新周期并启用；改为 0 则暂停并保留历史，再启用时仍使用同一个 job。原生配置更新中断可由 `mikasa:configuration` 暂停原因恢复。

Mikasa 的全局 pause 通过原生 `can_dispatch` 留住未派发的时间槽，入板时再查一次暂停。恢复后按固定 Hermes 的漏跑策略处理，不自研补跑队列。单次脚本限时 60 秒、调度 RPC 限时 90 秒；失败写入原生 job/执行账本，并向 runner 返回错误，不被当成审计成功。

专用 home 不加载模型或平台认证，拒绝 `.env`、auth.json、外部链接入口以及不兼容 job；不在这里启动第二个原生 daemon/Gateway ticker。账号 home 的个人 Cron 与此 home 分开。外发投递、通用聊天 Cron 和多账号 ticker 不在本次接入范围。

## 运行状态与恢复

- `scheduler/cron/jobs.json`：官方任务定义与下次时间。
- `scheduler/cron/executions.db`：官方执行账本及 occurrence；它不是重试队列。
- `scheduler/cron/output/`：官方脚本执行结果。
- `scheduler/integration.json` 和 `scripts/`：可重新生成的适配输入，只含路径、身份、仓库名称和 job ID，不含 token 或完整模型配置。

停机升级时保留整套 runtime。现有 `backup` 仍只备份任务与回执，不包含 scheduler 或账号/工程 profile，不能用它恢复完整运行现场。完整备份是后续独立迁移。

## 验证与后续边界

`tests/test_cron.py` 调用固定真实 SDK 的 job API、tick、脚本子进程、执行账本和 Kanban；覆盖首次等待、秒精度、重启保持时间、重复触发、入板重放、活跃审计去重、宿主/原生暂停、配置停启、原生编辑、竞争锁、凭据隔离、脚本失败以及派发前进程退出后的 pending slot 恢复。无真实模型或外部消息，GitHub 审计响应使用本地夹具。实际结果见 [验证记录](../VALIDATION.md)。

后续先接原生运行事件，再完成完整原生状态备份；随后 GitHub/飞书→VM→聊天工程任务与 FluxCore。源码调查确认 `/v1/runs/{run_id}/events` 是进程内队列且断线会回收 transport，不提供持久重放；事件迁移须保留持久状态恢复，不能声称无损重连。官方备份默认可能包含认证文件及外部 memory provider 路径，须先收口范围，不能直接把其默认归档当成 Mikasa 可迁移备份。
