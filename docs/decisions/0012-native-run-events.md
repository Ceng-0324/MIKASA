# 0012：聊天等待消费 Hermes 原生运行事件

日期：2026-09-21。延续 [原生优先方向](0006-hermes-native-mikasa.md)，使用未修改的 Hermes 0.21.3、revision `f9524d3f119c672e4a4444f56d582e7475716ba3`。

## 分工和协议事实

HTTP 聊天与 `chat --message` 的运行等待不再每 150ms 查询状态。Mikasa 消费 Hermes 官方 `GET /v1/runs/{run_id}/events` SSE，由原生事件通知完成，再读取 `GET /v1/runs/{run_id}` 的持久结果。已完成的幂等回执直接读取持久状态，不重新订阅或推理。模型切换的验证调用复用同一等待路径。

固定源码 `gateway/platforms/api_server_runs.py` 中，`_finish` 先保存终态，再写入 `run.completed/failed/cancelled/interrupted` 事件；`_handle_run_events` 消费进程内单个 queue，10 秒发送一次 keepalive，退出时 `_drop_run_transport` 移除 transport。该端点没有事件游标、广播或持久重放机制；`Last-Event-ID` 不提供恢复保证。不要对同一个 run 启动多个消费者。

Hermes 继续拥有运行状态、会话、工具循环、记忆和事件生成；CCH 的模型供应/路由不变。Mikasa 保留当前 API 的账号授权、幂等回执、取消与本机事件传输适配，不另建事件日志或会话存储。人格/工程规则和 skills 仍由原生 profile/plugin 加载。

## 正常、断线与取消

1. 先读原生状态，完成就直接返回；失败、取消或中断保留原有错误语义。
2. 未完成时只建立一次 SSE 连接，等待原生终态或流关闭。正常路径只有初始/最终两次状态读取，不随 delta、工具事件或 keepalive 轮询。
3. EOF、连接错误、404（transport 已回收）或不可解析的流转入同一个 run 的状态恢复，最多每秒查询一次。不重新订阅、不发新 run；持久 API 本身失败时明确报错，保留回执供后续核对。SSE 的 401/403 直接报鉴权错误，不降级绕过。
4. 原有 pause 和 worker.timeout 仍生效；等待期间每约 100ms 检查本机取消/期限，需要结束时先确认原生状态，再发 `/stop`。正常网络请求仍有自身超时，100ms 不代表停止副作用的硬时限。`stop` 失败会报错，不能假称运行已终止；已完成的运行不发送多余 stop。

事件流只负责唤醒。最终 output/runtime 始终取持久状态，并补入原有按 run 保存的身份/skills 证据；不从不完整 delta 拼接最终回答，不将工具参数或事件正文另存到业务库。正常数据和结果字段未变。

`mikasa/run_events.py` 使用标准库 HTTP 客户端，仅连接隔离 Gateway 的 `127.0.0.1`，不跟随重定向。单帧最多 1 MiB，解析异常/超限改读持久状态。一个专用读取线程避免静默流阻塞取消；上下文退出先关闭 socket 的读写，再 join 线程。连接限时 2 秒，静默读限时 30 秒（正常原生 keepalive 为 10 秒），不会留下脱离请求的读取线程。

## 验证与边界

`tests/test_run_events.py` 使用真实本地 HTTP 连接测试多行/CRLF SSE、静默保持、终态后不关流、完成回执、断线与 404、暂停、超时、stop 失败、失败终态、鉴权错误、畸形/超大帧及线程回收。现有聊天幂等、模型切换、账号隔离和 profile 保留回归继续执行。

`python3.12 scripts/probe_native_events.py` 启动固定真实 Hermes Gateway，使用临时 profile、本地模型 HTTP 夹具和合成 Key。它验收真实 SSE 终态、原生 memory 工具、工具历史、身份/规则/skills 证据、相同 run 重放、暂停停止、Gateway 重启后的持久结果/历史/Key 和读取线程回收。不读取真实 CCH 配置、不触碰正式 profile、不发送外部消息。结果见 [验证记录](../VALIDATION.md)。

本次迁移的是内部运行等待，旧 HTTP 仍返回最终 JSON，不新增对外 SSE、工具进度广播或自研聊天 UI。终端已直接由 Hermes CLI 处理，不经过这个适配器。Kanban 工程事件保持原生 task_events；宿主工程同步交接、周期唤醒以及外部渠道尚未完全迁移。事件消费适配将在原生渠道覆盖现有 API 的鉴权、回执和取消契约、并完成调用方迁移后删除。

下一步完整原生状态备份，随后 GitHub/飞书→VM→聊天工程任务与 FluxCore。现有 backup 仍只有任务/回执双库，不含 scheduler、账号/工程会话、记忆和工作区。
