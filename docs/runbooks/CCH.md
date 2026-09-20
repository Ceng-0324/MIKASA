# CCH 模型配置与诊断

Mikasa 读取模型配置，Hermes 官方 harness 负责模型调用，CCH 负责上游选择、模型重写和网关故障切换。Mikasa 不新增路由网关，也不修改个人 Codex 配置。上游调研与部署证据边界见 [路由决策](../decisions/0002-chat-model-switching.md)。

## 配置和连接检查

按 [Hermes 配置](../../workers/hermes/README.md) 选择 `codex`、`claude` 或 `environment`。环境来源只读取 `worker.env_allowlist` 内的模型变量；Codex 来源按 env_key、内嵌 bearer、邻近 auth.json 的顺序只读取得 API key；Claude 来源只读选定 settings.json 中的 CCH 端点和 token/API key，不复制认证文件。

```sh
python3.12 -m mikasa --config config/local/hermes-cch.json doctor
python3.12 -m mikasa --config config/local/hermes-cch.json doctor --probe-model
python3.12 -m mikasa --config config/local/hermes-cch.json doctor --model claude-opus-4-6 --probe-model
```

第一条只检查本地条件，`connection=not_checked`。第二条通过当前 worker 发送一次无工具聊天请求，会消耗一次模型调用；成功为 `connection=passed`，失败或配置不完整时退出码为 1。探针不创建任务、聊天或改动模型选择；Hermes 自身仍可能写专用 home 日志。配置、进程、协议或输出契约失败都不能报告连接通过。

输出的 `requested_model` 是请求名，`reported_model` 是响应标识，`model_match` 为 same/different/unreported。即使 same，也不能独立证明供应商实际底层模型。`backend` 明确实际使用的 worker；夹具 worker 通过不算真实 CCH 联调。默认 doctor 的退出码仍只表示命令执行成功，模型配置状态读取 `model.configuration`。

## /model 跨 GPT 与 Claude 切换

终端 `/model` 直接由 Hermes CLI 执行；HTTP 和 `chat --message` 暂保留旧 API 命令适配。两者均可使用 `/model gpt-6-astra` 或 `/model claude-opus-4-6`，保留上下文。原生 CLI 支持 session/once/global、provider/reasoning 等官方参数；原生选择器与目录校验不额外发送推理探针，实际可用性由请求验证。旧 API 只开放 session 范围，中文“切换为 完整模型ID”仍由适配器识别，真实推理验证成功后保存新选择。具体差异见 [聊天手册](CHAT.md)。

在 worker 中添加以下配置，模型名为配置示例，可按 CCH 实际提供的名称调整：

```json
{
  "model_source": {"type": "codex"},
  "model_routes": [
    {
      "models": ["gpt-6-astra", "gpt-5.6-luna"],
      "prefixes": ["gpt-", "o1", "o3", "o4"],
      "model_source": {"type": "codex"}
    },
    {
      "models": ["claude-opus-4-6"],
      "prefixes": ["claude-", "anthropic/claude-"],
      "model_source": {"type": "claude", "config_path": "~/.claude/settings.json"}
    }
  ]
}
```

Mikasa 配置匹配优先级：完整 models 匹配 → 最长 prefixes 匹配 → worker 默认来源。同一完整模型或前缀不允许重复配置。工程与旧 API 使用这套选择规则；原生 CLI 将默认模型和显式 models 生成精确别名，由 Hermes 选择相应 provider。新模型推荐加入对应 models；未列出的模型需显式选择原生 provider，CLI 不复刻前缀路由。候选不是 CCH 完整目录。`model_source` 只存来源引用，拒绝内嵌密钥；不同路由可以引用不同受信任配置文件。API 请求体、聊天文本和模型回复不能指定配置路径或任意端点。

原生 profile 启动时读取已配置来源，将端点、协议、模型别名和 key_env 写入 Hermes 配置；实际 Key 仅在子进程环境中。`/model` 由 Hermes 同时解析目标模型、provider、协议和 Key。`--global` 写入原生 profile，下次初始化保留该选择；工程默认值与旧 API 新会话默认值仍来自 Mikasa worker 配置。配置或认证变更后需重启对应 CLI/Gateway；不迁移正在生成的请求。来源缺失或损坏时直接失败，不借用其他来源凭据。

固定 CCH 源码按协议筛选供应商：Responses → codex，Messages → claude/claude-auth，Chat Completions → openai-compatible。Hermes 已原生支持这些 transport，因此切换 Claude 时采用 Messages，GPT 按 Codex 配置采用 Responses；不自研协议转换代理，不把所有名字塞进同一个 Responses 端点。

Hermes 的交互命令不会由嵌入式 AIAgent.run_conversation 或现有 `/v1/runs` 自动分派。因此终端直接调用官方 `cli.main()`，不再维护 Mikasa 输入循环。HTTP 的命令适配暂留，等待原生渠道完整接管其鉴权、回执与取消契约。终端系统命令可操作受信任用户的本地工作区；聊天模型工具当前仍限于记忆和只读 skills。

## default 分组

用户要求使用 CCH 的 `default` 分组。**分组属于 CCH Key 的 `providerGroup` 配置，不是请求 model。** 当前本地默认请求模型仍从 Codex 读取；设置 model 为 `default` 或增加自造 header 都不能完成分组切换。

当前 `provider_group=unverified`。此前本站 `/v1/models` 和 `/api/v1/me/metadata` 返回 Cloudflare 1010 `browser_signature_banned`；这是 WAF 证据，不能推断为 Key 权限不足。诊断命令不重复请求这些入口，不尝试绕过。

剩余网关侧验收：由有权限的管理者在 CCH 确认当前 Key 的有效 providerGroup 为 `default`，并用同次请求的路由日志确认选中的供应商符合该分组。若需改动，按网关权限修改 Key 的分组，再运行连接探针。只保存脱敏的分组/路由结论，不导出 Key；管理端无法访问时保持未验证，不阻塞独立的 GitHub、飞书接入准备。

## 故障处理

| 错误码 | 含义与下一步 |
| --- | --- |
| `missing_dependency` | 按 Hermes requirements-tested.txt 安装所选协议依赖 |
| `auth` | 服务拒绝认证；核对所选 Key 是否有效 |
| `access_denied` | HTTP 403；检查访问控制和 WAF，不能仅凭状态码判定 Key 权限 |
| `upstream_blocked` | Hermes 分类识别到 WAF/网关拦截；由服务管理员核对策略 |
| `billing` / `rate_limit` | 计费、额度或限流；核对 CCH 账户和上游容量 |
| `unavailable` / `timeout` / `tls` | 核对网络、证书链、CCH 和上游状态 |
| `model_unavailable` / `request_rejected` | 核对完整模型 ID、API 协议、模型权限及上下文限制 |
| `invalid_response` | 模型调用未产生约定 JSON；核对结构化输出能力 |
| `execution_failed` | 缺少可识别的故障证据；核对隔离环境、配置和提供商状态 |

以上分类来自官方 Hermes 结构化错误钩子，再经本地固定词表映射，不代表已查明网关根因。宿主进程超时、取消和输出上限保留已有提示。Hermes 和 CCH 各自保留官方内部恢复机制，Mikasa 不增加一层模型回退或自动换名。工程检查/修复在 Hermes 原生工具循环内完成；宿主 `max_attempts` 已停用，最终验收失败不自动重启 Agent，见 [0009](../decisions/0009-native-repair-loop.md)。

旧 API 聊天切换失败保留原模型和 revision，`execution.error_code` 提供已识别的失败类别；普通聊天失败不保存该轮，修复后可以重试。原生 CLI 使用 Hermes 自带错误反馈，不承诺真实推理失败自动回滚选择。工程任务的 `worker/failed` 事件可带 `error_code`，不保存 SDK 异常原文。查看与恢复方式见 [操作手册](OPERATIONS.md)。
