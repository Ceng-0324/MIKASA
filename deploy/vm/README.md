# VM 部署

目标为 Linux systemd，代码 `/opt/mikasa`，配置 `/etc/mikasa/config.json`，状态 `/var/lib/mikasa`，专用账号 `mikasa`。当前模板覆盖范围：

| 服务 | 入口 | 当前状态 |
| --- | --- | --- |
| [API](mikasa-api.service) | `serve` | 已有模板；HTTP 聊天的每账号 Hermes Gateway 由 API 管理 |
| [工程 runner](mikasa-runner.service) | `run` | 已有模板；消费工程任务队列 |
| [飞书 / 微信](mikasa-gateway.service) | `gateway --platform feishu --platform weixin` | 统一消息服务模板；本阶段首先部署 |

本阶段使用已有 OrbStack `mylinux`（Ubuntu 26.04 arm64），在独立目录安装 Python 3.12，以专用 `mikasa` 用户运行。它依赖 Mac 保持运行，不能等同于独立云主机的持续在线。部署结果和验收限制统一记录在[验证边界](../../docs/VALIDATION.md)。

消息 Gateway 是独立运行入口；同一账号 profile 不能同时由终端、HTTP 聊天和消息 Gateway 管理。只启用消息服务时无需启动 API、runner、Docker 或 TLS 反向代理；飞书长连接和微信轮询主动向外连接，不需要公网入站端口。工程执行和 GitHub webhook 在后续阶段启用。

为 `worker.hermes_source` 设置固定源码目录，为 `worker.native_python` 设置 Hermes 专用解释器；模型来源使用 VM 专用凭据引用。现有单元使用 control-group 关闭子进程，状态仅写 `/var/lib/mikasa`。维护前停服并执行完整 `backup`，`restore` 只恢复到新目录；重新提供外部配置与凭据并核对状态后启动，不复制个人 Codex/Claude 认证文件。

## 安装与配置

1. 启动指定 Linux VM，检查已有服务和可用资源，再建立专用服务用户 `mikasa`，服务用户不需要 sudo。本机使用 `orb start mylinux`，管理命令使用 `orb -m mylinux -u root -w / ...`，不用默认机器。新机器推荐 Ubuntu 24.04；复用其他版本时单独安装 Python 3.12，不替换系统解释器。
2. 安装 Git、CA 证书、Python 3.12 及 venv，将已验证项目放入 `/opt/mikasa`，建立 `/opt/mikasa/.venv`。代码由 root 管理，服务用户只读。按[固定 Hermes 安装说明](../../workers/hermes/README.md)安装到 `/opt/hermes` 和 `/opt/hermes-venv`；Mac 的 venv 不能复制到 Linux，依赖快照须在 Linux 重新安装与检查。
3. 将 [config.example.json](config.example.json) 安装为 `/etc/mikasa/config.json`，填写实际模型目录与原有飞书主人 ID；将 [runtime.env.example](runtime.env.example) 的结构用于私密 `/etc/mikasa/runtime.env`。目录 root:mikasa 0750、两文件 root:mikasa 0640。环境文件使用 systemd 赋值语法，不使用 `export`、命令替换或 `source`。
4. GPT/Claude 各自指定 CCH 端点、Key 和协议，来源 `env` 引用须列入 `worker.env_allowlist`。仅将服务需要的凭据注入 VM 私密环境，不复制个人认证目录，也不将密钥写进命令行、日志或 Git。缺少任一路由的显式环境引用会阻止启动。
5. 保留本机消息服务运行，先验证 VM 的固定 Hermes、依赖、模型和飞书只读探针。将服务单元安装到 `/etc/systemd/system/mikasa-gateway.service`，执行 `systemd-analyze verify` 与 `systemctl daemon-reload`；此时尚不启动消息消费。

## 状态迁移与切换

1. 记录源代码版本、服务 PID、原生会话与记忆数量。确认 VM 前置检查通过后，停止 Mac 的统一 Gateway，并等到子进程退出；两台机器不能同时消费同一机器人消息。
2. 按[备份手册](../../docs/runbooks/OPERATIONS.md)生成停服快照，私密传输到 VM，再用 `restore` 恢复到尚不存在的 `/var/lib/mikasa`。保留 Mac 原 runtime 和恢复点；备份不是可公开的脱敏包。
3. 微信 `credentials/weixin.json` 不在普通状态备份中，需独立通过私密通道安装到新 runtime，目录 0700、文件 0600、归 `mikasa` 所有。先验证绑定；失效才在 VM 重新扫码。飞书和微信的主人账号关系沿用已确认绑定。
4. 本机 `codex`/`claude` 来源改为 VM `environment` 来源会改变生成的 provider ID。停止状态下，根据两份配置的来源和模型对应关系，重绑恢复副本中的默认 provider、会话模型覆盖与待用回执路由；不修改原备份或历史聊天文本，不直接删除 config、SessionDB 或 memories。无法匹配的选择先核实，不能静默换模型。
5. 恢复目录归 `mikasa` 所有。用该用户和 systemd 环境执行 doctor、平台检查及模型探针，确认身份/skills 与原有会话、记忆存在。服务的 `active` 只证明进程存活，还需检查 Hermes 的平台状态和实际消息往返。

```sh
sudo systemctl enable --now mikasa-gateway.service
sudo systemctl status mikasa-gateway.service --no-pager
sudo journalctl -u mikasa-gateway.service -n 80 --no-pager
```

在飞书和微信分别验证 `/help`、普通消息、`/model 完整模型ID` 与 `/new`，核对主人身份及跨会话记忆；随后检查停止、重启、自动拉起和状态恢复。日志可能含私密消息，只在本机查看，不原样上传。

## 日常运维与回退

Mac 上通过 `orb -m mylinux -u root -w / systemctl status mikasa-gateway.service --no-pager` 查看服务；重启用 `systemctl restart`，停用用 `systemctl disable --now`。VM 停止后用 `orb start mylinux`，已启用的服务随 Linux 启动。Mac 重启后的 OrbStack 自动启动取决于本机登录与应用设置，不能仅凭 systemd enabled 承诺无人值守恢复。

切换失败时先停止 VM 消息服务，再恢复 Mac 原 Gateway。若 VM 已接收新消息，先保存新状态并核对会话/记忆差异；直接启动旧副本会丢失迁移后的连续性。回退不删除任一侧数据库或重新执行工程副作用。
