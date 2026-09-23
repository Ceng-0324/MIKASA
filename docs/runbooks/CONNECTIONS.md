# 平台接入

GitHub 使用 `Mikasa-0910` 独立账号，飞书使用企业自建应用机器人，微信使用 iLink 扫码身份。Hermes 负责消息连接、系统命令、会话与记忆，CCH 提供模型；Mikasa 补充配置、账号绑定和诊断。当前接入结果见[验证边界](../VALIDATION.md)。

以下命令使用本机已有的 `config/local/hermes-cch.json`；其他机器替换为自己的配置路径。合并平台字段时保留已有 CCH 设置。

## 需要提供什么

| 信息 | 获取与交付方式 |
| --- | --- |
| GitHub token | 使用 `Mikasa-0910` 创建；只告知本机文件路径或环境变量名 |
| 飞书应用 | 企业自建应用，名称 Mikasa，启用机器人；App ID / App Secret 保存在本机 |
| 负责人身份 | 可选 `owner_open_id` / `owner_user_id` 说明身份关系，不作为飞书聊天白名单；本机已有绑定 |
| 应用状态 | 是否发布、需要使用的人是否在可用范围、权限是否批准、消息事件是否订阅 |

不需要提供 GitHub/飞书密码、短信验证码、浏览器 Cookie、整份认证目录。飞书普通成员账号与机器人应用是两种身份：可额外创建普通账号管理应用，但 Hermes 接入仍需要应用凭据，不使用普通账号模拟登录。机器人已有独立名称、头像和聊天入口。

## GitHub 操作步骤

本阶段目标是独立使用 `Mikasa-0910` 账号身份，不要求先指定仓库、接受邀请或配置 webhook。通过 token 使用 GitHub API，不接管密码、邮箱或双因素认证；账号身份验证与具体操作权限分开验收。

1. 登录 `Mikasa-0910`，确认当前账号，然后打开 **Settings → Developer settings → Personal access tokens → Tokens (classic) → Generate new token (classic)**，填写用途和有限有效期。
2. 只验证账号身份时无需选仓库 scope；计划开展公开仓库协作可选 `public_repo`，需要私有仓库时选 `repo`。其他能力按实际任务补充，不要求一次勾选全部权限。若组织禁止 classic PAT，后续接入该组织时再处理其授权方式。
3. 将生成的 token 仅存入本机私密文件或密码管理器，注入 `MIKASA_GITHUB_TOKEN`。页面仅显示一次；泄露或遗失时撤销重建。只需告知本机凭据路径或变量名。
4. 使用现有配置执行下方只读探针。`repositories` 可保持 `{}`；确认 `/user` 返回 `Mikasa-0910` 即通过账号接入检查。

后续进入具体仓库任务时，再按需要授予 Mikasa 账号实际访问权限。负责人可在仓库 **Settings → Collaborators / Manage access → Add people** 邀请 `Mikasa-0910`，由该账号接受。现有工程任务入口仍需配置目标仓库和 base 分支，例如：

```json
"repositories": {
  "Ceng-0324/YOUR_REPOSITORY": {"base": "main"}
},
"github": {"token_env": "MIKASA_GITHUB_TOKEN"}
```

**为什么暂用 classic PAT**：GitHub 官方列明，fine-grained PAT 不能用于 outside/repository collaborator 场景；Mikasa 个人账号无法据此选择你个人账号拥有的仓库。classic PAT 的范围覆盖该账号在相应 scope 下可访问的仓库，不能在 token 上精确限定单仓。repositories 仅用于连接探针清单，不限制原生工程工具；实际范围由 token 与账号的 GitHub 权限决定。独立账号应只加入需要的仓库。GitHub App installation token 适合长期集成，但发布身份会成为 App bot，也不兼容当前 `/user` 账号校验，不能直接替换。

执行只读检查：

```sh
python3.12 -m mikasa --config config/local/hermes-cch.json connections github
python3.12 -m mikasa --config config/local/hermes-cch.json connections github --probe
```

联网探针只 GET `/user`，有已配置仓库时再检查仓库、base 分支、Issue/PR 列表，不创建 Issue、PR、Review 或 push。无仓库时账号认证成功即 `connection=passed`，`repository_access=not_checked`。`account_push_role=true` 只说明账号角色，不证明 token 写权限；正式写入与 CI Checks 权限仍需分别验收。账号接通不代表所有 GitHub 操作或聊天工程工具均已实现。

原生工程按交互授权使用 gh/Git，不需要 GitHub webhook。旧自动审查服务及 HTTP 入口已删除；不配置 `/webhooks/github`。本轮不单独安排正式 Review 流程验收。

## 国内飞书操作步骤

1. 使用能管理目标企业应用的账号登录 [飞书开发者后台](https://open.feishu.cn/app)，选择目标企业，**创建企业自建应用**，填写 Mikasa 名称、描述与头像。若没有创建权限，让企业管理员授予开发者权限或创建应用并将你加入应用协作者。
2. 在应用的 **添加应用能力 → 机器人** 启用机器人。这是 Hermes 使用的独立飞书身份，无需先注册普通成员号。不要选择群聊中的自定义 Webhook 机器人；Hermes 此入口需要企业自建应用的 App ID / App Secret 和长连接事件能力。
3. 在 **凭证与基础信息** 找到 `App ID`（通常 `cli_...`）和 `App Secret`，存入本机 `MIKASA_FEISHU_APP_ID`、`MIKASA_FEISHU_APP_SECRET`。不要把它们写入 Git JSON 或聊天消息。
4. 在 **权限管理** 保留 `im:message.p2p_msg:readonly`（单聊读取）和 `im:message:send_as_bot`（发送回复）；群聊补充 `im:message.group_at_msg:readonly`（接收群内 @ 机器人的消息）。要让普通未 @ 的群消息也送达，申请 `im:message.group_msg`（获取群组中所有消息，敏感权限，以控制台审批为准）。项目取消 @ 限制不等于飞书自动投递全部消息。Hermes 查询显示名、引用和附件所需额外权限按实际使用补充。
5. 在 **版本管理与发布** 创建版本，把应用可用范围扩大到需要与 Mikasa 交互的成员或部门，提交并完成企业审批/发布。原先只选负责人会限制其他人的使用。修改权限或可用范围后按控制台要求重新发布。
6. 可选 `feishu.owner_open_id` 填负责人在 Mikasa 应用中的 `ou_...`，不是机器人 ID；用于身份说明，不限制准入。如已有 User ID 权限，可补同一人的 `owner_user_id`；本机已有绑定无需重复配置。
7. 检查配置中的 `feishu` 段应类似下面这样，App ID 和 App Secret 仍只通过环境变量提供：

```json
"feishu": {
  "domain": "feishu",
  "owner_open_id": "ou_YOUR_OPEN_ID",
  "app_id_env": "MIKASA_FEISHU_APP_ID",
  "app_secret_env": "MIKASA_FEISHU_APP_SECRET"
}
```

8. 加载本机环境后执行以下检查。`--probe` 复用 Hermes 官方机器人信息探针，获取 tenant token 并读取机器人信息，不建立长连接、不发送消息，也不调用 CCH。诊断的 `access` 字段报告代码生成的准入策略，不证明旧进程已加载新策略。

```sh
python3.12 -m mikasa --config config/local/hermes-cch.json connections feishu
python3.12 -m mikasa --config config/local/hermes-cch.json connections feishu --probe
```

9. 准备事件订阅：在 **事件与回调 → 事件配置** 选择 **使用长连接接收事件**。该方式不需要公网 URL、Encrypt Key 或 Verification Token。先检查 CCH 已配置；CLI 可以与 Gateway 并存，若已有 Gateway 正在运行则先停止它再重启加载新代码，然后执行 `python3.12 -m mikasa --config config/local/hermes-cch.json gateway --platform feishu`。微信绑定完成后改为同一条 Gateway 命令追加 `--platform weixin`；不要启动第二个 Gateway。代码更新后需重启现有 Gateway 才会加载新策略。
10. 控制台若要求先建立长连接，等待启动输出确认连接后，再保存订阅方式，添加 **接收消息 v2.0** 事件 `im.message.receive_v1`，按控制台提示发布新版本。无需订阅 Hermes 支持的所有事件。
11. 在目标飞书群打开 **群设置 → 群机器人 → 添加机器人**，搜索 Mikasa 并添加。若搜索不到或不能添加，检查应用是否发布、操作者是否在应用可用范围，以及群管理员的添加限制；项目的消息过滤无法影响飞书客户端的添加列表。
12. 在私聊和群内分别发送 `/help`、普通文字、`/model 完整模型ID` 和 `/new`；再用另一成员账号验证。群内先 @ Mikasa，再测试未 @ 消息，区分事件权限与本地策略。只有真实收到回复才算完成平台验收；同时检查身份/skills 加载与记忆保留。

飞书现采用 Hermes 原生开放准入：所有用户、群聊与其他机器人均可进入，群聊不要求 @。通过 `FEISHU_ALLOW_ALL_USERS=true`、`FEISHU_GROUP_POLICY=open`、`FEISHU_ALLOW_BOTS=all`、`FEISHU_REQUIRE_MENTION=false` 实现，无成员或群白名单；Hermes 自身消息回环过滤、消息去重与机器人循环保护保留。只对飞书开放，微信仍使用扫码负责人的单聊绑定。

私聊按平台和聊天区分；普通群及话题内共享上下文，发送者仍使用 Hermes 元数据识别。同一 Gateway 共用负责人 profile 的 MEMORY/USER、SessionDB、身份与 skills，具体会话仍按平台、聊天和话题标识隔离，并非每人的私有记忆空间。开放用户可调用原生系统命令与工程工具，部分操作影响共享 profile 和工作机。不同会话并发，同会话忙碌时排队；工程进度与结果直接回复原会话，详细语义见[聊天手册](CHAT.md)。

CLI 与消息 Gateway 可以使用同一负责人 profile 并存。启动时会短暂锁住 profile 以完成身份和配置刷新；运行期由 Hermes 的会话 lease 与 Gateway runtime 锁管理并发，重复启动第二个 Gateway 会被原生拒绝。Ctrl-C 停止前台；启动失败需处理错误后重启，不覆盖会话或记忆。

已知限制：原生 `/sethome` 会保存默认投递设置并生成 profile `.env`，与当前禁止额外环境注入的启动检查冲突。当前验收不依赖默认投递；遇到此情况先核对文件字段并保留原设置，不能删除未知凭据或直接放开任意 `.env`。macOS 上过长的 profile 路径还会使 Hermes 可选 liveness socket 无法创建，消息长连接仍可工作；VM 使用短路径后复验存活检测。

## 微信扫码绑定

微信使用固定 Hermes 的原生 iLink 适配器。先在本机执行：

```sh
python3.12 -m mikasa --config config/local/hermes-cch.json weixin-login
python3.12 -m mikasa --config config/local/hermes-cch.json connections weixin
```

用负责人本人微信扫描终端二维码并在手机确认。扫码得到独立 iLink 机器人身份，不接管个人微信账号；当前支持主人私聊，通常无法加入普通微信群，放开本地策略不能让 iLink 投递未支持的群消息。登录不调用模型、不收发消息，也不修改正在运行的飞书 profile。绑定来自扫码返回的用户 ID，无需手工抄写；不要分享登录二维码。

主人已确认本机绑定的手机微信账号属于 `Ceng-0324`（Shawn / Ceng）。准备原生 profile 时，从经校验的本机绑定提取 `user_id` 注入主人身份关系，以 Hermes 微信发送者元数据匹配；不将机器人 `account_id` 当作主人，也不向身份提示传入 token。没有绑定时不注入微信身份，绑定错误时拒绝更新；重新绑定后重启 Gateway 使新的身份映射生效。实际微信标识仅留在本机运行数据，不写入公开身份文档。

完整绑定以 0600 保存到配置 runtime 下的 `credentials/weixin.json`；登录取消、超时或返回缺字段时保留旧文件。该目录被 Git 忽略且不属于受管状态备份范围，迁到 VM 时单独安全转移或重新扫码。登录临时 home 自动清理，凭据不写入会话、记忆或生成的 Gateway 配置。`connections weixin` 只检查本地绑定，不证明 token 尚有效；微信不提供本项目使用的只读认证探针，因此拒绝 `--probe`，避免探针消费真实消息。

扫码成功后必须启用消息平台。若飞书 Gateway 已运行，先在其终端 Ctrl-C 正常停止；保持原有飞书凭据环境，再用同一 profile 启动双平台：

```sh
python3.12 -m mikasa --config config/local/hermes-cch.json gateway --platform feishu --platform weixin
```

不要另开一个微信进程争用 profile。`weixin-login` 不会自动修改已经运行的 Gateway；`connections weixin` 的 `ready` 也只说明本地绑定可读取。启动后用扫码账号进入微信机器人，发送 `/help` 和普通文字，再验证 `/model`、`/new` 与记忆。原生 `connected` 表示适配器已启动，真实入站、CCH 回执、发送结果和手机收到回复需要分别确认。

## 本机凭据存放

已有可用本机配置时在原配置中合并上述字段，保留 CCH 设置，不覆盖成默认示例。可将 [环境模板](../../config/examples/platforms.env.example) 复制为 `config/local/platforms.env`，设置 `chmod 600 config/local/platforms.env` 后，用本机编辑器填写值。该目录已被 Git 忽略；不要把整个文件内容发到聊天。

`app_id_env` / `app_secret_env` 填变量名，实际值放在 `platforms.env`，例如 `MIKASA_FEISHU_APP_ID='cli_...'` 和 `MIKASA_FEISHU_APP_SECRET='实际密钥'`。已有凭据和绑定保留在原本机文件中，不重复复制或覆盖；公开文档只使用占位符。

在你自己控制的 shell 中加载自己编写的文件：

```sh
set -a
. ./config/local/platforms.env
set +a
```

文件按 shell 赋值语法填写，值用单引号包裹，不启用 `set -x`，不在带密钥的命令行中直接赋值。Mikasa 不自动加载这个文件，也不会复制 Codex/Claude 认证文件。配置只保存环境变量名；飞书子进程只得到模型与飞书凭据，不继承 GitHub token。诊断不会打印 secret 或原始 SDK 响应。

## 依据与验证范围

2026-09-21 核对固定 Hermes revision 的 `plugins/platforms/feishu/adapter.py`、`gateway/config.py`、`gateway/authz_mixin.py`，以及以下官方文档：

- [GitHub PAT 与 fine-grained 限制](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens)
- [飞书接收消息事件与权限](https://open.feishu.cn/document/server-docs/im-v1/message/events/receive)
- [飞书回复消息与权限](https://open.feishu.cn/document/server-docs/im-v1/message/reply)
- [获取指定用户 Open ID](https://open.feishu.cn/document/uAjLw4CM/ugTN1YjL4UTN24CO1UjN/trouble-shooting/how-to-obtain-openid)
- [通过手机号或邮箱获取用户 ID](https://open.feishu.cn/document/server-docs/contact-v3/user/batch_get_id)

探针认证成功不能证明应用已发布、负责人绑定正确或消息往返成功；模拟测试不能替代真实 GitHub/飞书验收。当前结果见 [验证记录](../VALIDATION.md)。
