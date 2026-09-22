# 与 Mikasa 聊天和切换模型

本机已联调的配置为 `config/local/hermes-cch.json`。新机器先按 [Hermes 配置](../../workers/hermes/README.md) 安装并配置。

## 终端

```sh
python3.12 -m mikasa --config config/local/hermes-cch.json chat
```

终端输入、命令分派、菜单与会话全部由未修改的 Hermes CLI 处理：

```text
记住这个项目的验收代号是蓝鲸。
/model
/model claude-opus-4-6 --session
刚才的验收代号是什么？
/model gpt-6-astra --global
/status
/new
/resume
/exit
```

使用 CCH 提供的完整模型 ID。`/model` 打开原生选择器；`--session` 只改变当前会话，`--once` 覆盖下一轮，`--global` 保存 profile 默认值，provider/reasoning 参数按 Hermes 官方语义处理。切换保留当前上下文；工程有独立原生 profile，不跟随聊天 profile 的全局偏好。

GPT/Claude 跨协议切换需要配置 [模型来源路由](CCH.md)。启动时将默认模型与 `model_routes.models` 转为 Hermes providers 和精确模型别名，凭据仅进入子进程环境。未列入配置的模型应先加入相应 models，或在原生命令中显式选择对应 provider；CLI 不执行旧适配器的前缀路由。菜单/目录结果不构成真实推理可用性承诺。

原生 `/model` 校验参数、提供商与模型目录，不额外发送推理探针。参数或路由解析失败保留旧选择；切换后的真实请求仍可能因服务状态失败，不能承诺推理失败自动回滚。此前 CCH 目录入口出现过 WAF 拒绝，本轮使用本地目录验证 SDK 路由，未重复请求该入口。真实调用诊断使用 `doctor --model MODEL_ID --probe-model`。

`/new` 使用 Hermes 自带确认流程，清空会话上下文，保留长期记忆和旧会话。固定版本尝试恢复启动时加载的默认模型，但对自定义 CCH provider 缺少配置传递，可能保留当前模型；需要确定模型时再执行 `/model ID`。`--global` 写入磁盘的选择在重启后加载。`/resume`、`/sessions`、`/memory`、`/help` 等直接沿用原生实现。初始工作目录为 profile 的持久 workspace，可直接使用机器上的其他仓库。

使用原生会话 ID 跨进程恢复：

```sh
python3.12 -m mikasa --config config/local/hermes-cch.json chat --session NATIVE_SESSION_ID
```

本地 CLI 按负责人身份执行；多人使用应走鉴权 HTTP。中文“切换为……”在原生 CLI 是普通模型消息，可靠的系统切换使用 `/model`。`chat --message` 暂保留下面的 JSON API 语义，使用旧 API 聊天 ID；原生 CLI 新建的会话不会自动登记成 HTTP chat_id。

## 飞书与微信

两端使用同一个 Hermes Gateway，直接输入原生命令；群聊中的“本会话”指本群或当前话题的共享会话。

| 命令 | 作用范围 |
| --- | --- |
| `/model` | 查看当前模型与原生选择菜单 |
| `/model claude-opus-4-6 --session` | 切换本会话，保留上下文；省略 `--session` 同样默认本会话 |
| `/model gpt-6-astra --once` | 只覆盖下一轮，之后恢复原选择 |
| `/model gpt-6-astra --global` | 保存共享 profile 默认值；其他会话已有的显式选择仍优先 |
| `/busy queue` | 本 Gateway 忙碌输入采用原生排队，之后的消息接续处理 |
| `/new` | 新建当前会话，历史与长期记忆保留；不是重启服务 |

模型切换由原生反馈说明作用范围；保存失败只报告会话选择，不声称已更改默认值。默认使用中文界面，部分上游提示仍为英文。工程入口的模型配置和 CCH 后台分组独立于聊天选择；共享 profile 的默认设置会影响共用该 profile 的参与者。

## 在聊天中做工程

直接说明仓库路径、目标和验收条件，例如：“在 `/home/mikasa/work/demo` 修复登录测试，运行相关检查并创建本地提交，不推送。”Hermes 在当前会话直接调用原生工具，使用当前聊天模型，不经过 Mikasa 任务转发器。仓库与产出保留在工作机，独立工程 CLI 也可以访问。

原生工具状态、阶段说明、长任务通知和最终结果回到原聊天。默认 `tool_progress: new`，同类工具不逐次播报，支持编辑的平台合并为一个进度气泡；保留模型中途说明和 60 秒长任务心跳。微信不支持编辑，Hermes 原生省略逐工具气泡，发送阶段说明、心跳及完整结果。后台原始通知采用 `error`，保留失败提示和原生 Agent 唤醒，成功结果由当前任务汇报；交付前读取后台进程的 wait/log 结果，避免遗漏和重复通知。阶段说明取决于模型实际生成，不保证固定条数。

`/stop` 停止当前执行，已经发生的文件写入不会回滚。同一会话忙碌时消息排队，其他会话可并发；多人同时操作同一仓库时使用原生 worktree 或独立工作目录。显示配置迁移只更新旧默认一次，保留平台覆写和后续用户偏好。

说“继续上次的任务”时，Mikasa 先使用原生 `session_search` 找到相关历史，再核对实际仓库、分支和未完成项。临时进度留在会话与仓库；稳定约定和明确要求长期记住的事实才写入 MEMORY/USER。`/new` 后可检索旧会话，精确恢复同一上下文用 `/resume` 或工程 CLI 的 `--resume SESSION_ID`。飞书与微信共享聊天历史；独立工程 CLI 只共享长期记忆，使用另一份 SessionDB，不能把共享记忆理解为自动合并两边历史。跨工程入口接手时说明仓库及原会话所在入口，以 Git、测试和原会话核对进度。

聊天与独立 CLI 使用相同 Hermes 工具机制、系统账号和依赖，原生工具、插件、MCP 与预算在各自 profile 配置。专用 VM 上普通命令审批关闭，规则文件仍遵循 Hermes 原生确认。飞书的开放参与者同样可以调用工程工具；身份约定不构成额外程序门禁。

## HTTP

按 [操作手册](OPERATIONS.md) 配置 Mikasa API token 后启动服务：

```sh
python3.12 -m mikasa --config config/local/hermes-cch.json serve
```

服务提供鉴权 JSON API，不提供自研网页聊天入口。系统命令只解析用户的直接交互消息，不扫描仓库文件或工具输出。跨机器访问需要可信 TLS 反向代理。

HTTP 和单条 `chat --message` 仍使用旧命令适配：支持中文切换、`/model ID --session`、`/model default`，真实推理探针成功后才保存选择；`/new`/`/reset` 保留当前模型，`/init` 返回 `deferred_command`。尚未开放的原生参数和命令明确拒绝。兼容层服务于既有 API 客户端，将在原生渠道覆盖账号鉴权、幂等回执与停止请求并迁移调用方后删除。

- `POST /chats`，body `{}`：建立属于认证账号的聊天。
- `GET /chats/{id}`：读取当前请求模型、revision 和原生历史的最近一页（最多 500 条消息）。
- `POST /chats/{id}/messages`：body `{"message":"切换为 gpt-5.6-luna"}`，必须提供 `Idempotency-Key`。

沿用 Bearer 鉴权；不能在 body 指定 actor、端点或凭据。回复包含 `reply`、`model`、`kind`、`revision` 和本次 `execution`；切换验证失败时 kind 为 `switch_failed`，model 仍为原值。非本人会话返回 404，同会话并发/暂停返回 409。所有已配置成员可切换自己的聊天，不具备修改网关全局路由或他人聊天的权限。

客户端必须将回复的 `chat_id` 作为下一条请求的目标；`kind=new` 返回新 ID、revision=0。若网络响应丢失，使用原会话 ID、原命令和同一幂等键重试，即可取回同一个新 ID，不会重复新建。旧会话继续可读可用；`/model default` 是恢复默认模型，`/reset` 是新建会话，两者不同。

运行中修改 CCH 后台映射仍可能使相同请求名对应不同上游。`execution.requested_model` 是请求名称，`execution.reported_model` 是 SDK 从响应中观察到的标识，不能作为底层模型身份的独立证明。

可识别的模型故障通过 `execution.error_code` 和固定提示说明；切换失败保留模型、revision 和历史，SDK 异常原文不会写入回复。同一幂等键重放仍返回第一次失败结果；修复后发起新请求重试。`default` 分组与“恢复默认模型”是不同设置，分组和连接诊断见 [CCH 手册](CCH.md)。

## 原生运行与数据迁移

消息 Gateway 默认允许不同会话并发；同一会话忙碌时使用 Hermes `queue` 模式，后续消息按原生队列接续，不要求用户反复重发。`/busy` 查看当前模式，`/busy queue` 设置排队，`/queue 内容` 显式排队，`/stop` 沿用原生停止语义。全局 `max_concurrent_sessions` 是准入上限，达到上限会拒绝新会话，并不是全局轮询队列；当前不再写死为 1，仍受 VM 资源及 CCH 限流影响。

普通群聊和话题共用各自上下文，私聊按平台和聊天分开，发送者仍使用 Hermes 元数据区分。首次从旧的按成员群会话切换时开启新的群上下文，旧历史保留。飞书使用原生输入状态和流式回复，微信保留完整回复和长任务通知；系统界面默认中文，尚未本地化的上游提示仍可能是英文。偏好迁移只执行一次，之后原生 `/busy`、显示及会话设置保留。

CLI 启动原生 CLI 子进程，HTTP 启动原生 Gateway 子进程；同一账号使用同一 profile、SessionDB 和 MEMORY/USER。`mikasa gateway --platform feishu [--platform weixin]` 使用负责人 profile，由同一个 Hermes Gateway 处理开放的飞书私聊/群聊及已绑定负责人的微信单聊；飞书不要求 @，其他机器人也可进入。会话按 Hermes 原生规则划分，长期记忆仍为 profile 共享；开放用户也能调用原生系统命令，不将其描述为每人的独立沙箱。平台配置和生效步骤见[接入手册](CONNECTIONS.md)。CLI、HTTP 和消息 Gateway 不能同时管理同一账号 profile，锁冲突会在更新配置前报错。退出会收回对应子进程，重新打开继续使用原生数据。模型凭据只从显式 CCH 来源读取到子进程环境，不复制个人认证文件。

初始化更新身份/规则、必需 skills/plugin 和生成的 CCH 配置，保留 Hermes 自己保存的默认模型、推理和显示偏好。`config.yaml` 的 YAML/JSON 都可读取，刷新写为 JSON（合法 YAML），不保留 YAML 注释；格式错误时保留原文件并阻止启动。长期记忆和原生数据库不由配置初始化覆盖。

飞书、微信中的 `/sethome` 直接使用 Hermes 原生命令，将当前聊天设为该平台默认投递目标。重启读取原生 `config.yaml` 中的完整目标，也保留 Hermes 写入的 `.env` 偏好。原生 `.env` 可以配置专用工具凭据；备份排除该文件，通过 `config.yaml` 保留投递目标，外部凭据须单独恢复。

明确要求跨会话记住非敏感事实时，Mikasa 应调用原生 memory 工具，成功后再确认。`/new` 会切换会话，不删除 MEMORY/USER；重启同样保留原生记忆。口头说“记住了”不等于已持久化，验收须同时核对工具结果、新会话回答与磁盘记录。

被删除的 CCH 来源不再留在生成的 provider/别名列表。若该来源仍是原生默认 provider，启动会保留旧配置并报错；恢复来源或修正 profile 的默认 provider 后再启动，不自动回退到其他模型。

首次打开账号 profile，会用 Hermes SessionDB 的原生接口导入旧聊天的全部普通消息；命令回执不进入模型历史。原 SQLite 保留，导入标记防止重复；冲突会阻止启动，不覆盖数据。新请求只保存摘要与 native run 引用，不复制正文。已接受但中断的请求先检查原生状态，重试使用同一幂等键，不重新推理。

不同账号 profile 的 SessionDB、MEMORY、USER 和 home 独立；消息 Gateway 的所有参与者共用主人 profile。身份由 canonical 生成 SOUL，人格 skill 原生 auto_load；聊天常驻精简交互提示，完整工程规章生成 mikasa-engineering skill 按需读取。工程任务使用方法 skills，自然语言反馈实际结果，没有强制 JSON 输出契约。

问“上次聊到哪里”时，使用 Hermes 原生历史检索；`/new` 保留旧历史，换渠道也可通过检索续上。历史访问由原生配置和文件权限决定；同 profile 的私聊和群聊并非数据隔离，回答应区分发言人、渠道和项目，不自行转述私聊内容到群聊。HTTP 的 `/init` 仍暂缓。

聊天和独立工程 CLI 共用原生 MEMORY/USER，新实例会读取已保存约定，同一实例不承诺外部记忆热刷新。聊天中的工程任务直接使用当前聊天上下文与 SessionDB；独立 CLI 的会话历史仍分开保存，切换入口时使用原生会话与历史检索能力续接。详见 [当前架构](../architecture/README.md)。

`backup DIRECTORY` 备份完整受管状态，包括原生会话、记忆与运行回执；`restore BACKUP NEW_RUNTIME` 校验后恢复到新目录。先停服，按 [备份说明](OPERATIONS.md) 重新提供外部配置与凭据；备份不上传 Git 或公开存储。

通过 HTTP 调用 `POST /chats/{id}/stop`（空 JSON、所属账号鉴权）。返回 `stop_requested` 仅说明已向 Hermes 发出取消；原生运行进入终态后才能确认停止。取消不会回滚已经写入的长期记忆或已发生的工具副作用。

HTTP/单条消息的内部等待已使用 Hermes 原生运行事件，正常运行不再高频查询状态；对外仍返回最终 JSON。断流后查询同一 run 的持久状态，不重新推理，不保证恢复中间 delta；暂停/超时仍向原生 `/stop` 请求结束。旧回执在 Gateway 重启后可直接读取持久结果，失败或已中断的 run 不会自动重新执行。边界及本地真实 Gateway 验收见 [当前架构](../architecture/README.md)。
