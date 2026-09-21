# GitHub 与飞书接入

本阶段连接 `Mikasa-0910` GitHub 账号及国内飞书的 Mikasa 应用机器人。Hermes 负责飞书长连接、消息处理、系统命令、会话与记忆，CCH 继续提供模型；Mikasa 只补配置、负责人身份绑定和诊断。真实平台验收需要下面的外部信息，当前不代表已上线。

以下命令使用本机已有的 `config/local/hermes-cch.json`；其他机器替换为自己的配置路径。合并平台字段时保留已有 CCH 设置。

## 需要提供什么

| 信息 | 获取与交付方式 |
| --- | --- |
| GitHub token | 使用 `Mikasa-0910` 创建；只告知本机文件路径或环境变量名 |
| 飞书应用 | 企业自建应用，名称 Mikasa，启用机器人；App ID / App Secret 保存在本机 |
| 负责人身份 | 曾俊轩在上述应用中的 `open_id`；如启用 User ID 权限，再提供同一人的 `user_id` |
| 应用状态 | 是否发布、负责人是否在可用范围、权限是否批准、消息事件是否订阅 |

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
"github": {"token_env": "MIKASA_GITHUB_TOKEN", "publish_enabled": false}
```

**为什么暂用 classic PAT**：GitHub 官方列明，fine-grained PAT 不能用于 outside/repository collaborator 场景；Mikasa 个人账号无法据此选择你个人账号拥有的仓库。classic PAT 的范围覆盖该账号在相应 scope 下可访问的仓库，不能在 token 上精确限定单仓。Mikasa 的仓库配置只约束自身请求，不收窄 token 的 GitHub 权限。独立账号应只加入需要的仓库。GitHub App installation token 适合长期集成，但发布身份会成为 App bot，也不兼容当前 `/user` 账号校验，不能直接替换。

执行只读检查：

```sh
python3.12 -m mikasa --config config/local/hermes-cch.json connections github
python3.12 -m mikasa --config config/local/hermes-cch.json connections github --probe
```

联网探针只 GET `/user`，有已配置仓库时再检查仓库、base 分支、Issue/PR 列表，不创建 Issue、PR、Review 或 push。无仓库时账号认证成功即 `connection=passed`，`repository_access=not_checked`。`account_push_role=true` 只说明账号角色，不证明 token 写权限；正式写入与 CI Checks 权限仍需分别验收。账号接通不代表所有 GitHub 操作或聊天工程工具均已实现。

### GitHub Webhook 留到公网入口就绪

只读连接不需要 webhook。VM/TLS 就绪后，由负责人进入仓库 **Settings → Webhooks → Add webhook**：URL 为部署域名的 `/webhooks/github`，Content type 选 `application/json`，启用 SSL 校验，Secret 与服务的 `MIKASA_GITHUB_WEBHOOK_SECRET` 一致，选择 `Pull requests` 事件。服务另需现有 `server.tokens` API 凭据。先用 ping / Recent Deliveries 核对签名与送达，再做 PR 事件验收。

本阶段 `auto_review=false`、`publish_enabled=false`；收到事件不表示会自动审查或发布。正式 Review 在你指定可写测试 PR 并授权该次发布后验收，不把新建真实 PR 当作连接探针。

## 国内飞书操作步骤

1. 使用能管理目标企业应用的账号登录 [飞书开发者后台](https://open.feishu.cn/app)，选择目标企业，**创建企业自建应用**，填写 Mikasa 名称、描述与头像。若没有创建权限，让企业管理员授予开发者权限或创建应用并将你加入应用协作者。
2. 在应用的 **添加应用能力 → 机器人** 启用机器人。这是 Hermes 使用的独立飞书身份，无需先注册普通成员号。
3. 在 **凭证与基础信息** 找到 `App ID`（通常 `cli_...`）和 `App Secret`，存入本机 `MIKASA_FEISHU_APP_ID`、`MIKASA_FEISHU_APP_SECRET`。不要把它们写入 Git JSON 或聊天消息。
4. 在 **权限管理** 申请 `im:message.p2p_msg:readonly`（读取用户发给机器人的单聊消息）和 `im:message:send_as_bot`（以应用身份发消息）。这是首阶段文字单聊所需权限；关闭输入状态和流式预览，不为群聊、通讯录、云文档、会议或附件预先授予额外权限。Hermes 可尝试查询显示名、引用原消息等，缺少额外权限时这些附加信息可能不可用，真实验收再按实际使用补充。
5. 在 **版本管理与发布** 创建版本，把应用可用范围先设为负责人曾俊轩，提交并完成企业审批/发布。权限修改可能需要重新发布。机器人存在但未发布或不在可用范围，仍无法正常单聊。
6. 获取**负责人的 Open ID**：打开 [API 调试台](https://open.feishu.cn/api-explorer)，选择刚创建的 Mikasa 应用，找到 **发送消息** 接口，在 ID 类型选择 `open_id`，点击 **快速复制 open_id**，搜索曾俊轩并复制成员 ID。这里只使用选择器，**不要点击发送请求**。不同应用的 Open ID 不同，不能拿其他应用的 ID 或机器人自己的 ID 代替。
7. 如果调试台没有用户选择器，可在同一应用申请 `contact:user.id:readonly`，将通讯录数据范围限制到本人，在 **通过手机号或邮箱获取用户 ID** 接口中用 `tenant_access_token`、`user_id_type=open_id` 查询自己。返回 `data.user_list[].user_id` 此时实际是 `ou_...`。手机号/邮箱仅在飞书平台输入，不需要发给我；这条替代路径所需的额外权限并非单聊的必需项。
8. 在本机配置添加下列 `feishu` 段，替换你的真实 Open ID。默认不申请 `contact:user.employee_id:readonly`。若应用已有该权限，Hermes 优先采用事件中的租户 User ID，需要再通过同一成员选择器或查询 API 的 `user_id_type=user_id` 获取同一人的 ID，填入可选 `owner_user_id`；不要填其他人的 ID。

```json
"feishu": {
  "domain": "feishu",
  "owner_open_id": "ou_REPLACE_WITH_YOUR_ID",
  "app_id_env": "MIKASA_FEISHU_APP_ID",
  "app_secret_env": "MIKASA_FEISHU_APP_SECRET"
}
```

9. 加载本机环境后执行以下检查。`--probe` 复用 Hermes 官方机器人信息探针，获取 tenant token 并读取机器人信息，不建立长连接、不发送消息，也不调用 CCH。

```sh
python3.12 -m mikasa --config config/local/hermes-cch.json connections feishu
python3.12 -m mikasa --config config/local/hermes-cch.json connections feishu --probe
```

10. 准备事件订阅：在 **事件与回调 → 事件配置** 选择 **使用长连接接收事件**。该方式不需要公网 URL、Encrypt Key 或 Verification Token。先检查 CCH 已配置，关闭同账号正在运行的 CLI/API Gateway，然后在终端执行 `python3.12 -m mikasa --config config/local/hermes-cch.json feishu`，保持前台运行；不要让两个进程使用同一应用。
11. 控制台若要求先建立长连接，等待启动输出确认连接后，再保存订阅方式，添加 **接收消息 v2.0** 事件 `im.message.receive_v1`，按控制台提示发布新版本。无需订阅 Hermes 支持的所有事件。
12. 用负责人本人账号在飞书打开机器人，主动发送一条普通文字消息，再测试 `/help`、`/model 完整模型ID` 和 `/new`。这一步才验证真实事件、CCH 推理、机器人回复和系统命令；同时检查人格/skills 加载证据和原生记忆跨会话保留。其他账号和群聊当前不会进入负责人 profile。

`feishu` 启动意味着允许 Hermes 接收并回复已绑定负责人的消息。这里只开放模型的 memory 与只读 skills；**原生系统命令是受信任控制面，并非沙箱**，不要将负责人身份授予陌生用户。当前不接聊天工程任务、不主动群发。CLI、HTTP Gateway 与飞书共享同一负责人 profile 和 MEMORY/USER，但聊天会话各自由 Hermes 管理，三个进程互斥，不能同时启动。Ctrl-C 停止前台；启动失败需处理错误后重启，不自动修改身份或放宽准入。

## 本机凭据存放

已有可用本机配置时在原配置中合并上述字段，保留 CCH 设置，不覆盖成默认示例。可将 [环境模板](../../config/examples/platforms.env.example) 复制为 `config/local/platforms.env`，设置 `chmod 600 config/local/platforms.env` 后，用本机编辑器填写值。该目录已被 Git 忽略；不要把整个文件内容发到聊天。

在你自己控制的 shell 中加载自己编写的文件：

```sh
set -a
. ./config/local/platforms.env
set +a
```

文件按 shell 赋值语法填写，值用单引号包裹，不启用 `set -x`，不在带密钥的命令行中直接赋值。Mikasa 不自动加载这个文件，也不会复制 Codex/Claude 认证文件。配置只保存环境变量名；飞书子进程只得到模型与飞书凭据，不继承 GitHub token。诊断不会打印 secret 或原始 SDK 响应。

准备好后告知：**配置文件路径、GitHub token 的本机路径或变量名、飞书凭据来源、飞书 Open ID、应用发布/事件订阅状态**。GitHub 仓库与分支在后续具体任务时确定，不是本次账号接入的前置条件。不用粘贴 token / App Secret。完成真实接入后再推进 VM，最后接聊天工程任务与 FluxCore。

## 依据与验证范围

2026-09-21 核对固定 Hermes revision 的 `plugins/platforms/feishu/adapter.py`、`gateway/config.py`、`gateway/authz_mixin.py`，以及以下官方文档：

- [GitHub PAT 与 fine-grained 限制](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens)
- [飞书接收消息事件与权限](https://open.feishu.cn/document/server-docs/im-v1/message/events/receive)
- [飞书回复消息与权限](https://open.feishu.cn/document/server-docs/im-v1/message/reply)
- [获取指定用户 Open ID](https://open.feishu.cn/document/uAjLw4CM/ugTN1YjL4UTN24CO1UjN/trouble-shooting/how-to-obtain-openid)
- [通过手机号或邮箱获取用户 ID](https://open.feishu.cn/document/server-docs/contact-v3/user/batch_get_id)

探针认证成功不能证明应用已发布、负责人绑定正确或消息往返成功；模拟测试不能替代真实 GitHub/飞书验收。当前结果见 [验证记录](../VALIDATION.md)。
