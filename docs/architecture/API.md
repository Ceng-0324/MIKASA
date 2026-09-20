# CLI 与 HTTP 契约

CLI：`python3.12 -m mikasa --config <配置路径> <命令>`。本地 CLI 仅供受信任的操作系统账号使用，按负责人权限执行；不能将 shell 账号交给普通成员来实现多用户鉴权。

HTTP 默认监听 `127.0.0.1:8765`。除健康检查和单独验签的 GitHub webhook 外，均需要 `Authorization: Bearer <token>`。token 通过配置中的账号到环境变量名映射识别，不采信 body 中的自称身份。

| 方法和路径 | 行为 | 权限 |
| --- | --- | --- |
| `GET /health` | 存活与暂停状态 | 无认证；不含任务信息 |
| `GET /tasks` | 最近 500 个任务 | 已配置成员 |
| `GET /tasks/{id}` | 状态、结果和错误 | 已配置成员 |
| `GET /tasks/{id}/events` | 任务事件历史 | 已配置成员 |
| `POST /tasks` | 创建任务，必须携带 `Idempotency-Key` | 成员可提交分析需求；负责人可实施和派发 |
| `POST /tasks/{id}/cancel` | 取消，失效运行令牌 | 负责人 |
| `POST /tasks/{id}/retry` | 重试失败、阻塞或取消任务 | 负责人 |
| `POST /tasks/{id}/assign` | `{"assignee":"账号"}` | 负责人 |
| `POST /tasks/{id}/complete` | 人工任务附 `evidence` 完成 | 负责人；不能跳过 Mikasa 实现的审批 |
| `POST /tasks/{id}/expand` | 拆解结果转实施任务，保留依赖 | 负责人 |
| `POST /tasks/{id}/publish` | 发布 Issue、草稿 PR 或正式 Review | 负责人；需额外启用发布配置 |
| `POST /tasks/{id}/reconcile` | `{"pr":123}` 核对实现的审批、CI 和合并 | 负责人 |
| `POST /provenance` | `repo`、`pr`、`head`、`provenance` | 负责人 |
| `POST /control` | `{"paused":true}` 或 `false` | 负责人 |
| `POST /webhooks/github` | HMAC SHA-256 签名校验和 delivery 去重 | GitHub webhook secret |

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

发布歧义恢复仅提供本地 CLI `resolve-publication TASK EXTERNAL_ID`，读取外部记录并核对作者、任务标记和提交，不盲目重发。`gate REPO PR` 输出当前审批政策检查结果，加 `--publish` 才发布 `mikasa/approval` commit status，仍需显式启用外部发布；`backup PATH` 使用 SQLite 一致性备份。
