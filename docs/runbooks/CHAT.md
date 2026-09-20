# 与 Mikasa 聊天和切换模型

本机已联调的配置为 `config/local/hermes-cch.json`。新机器先按 [Hermes 配置](../../workers/hermes/README.md) 安装并配置。

## 终端

```sh
python3.12 -m mikasa --config config/local/hermes-cch.json chat
```

进入后可以直接说：

```text
记住这个项目的验收代号是蓝鲸。
切换为 gpt-5.6-luna
刚才的验收代号是什么？
当前模型
恢复默认模型
/exit
```

切换前会检查连接，成功后对当前聊天生效；保留聊天记录，其他会话及工程任务不受影响。模型名称使用 CCH 支持的完整 ID，不知道名称时查 CCH 配置；`/models` 提供使用说明，不伪造可用模型列表。首次切换会额外消耗一次小型验证调用。

终端会打印会话 ID，可跨进程继续：

```sh
python3.12 -m mikasa --config config/local/hermes-cch.json chat --session CHAT_ID
python3.12 -m mikasa --config config/local/hermes-cch.json chat --session CHAT_ID --message '当前模型'
```

本地 CLI 使用当前受信任操作系统账号，按负责人身份执行；多人使用应走鉴权 HTTP。

## 网页

按 [操作手册](OPERATIONS.md) 在环境中设置配置所引用的 Mikasa API token（默认 `MIKASA_OWNER_API_TOKEN`，至少 32 字符），然后运行：

```sh
python3.12 -m mikasa --config config/local/hermes-cch.json serve
```

在浏览器打开 `http://127.0.0.1:8765/chat`，输入 **Mikasa API token**，点击“新建聊天”。不要在此输入 CCH 的模型密钥。想继续已有聊天，填会话 ID 后点击“继续聊天”。访问令牌只留在当前页面，刷新需重新输入；聊天记录保存在服务端 runtime。

页面支持自然语言切换、发送失败后的幂等重试和聊天恢复。模型请求可能需要几十秒，同一聊天处理期间等待回复后再发下一条。跨机器访问需要可信 TLS 反向代理。

## HTTP

- `POST /chats`，body `{}`：建立属于认证账号的聊天。
- `GET /chats/{id}`：读取当前请求模型、revision 和最近 40 轮记录。
- `POST /chats/{id}/messages`：body `{"message":"切换为 gpt-5.6-luna"}`，必须提供 `Idempotency-Key`。

沿用 Bearer 鉴权；不能在 body 指定 actor、端点或凭据。回复包含 `reply`、`model`、`kind`、`revision` 和本次 `execution`；切换验证失败时 kind 为 `switch_failed`，model 仍为原值。非本人会话返回 404，同会话并发/暂停返回 409。所有已配置成员可切换自己的聊天，不具备修改网关全局路由或他人聊天的权限。

运行中修改 CCH 后台映射仍可能使相同请求名对应不同上游。`execution.requested_model` 是请求名称，`execution.reported_model` 是 SDK 从响应中观察到的标识，不能作为底层模型身份的独立证明。
