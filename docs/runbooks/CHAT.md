# 与 Mikasa 聊天和切换模型

本机已联调的配置为 `config/local/hermes-cch.json`。新机器先按 [Hermes 配置](../../workers/hermes/README.md) 安装并配置。

## 终端

```sh
python3.12 -m mikasa --config config/local/hermes-cch.json chat
```

进入后可以直接说：

```text
记住这个项目的验收代号是蓝鲸。
/model
/model claude-opus-4-6
刚才的验收代号是什么？
/model gpt-6-astra
当前模型
恢复默认模型
/exit
```

切换前会检查连接，成功后对当前聊天生效；保留聊天记录，其他会话及工程任务不受影响。模型名称使用 CCH 支持的完整 ID，不知道名称时查 CCH 配置；`/models` 提供使用说明，不伪造可用模型列表。首次切换会额外消耗一次小型验证调用。

GPT/Claude 跨协议切换需要配置 [模型来源路由](CCH.md)，本机已接入现有 Codex/CCH 和 Claude Code/CCH 配置。裸 `/model` 与 `/models` 显示本地配置候选，网页可以点击候选按钮；菜单不是 CCH 实时目录。仍可直接输入未列入菜单但符合配置前缀的完整模型 ID。Hermes 官方组件解析命令与参数，Mikasa 验证权限、连接和持久化范围，无须模型理解命令。

支持 `/model ID --session`；全局切换、单轮覆盖、provider/reasoning 和目录刷新参数尚未开放，会明确拒绝。`/help` 显示已接入的命令，`/version`（别名 `/v`）执行 Hermes 官方版本查询。查询和命令解析不调用模型、不读取模型密钥；实际切换验证会调用目标模型。

`/new`（别名 `/reset`）创建新聊天并保留当前模型，旧聊天记录保留，可通过旧 ID 恢复。网页和 CLI 自动改用新 ID，下一条消息从空上下文开始。`/init` 会生成或修改仓库规则，当前返回 `deferred_command`；它随最后的聊天工程任务与试点接入，当前不执行文件写入。

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

客户端必须将回复的 `chat_id` 作为下一条请求的目标；`kind=new` 返回新 ID、revision=0。若网络响应丢失，使用原会话 ID、原命令和同一幂等键重试，即可取回同一个新 ID，不会重复新建。旧会话继续可读可用；`/model default` 是恢复默认模型，`/reset` 是新建会话，两者不同。

运行中修改 CCH 后台映射仍可能使相同请求名对应不同上游。`execution.requested_model` 是请求名称，`execution.reported_model` 是 SDK 从响应中观察到的标识，不能作为底层模型身份的独立证明。

可识别的模型故障通过 `execution.error_code` 和固定提示说明；切换失败保留模型、revision 和历史，SDK 异常原文不会写入回复。同一幂等键重放仍返回第一次失败结果；修复后发起新请求重试。`default` 分组与“恢复默认模型”是不同设置，分组和连接诊断见 [CCH 手册](CCH.md)。
