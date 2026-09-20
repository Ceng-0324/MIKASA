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

`/model` 是宿主系统命令，CLI 和 HTTP 使用同一控制面，不交给模型决定是否执行。直接输入 `/model gpt-6-astra` 或 `/model claude-opus-4-6`；裸 `/model` 列出当前模型及本地配置候选。也支持“切换为 完整模型ID”。模型是否可用必须由真实调用验证；成功后保留聊天上下文并保存新选择，失败保持原选择。

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

匹配优先级：完整 models 匹配 → 最长 prefixes 匹配 → worker 默认来源。同一完整模型或前缀不允许重复配置。菜单来自 models；前缀允许直接切换未列入菜单的新模型，不将示例列表当作 CCH 完整目录。`model_source` 只存来源引用，拒绝内嵌密钥；不同路由可以引用不同受信任配置文件。请求体、聊天文本和模型回复不能指定配置路径或任意端点。

模型切换时，端点、凭据和协议一起从选定来源读取到本次 worker 环境；当前会话只持久化模型名，其他聊天与工程默认配置保持独立。选定来源缺失或损坏时直接失败，不回退到其他来源的凭据。运行配置修改后，后续请求读取新配置所指向的认证；本机制不迁移正在生成的请求。

固定 CCH 源码按协议筛选供应商：Responses → codex，Messages → claude/claude-auth，Chat Completions → openai-compatible。Hermes 已原生支持这些 transport，因此切换 Claude 时采用 Messages，GPT 按 Codex 配置采用 Responses；不自研协议转换代理，不把所有名字塞进同一个 Responses 端点。

Hermes CLI/Gateway 的 `/model`、`/new`、`/init` 属于交互入口命令，不会由嵌入式 AIAgent.run_conversation 自动执行。Mikasa 使用自己的会话和授权入口，复用底层 harness；已接入 `/model`、`/new`、`/help` 和 `/version`；`/init` 随最后的工程交互接入，当前明确提示未执行。未开放的命令不转成普通模型请求。

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

以上分类来自官方 Hermes 结构化错误钩子，再经本地固定词表映射，不代表已查明网关根因。宿主进程超时、取消和输出上限保留已有提示。Hermes 和 CCH 各自保留官方内部恢复机制，Mikasa 不增加一层模型回退或自动换名；工程任务的重试/修复上限仍由 `max_attempts` 约束。

聊天切换失败保留原模型和 revision，`execution.error_code` 提供已识别的失败类别；普通聊天失败不保存该轮，修复后可以重试。工程任务的 `worker/failed` 事件可带 `error_code`，不保存 SDK 异常原文。查看与恢复方式见 [操作手册](OPERATIONS.md)。
