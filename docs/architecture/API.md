# CLI 与 HTTP 契约

CLI：`python3.12 -m mikasa --config CONFIG 命令`。本地 shell 是受信任操作系统账号入口，不用于模拟聊天成员鉴权。

| 入口 | 行为 |
| --- | --- |
| `engineer --cwd DIR -- chat` | 完整 Hermes 工程 CLI，-- 后原样透传 |
| `engineer -- kanban --help` | 原生任务与调度命令 |
| `engineer -- cron --help` | 原生计划任务命令 |
| `chat [--session ID]` | 原生聊天 CLI 与会话恢复 |
| `chat --message TEXT [--session ID]` | 保留的 HTTP 聊天适配，输出 JSON |
| `gateway --platform feishu --platform weixin` | 统一消息 Gateway |
| `connections PLATFORM [--probe]` | 配置检查或只读联网探针 |
| `doctor [--probe-model] [--model ID]` | 默认只读本机条件；显式临时 Gateway 模型探针 |
| `backup DIR` / `restore BACKUP NEW_RUNTIME` | 停服快照 / 恢复到新目录 |

原生 chat 的 --resume、--worktree、--max-turns、--toolsets 等按 Hermes 自身语义执行。工程工具、任务、会话输出不经过 Mikasa worker JSON 协议。

HTTP 默认 127.0.0.1:8765，除 health 和退休 webhook 提示外需要 Bearer token；账号从配置映射读取，body 不能自称身份。

| 方法与路径 | 行为 |
| --- | --- |
| POST /chats | {} 创建当前账号聊天 |
| GET /chats/{id} | 所属账号的原生历史最近一页、模型和 revision |
| POST /chats/{id}/messages | message 字段，必需 Idempotency-Key |
| POST /chats/{id}/stop | {} 停止当前原生运行 |
| POST /control | 负责人设置 paused，仅控制此 HTTP 适配 |
| GET /health | 存活与 HTTP 暂停状态 |
| /tasks、/tasks/{id} 及其子路径 | 鉴权后 410，迁移提示 |
| POST /webhooks/github | 410，不消费或派发事件 |

HTTP /new 返回新 chat_id，保留模型，调用方需跟随新 ID；同一幂等键重放返回同一结果。/model 仅修改当前聊天；/init 返回 deferred_command，未接入命令返回 unsupported_command。原生消息与 CLI 的完整系统命令不受 HTTP 子集影响，见 [聊天手册](../runbooks/CHAT.md)。

请求体上限 1 MB，须使用 Content-Length；错误为 400/403/404/409/410/500。TLS 和入站限流由部署环境提供。HTTP 暂停不控制独立 engineer 或消息 Gateway。

旧 submit/run/publish/expand 等 CLI 与第三方 worker v1 协议已删除，不再有任务类型或负责人发布业务引擎。旧数据保留在受管备份；旧调用方应迁到原生 CLI，而不是重试退休 API。停止发送旧请求后，410 路由可在未来 HTTP 接入迁移中一并删除。
