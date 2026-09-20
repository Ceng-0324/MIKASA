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

GPT/Claude 跨协议切换需要配置 [模型来源路由](CCH.md)，本机已接入现有 Codex/CCH 和 Claude Code/CCH 配置。裸 `/model` 与 `/models` 显示本地配置候选；菜单不是 CCH 实时目录。仍可直接输入未列入菜单但符合配置前缀的完整模型 ID。Hermes 官方组件解析命令与参数，Mikasa 验证权限、连接和持久化范围，无须模型理解命令。

支持 `/model ID --session`；全局切换、单轮覆盖、provider/reasoning 和目录刷新参数尚未开放，会明确拒绝。`/help` 显示已接入的命令，`/version`（别名 `/v`）执行 Hermes 官方版本查询。命令解析不调用模型；原生 Gateway 启动时加载已授权的模型凭据，实际切换验证会调用目标模型。

`/new`（别名 `/reset`）创建新聊天并保留当前模型，旧聊天记录保留，可通过旧 ID 恢复。CLI 自动改用新 ID，HTTP 客户端需跟随响应中的 chat_id，下一条消息从空上下文开始。`/init` 会生成或修改仓库规则，当前返回 `deferred_command`；它随最后的聊天工程任务与试点接入，当前不执行文件写入。

终端会打印会话 ID，可跨进程继续：

```sh
python3.12 -m mikasa --config config/local/hermes-cch.json chat --session CHAT_ID
python3.12 -m mikasa --config config/local/hermes-cch.json chat --session CHAT_ID --message '当前模型'
```

本地 CLI 使用当前受信任操作系统账号，按负责人身份执行；多人使用应走鉴权 HTTP。

## HTTP

按 [操作手册](OPERATIONS.md) 配置 Mikasa API token 后启动服务：

```sh
python3.12 -m mikasa --config config/local/hermes-cch.json serve
```

服务提供鉴权 JSON API，不提供自研网页聊天入口。系统命令只解析用户的直接交互消息，不扫描仓库文件或工具输出。跨机器访问需要可信 TLS 反向代理。

- `POST /chats`，body `{}`：建立属于认证账号的聊天。
- `GET /chats/{id}`：读取当前请求模型、revision 和原生历史的最近一页（最多 500 条消息）。
- `POST /chats/{id}/messages`：body `{"message":"切换为 gpt-5.6-luna"}`，必须提供 `Idempotency-Key`。

沿用 Bearer 鉴权；不能在 body 指定 actor、端点或凭据。回复包含 `reply`、`model`、`kind`、`revision` 和本次 `execution`；切换验证失败时 kind 为 `switch_failed`，model 仍为原值。非本人会话返回 404，同会话并发/暂停返回 409。所有已配置成员可切换自己的聊天，不具备修改网关全局路由或他人聊天的权限。

客户端必须将回复的 `chat_id` 作为下一条请求的目标；`kind=new` 返回新 ID、revision=0。若网络响应丢失，使用原会话 ID、原命令和同一幂等键重试，即可取回同一个新 ID，不会重复新建。旧会话继续可读可用；`/model default` 是恢复默认模型，`/reset` 是新建会话，两者不同。

运行中修改 CCH 后台映射仍可能使相同请求名对应不同上游。`execution.requested_model` 是请求名称，`execution.reported_model` 是 SDK 从响应中观察到的标识，不能作为底层模型身份的独立证明。

可识别的模型故障通过 `execution.error_code` 和固定提示说明；切换失败保留模型、revision 和历史，SDK 异常原文不会写入回复。同一幂等键重放仍返回第一次失败结果；修复后发起新请求重试。`default` 分组与“恢复默认模型”是不同设置，分组和连接诊断见 [CCH 手册](CCH.md)。

## 原生运行与数据迁移

CLI 生命周期与 HTTP 服务共同管理原生 Gateway，每个账号使用独立 profile。不要同时以 CLI 和 HTTP 管理同一账号 profile；锁冲突会明确报错。关闭入口会关闭子 Gateway，重新打开继续使用原生会话与记忆。模型凭据只从显式 CCH 来源读取到子进程环境，不复制个人认证文件。

首次打开账号 profile，会用 Hermes SessionDB 的原生接口导入旧聊天的全部普通消息；命令回执不进入模型历史。原 SQLite 保留，导入标记防止重复；冲突会阻止启动，不覆盖数据。新请求只保存摘要与 native run 引用，不复制正文。已接受但中断的请求先检查原生状态，重试使用同一幂等键，不重新推理。

`/new` 清空会话上下文，保留同账号长期记忆。不同账号的 SessionDB、MEMORY、USER 和 home 独立。身份由 canonical 生成 SOUL，工程规则经官方插件注入。人格 skill 通过原生 `skills.auto_load` 必需加载，缺失时拒绝启动；工程 skills 由原生索引与 skill_view 加载。聊天目前仅授权原生 memory、skills_list、skill_view；skill_manage 和仓库/终端能力被阻止，`/init` 随聊天工程任务在最后接入。

原有 `backup PATH` 只备份业务 SQLite，不能作为原生会话/记忆的完整恢复点。维护前停服并保留整个受限 runtime；不把它上传到 Git 或公开存储。

通过 HTTP 调用 `POST /chats/{id}/stop`（空 JSON、所属账号鉴权）。返回 `stop_requested` 仅说明已向 Hermes 发出取消；原生运行进入终态后才能确认停止。取消不会回滚已经写入的长期记忆或已发生的工具副作用。
