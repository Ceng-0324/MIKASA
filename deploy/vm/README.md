# VM 部署模板

包含 [API 服务](mikasa-api.service) 和 [runner 服务](mikasa-runner.service)，目标为 Linux systemd，代码 `/opt/mikasa`，配置 `/etc/mikasa/config.json`，状态 `/var/lib/mikasa`，专用账号 `mikasa`。

部署前按照 [操作手册](../../docs/runbooks/OPERATIONS.md) 准备 Python、固定版本 Hermes、模型端点、rootless Docker 检查镜像和环境文件，再在目标 VM 执行 `systemd-analyze verify`。服务单元尚未在目标 VM 运行验证，本次不执行安装或启用。
