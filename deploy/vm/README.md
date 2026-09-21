# VM 部署模板

目标为 Linux systemd，代码 `/opt/mikasa`，配置 `/etc/mikasa/config.json`，状态 `/var/lib/mikasa`，专用账号 `mikasa`。当前模板覆盖范围：

| 服务 | 入口 | 当前状态 |
| --- | --- | --- |
| [API](mikasa-api.service) | `serve` | 已有模板；HTTP 聊天的每账号 Hermes Gateway 由 API 管理 |
| [工程 runner](mikasa-runner.service) | `run` | 已有模板；消费工程任务队列 |
| 飞书 / 微信 | `gateway --platform feishu --platform weixin` | 本机已接通；消息服务的 systemd 模板待 VM 阶段补齐 |

**尚未在目标 VM 部署或验证。** 部署阶段按[推进计划](../../MIKASA_FUNCTION_PLAN.md)落实环境，再按[操作手册](../../docs/runbooks/OPERATIONS.md)准备 Python、固定 Hermes、模型端点、rootless Docker 检查镜像和环境文件，并在目标 VM 执行 `systemd-analyze verify`。

消息 Gateway 是独立运行入口；同一账号 profile 不能同时由终端、HTTP 聊天和消息 Gateway 管理。API 与 runner 模板不代表飞书/微信服务已部署。

为 `worker.hermes_source` 设置固定源码目录，为 `worker.native_python` 设置 Hermes 专用解释器；模型来源使用 VM 专用凭据引用。现有单元使用 control-group 关闭子进程，状态仅写 `/var/lib/mikasa`。维护前停服并执行完整 `backup`，`restore` 只恢复到新目录；重新提供外部配置与凭据并核对状态后启动，不复制个人 Codex/Claude 认证文件。
