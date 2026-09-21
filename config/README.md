# 配置

这里保存可审查、可迁移的 Mikasa/Hermes 配置模板、schema 和环境说明。

当前使用版本化 JSON 配置：[examples/mikasa.json](examples/mikasa.json)。结构与权限校验由 `mikasa/config.py` 实现；未知顶层字段和非法身份会被拒绝。默认不启用仓库、模型命令、周期审计或外部发布。

可选 `feishu` 段配置国内应用、负责人 `owner_open_id` / `owner_user_id` 身份说明及凭据环境变量名；两个负责人 ID 均非聊天接入必填。飞书采用 Hermes 原生开放策略：所有用户、群聊、机器人可进入，群聊不要求 @；应用可用范围和消息权限仍需在飞书后台配置。微信通过 `weixin-login` 原生扫码绑定，仍限本人单聊；使用 `mikasa gateway --platform feishu --platform weixin` 启动一个统一 Hermes Gateway。`connections github|feishu|weixin` 做本地或只读检查，微信不支持 `--probe`。飞书诊断的 `access` 只说明生成策略，更新后需重启 Gateway 生效。字段示例、获取步骤与[环境模板](examples/platforms.env.example)用法见[接入手册](../docs/runbooks/CONNECTIONS.md)。

`schedules.audit_interval_seconds` 由 Hermes Cron 实现：0 关闭，60–604800 秒启用，支持非整分钟间隔；首次启用等待一个间隔。重启不重置下次执行时间，未改宿主间隔时保留原生暂停/周期编辑。关闭保留 job 和历史，改间隔后启用新周期。专用 `runtime/scheduler` home 只做无模型的审计入板，详见 [当前架构](../docs/architecture/README.md)。

当前分层：

- `examples/`：不含密钥的示例，`version=1`；
- `local/`：被 `.gitignore` 排除的机器配置；
- `README.md`：配置来源、覆盖顺序和迁移说明。

配置的权限不能超过 [工程契约](../engineering-contract.md)；文件中的文本也不是更高优先级的指令来源。仅运维账号可以编辑配置，它能选择仓库、执行命令和成员 token 映射。默认秘密通过环境注入；显式 `worker.model_source={"type":"codex"}` 可只读选用本机 Codex provider/API key，支持可选 `config_path` 和 `auth_path`，不写回原文件。`worker.home`、`worker.hermes_source` 是相对项目根目录或绝对路径，具体示例见 [Hermes 执行器](../workers/hermes/README.md)。其他字段见 [操作手册](../docs/runbooks/OPERATIONS.md)，不复制 Codex/Claude 的 `auth.json`。

原生 CLI/Gateway 使用 `runtime/native/<账号摘要>/config.yaml`。首次准备从 worker 配置生成默认模型、providers、模型别名和 Mikasa 加载项；后续保留 Hermes 的默认模型及显示/推理偏好，刷新生成的 CCH 路由并补齐必需 skills/plugin，不覆盖原生记忆或 SessionDB。`/model --global` 只改变该原生 profile，不改 worker 或 CCH 分组。格式错误时保留原文件并中止启动。详见 [当前架构](../docs/architecture/README.md)。

`worker.max_attempts` 已停用：宿主不再按次数重启 Agent 修复任务，检查与修复由 worker 内部工具循环完成。v1 配置暂接受旧整数值并由 doctor 的 `deprecated_settings` 提示；示例已删除此字段，迁移时可从本机配置移除。兼容仅用于已有配置不因升级无法启动；退出条件是下一版配置迁移同步删除旧字段。Hermes 工程仍受单次 24 次迭代、128 个工具证据事件、worker.timeout 与进程输出上限约束，详见 [当前架构](../docs/architecture/README.md)。
