# 0010：Hermes Kanban 接管任务事实源与认领调度

日期：2026-09-21。延续 [0006](0006-hermes-native-mikasa.md) 的原生优先方向。使用固定 Hermes 0.21.3、revision `f9524d3f119c672e4a4444f56d582e7475716ba3`，不修改上游源码。

## 所有权与实际执行

任务、依赖、状态、租约、运行历史及执行事件统一保存到 `runtime/kanban/kanban.db`。`Service.tasks` 通过独立 Hermes Python 进程调用官方 `kanban_db`、`kanban_db_connect` 和 `kanban_db_dispatch`；宿主不加载 SDK 全局环境，不读取模型认证。原 `Store` 的任务队列、依赖判定、认领 SQL 与状态更新已删除。

每次 `run_once` 持有原 runner 互斥锁，经原生 `dispatch_once` 计算可执行任务并原子认领。公开 `spawn_fn` 扩展点将这一个原生 claim 交给宿主同步工程执行器，随后调用现有 Worker→AIAgent→Docker 工具循环。没有第二次认领，也没有镜像队列。当前最多运行一个任务；宿主 CLI 仍负责周期唤醒，原生 Gateway 常驻调度、Cron 和事件驱动是后续阶段，不能把本次说成 runner 已完全移除。

专用 Kanban home 的 `default` 是调度入口，不是用户聊天 profile。机器人账号映射到该入口，人类账号使用不注册为可运行 profile 的 `human-<账号>` 标识，不会被默认调度接管。工程执行仍根据可信 task.actor 连接提交账号的原生 MEMORY/USER，并恢复 `mikasa-task-<外部任务ID>` 的 SessionDB。Kanban 不生成第二份身份、记忆或会话。

Mikasa 保留旧任务 API、结构化交付、快照与独立验收、显式发布和回执适配。CCH 模型来源、路由与切换保持现有职责。原生 `completion_contract=local-only` 不启用 PR acceptance 门禁；`review_dispatch=false` 避免将已经交付的实现自动重新送进工程执行器。审查分工仍由身份、skills 与会话/记忆表达。

## API 与状态映射

旧 HTTP/CLI 字段保留，新增 `native_id` 和 `native_status` 供诊断。新任务直接使用 Hermes 的 `t_<hex>` ID；旧 ID 继续可用，工程 profile、工作区和 publication 标记不重命名。依赖读取原生 task_links，不从旧 payload 重新执行图判定。

| 原生状态 | 旧 API 显示 | 行为 |
| --- | --- | --- |
| ready / todo | queued | 原生判断依赖；未完成父任务时不能 claim 或手动 complete |
| running | running | 使用 claim_lock 与 current_run_id 防止过期执行者写入 |
| review | awaiting_review | 交付等待后续处理，不自动重启 Agent |
| blocked / triage | blocked 或 failed / cancelled | 根据原生状态及历史结束/取消事件展示旧标签；不会自动重试 |
| scheduled | cancelled（取消了尚在等待依赖的任务） | 保留依赖阻塞；显式 retry 用 unblock 重新检查父任务 |
| done | done | 由原生 complete_task 完成，原生推进下游 |

Hermes 的 archived 会视为依赖已终结，不能用于旧 API 的 cancel。对 ready/running 使用 block；review 先原生 reopen 再 block；todo 使用 schedule 停放。已经 blocked/triage 的取消只追加原生事件。原生 block 循环达到阈值会进入 triage，显式 retry 用 specify/unblock 恢复，继续保留原生循环诊断。没有复制原生状态机。

任务事件来自原生 task_events；原生生命周期事件与 Mikasa 执行证据一起返回。seq 使用原生事件序号，不能再假定与旧业务 events.seq 相同或每一步只增加一条事件。旧证据的内容、来源账号和时间保留。发布回执仍由业务库 publications 管理，发布事件不再属于执行事件流。

`mikasa_ids` 仅保存旧 ID 映射、幂等键与规范化原始提交对象，用于核对同键内容/提交者冲突；不保存运行状态或可执行队列。删除兼容适配的条件是旧工程 HTTP/CLI 入口及第三方 v1 worker 完成原生迁移，且所有历史 ID、幂等和发布引用有明确替代；不会在此之前删除历史映射。

## 取消、租约与恢复

原生 claim TTL 为 120 秒，运行中每 30 秒调用 heartbeat。宿主取消轮询只读同一个原生数据库，检查 running、claim_lock 和有效期，没有状态缓存。工具进度与结束操作核验租约，原生结束调用还传 expected_run_id。取消或重试后，旧执行者不能补写证据或完成新运行。

适配操作用独占锁串行，原生 dispatcher 仍使用自己的 tick 锁及事务。此板只由 Mikasa 的适配入口管理；不同时启动另一个原生 Gateway dispatcher 或直接写板来绕过宿主的副作用边界。runner 崩溃后的恢复只在取得独占 runner 锁后执行，用原生 block 关闭遗留 run、保留现场，要求显式 retry，不重做未知副作用。正常运行并非由 SDK 子进程 PID 表示，因此关闭 orphan reconciliation；heartbeat 与宿主互斥锁承担此边界。

交付结果先以原生 tasks.result 保存，再调用原生完成/阻塞/review API。若两步间崩溃，任务仍是 running；下次恢复停放并保留已写入的证据，不会假报 done。适配标签或结束事件写入前崩溃最多显示原生 blocked，不能使失败任务重新运行。

## 旧数据迁移与恢复

首次任务访问自动导入旧 tasks，创建原生记录后统一链接依赖；保留旧 ID、actor、幂等键、结果、错误和事件。旧 running 作为中断任务停放，不继承旧 run_token；旧 awaiting_review 不自动执行。旧 approvals/reviews 和聊天档案不参与调度。

导入事务与原生完成标记一起提交；随后旧 tasks 重命名为只读 `legacy_tasks`，业务库升级 user_version=2。原始 events 保留为档案及业务操作记录，任务读取不再使用它。若在两库切换之间中断，下一次通过原始 tasks/events 的摘要校验恢复，不重复导入；若旧进程改写了源数据，拒绝继续，保留两边数据供核对。迁移失败不会转回旧队列运行。

迁移会检查 runner 锁，旧进程还在执行时拒绝切换。运行前先停止旧版本 API/runner 并保留整个 runtime；不支持新旧二进制混跑。版本 2 业务库通过 board_id 与 Kanban 配对，缺板或错配时拒绝启动。回滚须恢复迁移前整套数据与旧程序，不能仅降版本号。此次开发只迁移临时测试数据，没有迁移或重启正式 profile。

`backup DIRECTORY` 现在生成任务备份目录，含 `mikasa.sqlite3`、`kanban/kanban.db` 与最后写入的 manifest.json。目录 0700、文件 0600，目标不可已存在；活动 runner 期间拒绝备份。两库使用 SQLite backup API，不裸拷 WAL。恢复需停止服务并同时恢复这两个文件。manifest 缺失表示备份未完成。

该备份明确标记 `scope=tasks-and-receipts`，不含 native/engineering 的会话、记忆与工作区，不能当作完整 Mikasa 恢复点。完整原生备份在下一阶段收口。

## 验证与后续

`tests/test_kanban.py` 直接调用固定 SDK，覆盖旧数据迁移、切换中断后恢复、源数据变化拒绝、缺板拒绝、唯一认领、依赖、取消、旧租约、heartbeat、review 不重调度、双库备份恢复。现有任务、HTTP/CLI、聊天和发布回归继续执行；CI 安装固定上游源码和仅控制面依赖，不用自研假队列代替原生语义。

`scripts/probe_engineering_state.py` 在临时 runtime、合成仓库和本地模型 HTTP 夹具上验证 Kanban→真实 Hermes SDK→Docker→最终验收/提交，并验证身份、工程 skills、账号记忆与续话；不调用真实 CCH、不发送 GitHub/飞书消息、不运行 FluxCore。实际检查结果见 [验证记录](../VALIDATION.md)。

下一阶段为 Cron、事件与完整原生备份，随后 GitHub/飞书、VM，最后聊天工程任务与 FluxCore。CCH default 分组仍未取得网关侧证明，外部凭据与 VM 信息按负责人要求稍后讨论。
