# 0008：工程持续会话与账号记忆

日期：2026-09-21。延续负责人确认的 [原生优先目标](0006-hermes-native-mikasa.md)。固定 Hermes 0.21.3，revision `f9524d3f119c672e4a4444f56d582e7475716ba3`；不修改上游。

## 选择与所有权

此前工程每次调用建立随机会话，任务记忆与聊天隔离。聊天中确认的长期协作安排无法自然进入工程执行，宿主修复轮也无法完整接续原生工具历史。本阶段改为原生持续会话与同账号记忆文件共享。

| 层 | 职责 |
| --- | --- |
| Hermes | SessionDB、压缩后续、工具历史恢复与去重、会话持久化；MemoryStore 文件锁、原子更新、容量限制与系统提示快照；SOUL、skills、推理和工具循环 |
| CCH | 模型供应、协议对应的网关路由与分组；本阶段不改变路由配置 |
| Mikasa | 从可信任务元数据绑定账号与仓库，准备 profile、身份和 skills；传递原生会话/调用 ID，保留当前快照、独立验收及必要交付适配 |

## 数据与生命周期

- 账号 home 仍为 `runtime/native/<账号 SHA-256 前 24 位>`。工程 home 为 `runtime/engineering/<task-id>`，保留独立 SessionDB、终端配置和 workspace。
- 工程 `memories` 目录直接链接该账号 home 的 `memories`；Hermes 固定版本没有独立 memory root 配置，因此仅在文件系统绑定目录，不复制记忆、不镜像数据库、不覆盖原生记忆工具。同账号多个任务和聊天写入同一文件，由原生 MemoryStore 的锁与读后原子替换协调。
- 账号来自宿主保存的 `task.actor`；正文、PR 和工具输出不能指定 memory owner。任务首次绑定 actor/task-id/repo 后不允许复用为其他绑定。不同账号相互隔离；任务终端不挂载账号 profile 或长期记忆。
- 同一任务使用文件锁互斥，锁冲突在 profile 修改前失败，异常退出释放。不同任务不占用聊天进程锁，也不修改账号 config.yaml/state.db。原生记忆采用 SDK 默认容量和任务配置，不继承聊天模型/终端偏好。
- 根会话固定为 `mikasa-task-<task-id>`。每次调用由 `SessionDB.get_compression_tip` 找到当前后续，再用 `get_resume_conversations` 取得原生模型历史，保留工具消息和已持久化标记；重新打开会话后交给 AIAgent。业务 SQLite 不重建历史。
- 持久 session_id 与随机 run_id 分开。后者传入 `run_conversation(task_id=...)`，使原生 Docker 标签与宿主验收/清理 ID 一致；重试不会接回旧容器。启动解释器保留 venv 路径，不跟随其符号链接变成基础 Python。
- SDK 正常关闭会话、排空容器清理并关闭 DB；超时/取消仍由宿主回收进程和本轮容器。重新执行读取已持久化历史，不保证突然中断的最后一条消息已保存，不自动重放未完成工具副作用。当前工作区与新工具读取优先于历史中的旧源码事实。

## 记忆语义与迁移

经确认的长期偏好、协作分工可通过原生 memory 保存；临时任务要求与检查结果留在任务会话。新工程实例加载账号记忆，新聊天实例也能读取工程保存的长期约定。同一实例的系统提示使用冻结快照，不承诺外部写入即时热刷新；普通聊天正文不会自动进入工程历史。

这是一套共享原生存储，不是强制规则引擎：Agent 仍可能遗漏或错误使用记忆。身份与 skills 继续指导来源判断和工程质量；外部平台权限由平台配置决定。

已有任务若存在实体 `memories/`，首次准备时重命名为 `memories.legacy/` 留档，然后绑定账号目录。归档冲突、意外链接或绑定变更时失败并保留原数据；不自动把旧仓库笔记合入账号长期记忆。旧 state.db 保留；旧随机 session 不自动接到新的稳定根会话，新续话从升级后的首次调用开始。

恢复或迁移须停掉相关进程、保留整个受限 runtime（包括原生 SQLite/WAL、账号 memories、任务档案和目录链接）。链接目标目前是绝对路径，跨机器移动需重新绑定到目标 runtime；错误目标会被拒绝。仅备份业务 SQLite 仍不足以恢复原生状态，完整 backup 迁移属于后续工作。

## 验证与剩余范围

`scripts/probe_engineering_state.py` 使用一次性账号和仓库、本地 HTTP 模型夹具、固定 SDK 与真实 Docker，走正式 Worker→bridge→AIAgent 路径。覆盖跨进程续话、完整工具历史、不重复落库、畸形最终结果后的恢复、原生压缩后续、账号记忆双向可见、并发写入、账号隔离、身份/skills 注入、容器 ID/清理与凭据不落盘。模型响应是夹具；这证明原生存储和工具链兼容，不代表真实 CCH 模型遵循约定的验收。

本阶段实际验收：全量 `python3.12 -m unittest discover -v` 140 项通过；上述 SDK/Docker 探针 26 项通过；`probe_native_offline.py` 的迁移、persona、三类工程 skills 和记忆加载 12 项通过。文档检查与 diff 检查通过。默认 doctor 正确报告示例未配置模型；本机 CCH 配置 doctor 报告 configuration=valid、connection=not_checked、provider_group=unverified。

本阶段不重启正式账号 profile，不触发 GitHub/飞书消息或发布，不重复请求此前被 WAF 拒绝的 CCH 目录。CCH `default` 分组仍待网关侧证据；过去真实联调结果仅为历史记录。

工程外层修复循环、任务队列、结构化交付和快照验收仍存在，不能把持续会话接通说成全部生命周期迁移完成。下一步收窄外层工程流程并迁往 Kanban 单一任务事实源，再接 Cron、事件和原生备份；之后 GitHub/飞书、VM，最后聊天工程任务与 FluxCore。外部账号和 VM 信息按负责人要求稍后讨论。
