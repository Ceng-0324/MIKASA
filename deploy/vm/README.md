# VM 部署模板

包含 [API 服务](mikasa-api.service) 和 [runner 服务](mikasa-runner.service)，目标为 Linux systemd，代码 `/opt/mikasa`，配置 `/etc/mikasa/config.json`，状态 `/var/lib/mikasa`，专用账号 `mikasa`。

部署前按照 [操作手册](../../docs/runbooks/OPERATIONS.md) 准备 Python、固定版本 Hermes、模型端点、rootless Docker 检查镜像和环境文件，再在目标 VM 执行 `systemd-analyze verify`。服务单元尚未在目标 VM 运行验证，本次不执行安装或启用。

原生聊天 Gateway 是 API 服务管理的每账号子进程，不再额外部署第二套聊天服务。为 `worker.hermes_source` 设置固定源码目录，为 `worker.native_python` 设置 Hermes 专用解释器；全部模型来源使用 VM 专用的显式凭据引用。API 单元使用 control-group 关闭子进程，状态仍仅写 `/var/lib/mikasa`。初次迁移先备份旧业务 SQLite；完整恢复还需保留原生 profile 的 SessionDB、memories 和本机服务凭据，不复制个人 Codex/Claude 认证文件。
