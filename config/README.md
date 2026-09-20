# 配置

这里保存可审查、可迁移的 Mikasa/Hermes 配置模板、schema 和环境说明。

当前使用版本化 JSON 配置：[examples/mikasa.json](examples/mikasa.json)。结构与权限校验由 `mikasa/config.py` 实现；未知顶层字段和非法身份会被拒绝。默认不启用仓库、模型命令、周期审计或外部发布。

当前分层：

- `examples/`：不含密钥的示例，`version=1`；
- `local/`：被 `.gitignore` 排除的机器配置；
- `README.md`：配置来源、覆盖顺序和迁移说明。

配置的权限不能超过 [工程契约](../engineering-contract.md)；文件中的文本也不是更高优先级的指令来源。仅运维账号可以编辑配置，它能选择仓库、执行命令和成员 token 映射。默认秘密通过环境注入；显式 `worker.model_source={"type":"codex"}` 可只读选用本机 Codex provider/API key，支持可选 `config_path` 和 `auth_path`，不写回原文件。`worker.home`、`worker.hermes_source` 是相对项目根目录或绝对路径，具体示例见 [Hermes 执行器](../workers/hermes/README.md)。其他字段见 [操作手册](../docs/runbooks/OPERATIONS.md)，不复制 Codex/Claude 的 `auth.json`。

原生 CLI/Gateway 使用 `runtime/native/<账号摘要>/config.yaml`。首次准备从 worker 配置生成默认模型、providers、模型别名和 Mikasa 加载项；后续保留 Hermes 的默认模型及显示/推理偏好，刷新生成的 CCH 路由并补齐必需 skills/plugin，不覆盖原生记忆或 SessionDB。`/model --global` 只改变该原生 profile，不改 worker 或 CCH 分组。格式错误时保留原文件并中止启动。详见 [原生 CLI 决定](../docs/decisions/0007-native-cli.md)。
