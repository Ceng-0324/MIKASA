# CCH 模型配置与诊断

Mikasa 读取模型配置，Hermes 官方 harness 负责模型调用，CCH 负责上游选择、模型重写和网关故障切换。Mikasa 不新增路由网关，也不修改个人 Codex 配置。

官方源码调研固定为 CCH `dfeb14331cb350f672e92a3684adecf1052dd476`，本站部署版本未确认；阅读过源码，未运行 CCH 上游测试。关键依据：

- [provider-selector.ts](https://github.com/ding113/claude-code-hub/blob/dfeb14331cb350f672e92a3684adecf1052dd476/src/app/v1/_lib/proxy/provider-selector.ts)：按模型和协议选供应商，旧会话绑定不支持新模型时重新选择。
- [model-redirector.ts](https://github.com/ding113/claude-code-hub/blob/dfeb14331cb350f672e92a3684adecf1052dd476/src/app/v1/_lib/proxy/model-redirector.ts)：供应商 modelRedirects 可改写请求模型。
- [provider-cache.ts](https://github.com/ding113/claude-code-hub/blob/dfeb14331cb350f672e92a3684adecf1052dd476/src/lib/cache/provider-cache.ts)：配置更新发布缓存失效通知，Redis 不可用时依赖 30 秒 TTL；作用于后续请求，不迁移生成中的流。

## 配置和连接检查

按 [Hermes 配置](../../workers/hermes/README.md) 选择 `codex`、`claude` 或 `environment`。环境来源只读取 `worker.env_allowlist` 内的模型变量；Codex 来源按 env_key、内嵌 bearer、邻近 auth.json 的顺序只读取得 API key；Claude 来源只读选定 settings.json 中的 CCH 端点和 token/API key，不复制认证文件。

```sh
python3.12 -m mikasa --config config/local/hermes-cch.json doctor
python3.12 -m mikasa --config config/local/hermes-cch.json doctor --probe-model
python3.12 -m mikasa --config config/local/hermes-cch.json doctor --model claude-opus-4-6 --probe-model
```

第一条只检查本地条件，`connection=not_checked`。第二条通过临时原生 CLI 发送一次聊天请求，会消耗一次模型调用；成功为 `connection=passed`，失败或配置不完整时退出码为 1。探针只使用临时 profile，会话和日志随探针清理，不改正式聊天、工程状态或默认模型。配置、进程、协议或输出契约失败都不能报告连接通过。

输出的 `requested_model` 是请求名，`reported_model` 是响应标识，`model_match` 为 same/different/unreported。即使 same，也不能独立证明供应商实际底层模型。`backend=hermes-gateway` 表示原生探针入口；本地夹具不能作为真实 CCH 联调。默认 doctor 的退出码仍只表示命令执行成功，模型配置状态读取 `model.configuration`。

## VM 环境变量来源

VM 使用 `environment` 来源，不复制个人 Codex/Claude 认证文件。`model_source.env` 可将四个模型字段映射到该路由专用的环境变量名；映射后的名字仍须列入 `worker.env_allowlist`。显式引用缺失、为空或未获允许时直接失败，不回退到另一套 Key 或协议。

完整双协议示例见 [VM 配置](../../deploy/vm/config.example.json)及[环境模板](../../deploy/vm/runtime.env.example)：GPT 使用 Responses，Claude 使用 Messages。Hermes 聊天和工程 profile 都接收已配置 provider 的 Key 环境引用，由原生选择模型和协议。模型 ID 与端点按实际 CCH 配置填写，分组仍由 CCH Key 决定。

## /model 跨 GPT 与 Claude 切换

终端和消息网关中的 `/model` 均由 Hermes 原生执行，可使用 `/model gpt-6-astra` 或 `/model claude-opus-4-6` 并保留上下文。session/once/global、provider/reasoning 等参数按原生语义处理。选择器与目录校验不额外发送推理探针；实际可用性通过 `doctor --model ID --probe-model` 或真实对话验证。见[聊天手册](CHAT.md)。

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

Mikasa 配置匹配优先级：完整 models 匹配 → 最长 prefixes 匹配 → worker 默认来源。同一完整模型或前缀不允许重复配置。配置生成和模型诊断使用这套选择规则；工程与聊天原生 CLI 将默认模型和显式 models 生成精确别名，由 Hermes 选择相应 provider。新模型推荐加入对应 models；未列出的模型需显式选择原生 provider，CLI 不复刻前缀路由。候选不是 CCH 完整目录。`model_source` 只存来源引用，拒绝内嵌密钥；不同路由可以引用不同受信任配置文件。聊天文本和模型回复不能指定配置路径或任意端点。

原生 profile 启动时读取已配置来源，将端点、协议、模型别名和 key_env 写入 Hermes 配置；实际 Key 仅在子进程环境中。`/model` 由 Hermes 同时解析目标模型、provider、协议和 Key。`--global` 写入原生 profile，下次初始化保留该选择；工程 profile 独立保存原生默认值。配置或认证变更后需重启对应 CLI/Gateway；不迁移正在生成的请求。来源缺失或损坏时直接失败，不借用其他来源凭据。

固定 CCH 源码按协议筛选供应商：Responses → codex，Messages → claude/claude-auth，Chat Completions → openai-compatible。Hermes 已原生支持这些 transport，因此切换 Claude 时采用 Messages，GPT 按 Codex 配置采用 Responses；不自研协议转换代理，不把所有名字塞进同一个 Responses 端点。

Mikasa 直接启动 Hermes 官方 CLI 或消息 Gateway，系统命令由对应原生入口分派，不维护额外命令解析器。

## default 分组

用户要求使用 CCH 的 `default` 分组。**分组属于 CCH Key 的 `providerGroup` 配置，不是请求 model。** 当前本地默认请求模型仍从 Codex 读取；设置 model 为 `default` 或增加自造 header 都不能完成分组切换。

当前 `provider_group=unverified`。此前本站 `/v1/models` 和 `/api/v1/me/metadata` 返回 Cloudflare 1010 `browser_signature_banned`；这是 WAF 证据，不能推断为 Key 权限不足。诊断命令不重复请求这些入口，不尝试绕过。

剩余网关侧验收：由有权限的管理者在 CCH 确认当前 Key 的有效 providerGroup 为 `default`，并用同次请求的路由日志确认选中的供应商符合该分组。若需改动，按网关权限修改 Key 的分组，再运行连接探针。只保存脱敏的分组/路由结论，不导出 Key；管理端无法访问时保持未验证，不阻塞独立的 GitHub、飞书接入准备。

## 故障处理

工程使用 Hermes 原生错误反馈与恢复，不再要求模型返回 JSON。`doctor` 只报告已确认的本地配置、连接或运行失败，不将缺少结构化根因的错误猜测为认证、限流或 WAF。

遇到 403 需结合网关管理端判断，不等同于 Key 无效；检查模型完整 ID、协议、端点、Key 和上游容量。Mikasa 不增加自动换名或模型回退。原生 CLI 的切换与推理失败沿用 Hermes 语义，不承诺自动回滚。
