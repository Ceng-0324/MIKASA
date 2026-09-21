# CLI 与 HTTP 契约

CLI：`python3.12 -m mikasa --config <配置路径> <命令>`。本地 CLI 仅供受信任的操作系统账号使用，按负责人权限执行；不能将 shell 账号交给普通成员来实现多用户鉴权。

`chat`（不带 `--message`）直接启动 Hermes 原生 CLI，不创建 Mikasa 业务服务或输入循环。`--session` 接受原生会话 ID，命令、全局模型偏好与会话恢复由 Hermes 处理。下文聊天 JSON 字段、幂等回执及命令限制仅适用于 HTTP 和 `chat --message`；原生 CLI 新会话不会自动注册为旧 API chat_id。两种入口的行为见 [聊天手册](../runbooks/CHAT.md)。

`doctor` 包含脱敏的本地模型配置状态，默认不联网；tasks 字段仅检查 Kanban 源码/Python 是否存在，不打开数据库或执行迁移。显式 `doctor --probe-model` 发起一次模型验证，失败退出码为 1；不建立聊天或工程任务。诊断字段与限制见 [CCH 手册](../runbooks/CCH.md)。

`doctor --model MODEL_ID` 按指定模型诊断配置，结合 `--probe-model` 验证实际协议。聊天 `/model` 和 `/models` 回复可包含 `model_options` 数组，仅列受信任配置中的候选 ID，交互客户端通过消息 API 发送 `/model MODEL_ID`；不增加任意端点/配置修改接口。未接入的斜杠命令返回 `kind=unsupported_command`，`/init` 返回 `deferred_command`，均不调用模型。`/new`（别名 `/reset`）返回 `kind=new` 和新 `chat_id`，客户端须跟随新 ID；在旧会话重放同一幂等键可取回同一结果。当前模型保留，新会话 revision=0、无历史；旧会话不删除。

HTTP 默认监听 `127.0.0.1:8765`。除健康检查和单独验签的 GitHub webhook 外，均需要 `Authorization: Bearer <token>`。token 通过配置中的账号到环境变量名映射识别，不采信 body 中的自称身份。

| 方法和路径 | 行为 | 权限 |
| --- | --- | --- |
| `POST /chats` | body `{}`，创建当前账号的聊天 | 已配置成员 |
| `GET /chats/{id}` | 模型、revision、原生历史的最近一页（最多 500 条消息）及截断标记 | 会话所属账号 |
| `POST /chats/{id}/stop` | `{}`，请求停止当前原生运行，包括切换验证；不等待发送锁 | 会话所属账号 |
| `POST /chats/{id}/messages` | `{"message":"切换为 gpt-5.6-luna"}`，必需 Idempotency-Key | 会话所属账号 |
| `GET /health` | 存活与暂停状态 | 无认证；不含任务信息 |
| `GET /tasks` | 最近 500 个任务 | 已配置成员 |
| `GET /tasks/{id}` | 状态、结果和错误 | 已配置成员 |
| `GET /tasks/{id}/events` | 任务事件历史及实时执行进度 | 已配置成员 |
| `POST /tasks` | 创建任务，必须携带 `Idempotency-Key` | 成员可提交分析需求；负责人可实施和派发 |
| `POST /tasks/{id}/cancel` | 取消，失效运行令牌 | 负责人 |
| `POST /tasks/{id}/retry` | 重试失败、阻塞或取消任务 | 负责人 |
| `POST /tasks/{id}/assign` | `{"assignee":"账号"}` | 负责人 |
| `POST /tasks/{id}/complete` | 附 `evidence` 完成任务，包含本地实现交付 | 负责人 |
| `POST /tasks/{id}/expand` | 拆解结果转实施任务，保留依赖 | 负责人 |
| `POST /tasks/{id}/publish` | 发布 Issue、草稿 PR 或正式 Review | 负责人；需额外启用发布配置 |
| `POST /control` | `{"paused":true}` 或 `false` | 负责人 |
| `POST /webhooks/github` | HMAC SHA-256 签名校验和 delivery 去重 | GitHub webhook secret |

模型任务结果可包含 `execution`，记录可信 worker 提供的 SDK 版本、请求模型、API 模式、规则和 skill SHA-256 及工具数；这是宿主注入证据，不是模型自述；Hermes 的 post_api_request hook 另提供 reported_model，表示 SDK 观察到的响应标识，仍不独立证明供应商实际模型身份。聊天接口语义和失败处理见 [聊天手册](../runbooks/CHAT.md)。

内置 Hermes 工程执行另返回 `session_owner=hermes`、`root_session_id`、`session_id`（可能为压缩后的后续会话）、`history_messages` 和 `memory_owner`。根会话固定为 `mikasa-task-<task-id>`，记忆归属取自可信任务提交账号，不能由任务 body 指定。重试与修复读取原生 SessionDB，不从任务事件重拼历史；失败不会回滚已经落盘的会话或记忆。旧随机工程会话保留为档案，不自动接入新根会话。详见 [当前架构](../architecture/README.md)。

每次认领只调用一次 worker，最终验收失败返回 blocked，不再自动生成宿主修复轮。新结果不生成 `attempts`，工具内检查记录在 `execution.tool_events`，最终验收记录在 `checks`；旧任务结果保持可读。validation 事件不再携带外层 `attempt`。显式 retry 时 worker context 可含 `previous_validation`（上次 checks、head、base），只是历史证据，不复制旧工作区。第三方 v1 worker 同样自行完成内部修复，stdin/stdout 结构和工具 RPC 不变。见 [当前架构](../architecture/README.md)。

任务示例：

```json
{
  "kind": "plan",
  "repo": "owner/repository",
  "title": "需求描述",
  "acceptance": "可验证的完成条件",
  "depends_on": [],
  "assignee": "Mikasa-0910"
}
```

`kind` 支持 `audit`、`plan`、`implement`、`review`、`followup`；`review` 还必须提供正整数 `pr`。仓库必须由运维配置允许；任务不能自行指定任意 URL、命令或本地路径。相同幂等键和相同请求返回原任务，内容不同返回 409。

POST 请求体最多 1 MB，必须使用 Content-Length；错误分别返回 400、403、404、409 或不暴露内部信息的 500。服务不提供 TLS，跨机器访问应放在可信 TLS 反向代理之后，限制请求并发和速率。

`server.auto_review=true` 时，PR opened/reopened/synchronize/ready_for_review 事件创建只读审查任务，结果先留为本地草稿。webhook 文本不会自动触发代码实施或发布。定期审计由 `schedules.audit_interval_seconds` 控制，默认 0 关闭。

发布歧义恢复仅提供本地 CLI `resolve-publication TASK EXTERNAL_ID`，读取外部记录并核对作者、任务标记和提交，不盲目重发。`backup DIRECTORY` 创建完整受管状态快照，`restore BACKUP NEW_RUNTIME` 校验后恢复到新目录，均不覆盖已有目标或提供 HTTP 写入口；见 [操作手册](../runbooks/OPERATIONS.md)。

执行时无需等待最终结果即可读取 `GET /tasks/{id}/events` 或 CLI `events TASK_ID`。`kind=execution` 的 `data` 包含 `phase`（workspace/worker/tool/validation/commit）、`status`（started/completed，worker 还可能 failed）。worker 与其工具事件共享 `invocation`，工具另有 `call` 序号；completed 表示该调用已返回，是否成功看 `ok` 或检查退出码，不代表任务已交付。

宿主记录工具名称、已验证路径、读取版本/摘要/覆盖范围和检查退出码，不写入模型推理、原始工具参数、源码正文或 SDK 错误文本。开始事件先于工具副作用落库；完成事件在返回模型前落库。进程被突然终止时可能只有 started，不能推断副作用未发生，必须核对保留工作区。取消或重试会失效运行令牌，禁止旧执行者追加记录；历史事件继续保留。该机制提供追踪，不实现会话自动续跑。

可识别的模型故障在 `worker/failed` 事件附加固定词表 `error_code`。聊天切换失败时 `execution` 可仅含 `error_code`，不能当作成功的模型运行证据；原模型和 revision 保持不变。

任务由 Hermes Kanban 保存并调度。新 ID 形如 `t_<hex>`，迁移旧 ID 保持可用；返回值新增 `native_id`、`native_status`，旧 state 标签作为兼容视图保留。events 包含原生生命周期事件，seq 改为原生事件序号；发布回执另由业务库管理。取消不会解除子任务依赖，手动 complete 也须满足原生父任务条件；详见 [当前架构](../architecture/README.md)。

HTTP/`chat --message` 内部以原生 SSE 等待运行完成，最终 JSON 字段不变，不开放新的对外 SSE 路由。事件流缺失或断开时只恢复相同 run 的持久状态，不能承诺重放中间进度；正常等待、取消与断线语义见 [当前架构](../architecture/README.md)。
