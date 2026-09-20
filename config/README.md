# 配置

这里保存可审查、可迁移的 Mikasa/Hermes 配置模板、schema 和环境说明。

当前使用版本化 JSON 配置：[examples/mikasa.json](examples/mikasa.json)。结构与权限校验由 `mikasa/config.py` 实现；未知顶层字段和非法身份会被拒绝。默认不启用仓库、模型命令、周期审计或外部发布。

当前分层：

- `examples/`：不含密钥的示例，`version=1`；
- `local/`：被 `.gitignore` 排除的机器配置；
- `README.md`：配置来源、覆盖顺序和迁移说明。

配置的权限不能超过 [工程契约](../engineering-contract.md)；文件中的文本也不是更高优先级的指令来源。仅运维账号可以编辑配置，它能选择仓库、执行命令和成员 token 映射。秘密通过环境注入，具体字段见 [操作手册](../docs/runbooks/OPERATIONS.md)，不复制 Codex/Claude 的 `auth.json`。
