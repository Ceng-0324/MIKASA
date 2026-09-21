# 配置

这里保存不含密钥的配置示例；机器配置放在 Git 忽略的 `local/` 中。

## 准备配置

新机器从 [examples/mikasa.json](examples/mikasa.json) 复制一份到 `local/`，按 [Hermes 执行器](../workers/hermes/README.md) 配置固定环境，按 [CCH 手册](../docs/runbooks/CCH.md) 配置模型来源。后续命令以本机已有的 `config/local/hermes-cch.json` 为例；已有配置直接使用，不要用示例覆盖。

配置使用 `version=1` JSON，校验实现在 [mikasa/config.py](../mikasa/config.py)，没有独立 schema 文件。未知顶层字段和非法身份会被拒绝。默认示例未配置模型、仓库、周期审计或外部发布；纯聊天和 GitHub 账号身份检查都允许 `repositories={}`。

## 配置由谁维护

| 来源 | 内容与职责 |
| --- | --- |
| `local/*.json` | 运维配置：模型来源、Hermes 路径、仓库、平台身份和凭据环境变量名 |
| 环境变量 / 显式本机模型来源 | 运行凭据；环境变量名见[模板](examples/platforms.env.example)，不将密钥写进 Git |
| `<runtime>/native/<账号摘要>/config.yaml` | Hermes 聊天 profile 的默认模型、显示和推理偏好，以及 Mikasa 生成的 providers、skills/plugin 配置 |
| `<runtime>/credentials/weixin.json` | 原生扫码后的私密绑定，由 `weixin-login` 写入，不能当作缓存清除 |

`<runtime>` 指 JSON 中的运行目录。`worker.home`、`worker.hermes_source` 和 `worker.native_python` 使用绝对路径或相对项目根目录的路径。配置由运维账号维护，文件文本不获得高于[工程契约](../engineering-contract.md)的指令权限。

默认凭据通过环境注入；显式 `worker.model_source={"type":"codex"}` 可只读使用本机 Codex provider/API key，支持 `config_path` 和 `auth_path`，不写回或复制个人认证文件。Claude Code 来源及多协议路由同见 [CCH 手册](../docs/runbooks/CCH.md)。

首次准备 profile 时从 worker 配置生成默认模型；后续保留 Hermes 保存的模型、显示和推理偏好，刷新 CCH providers/别名与必需 skills/plugin，不覆盖记忆或 SessionDB。`/model --global` 只改该聊天 profile，不改工程 worker 或 CCH Key 分组；固定版本的重启生效限制见[聊天手册](../docs/runbooks/CHAT.md)。原生配置格式错误时保留文件并中止启动。

## 按用途查字段

| 用途 | 配置与说明 |
| --- | --- |
| GitHub / 飞书 / 微信 | [接入手册](../docs/runbooks/CONNECTIONS.md)：GitHub token、飞书应用与可选主人 ID、微信扫码、统一 Gateway 和只读诊断 |
| 仓库、检查、API、发布 | [操作手册](../docs/runbooks/OPERATIONS.md) |
| 周期审计 | `schedules.audit_interval_seconds`：0 关闭，60–604800 秒启用；原生 Cron 的持久化和暂停行为见[架构](../docs/architecture/README.md) |
| 执行资源与工具边界 | [Hermes 执行器](../workers/hermes/README.md) |

`worker.max_attempts` 已停用：检查与修复由 worker 内部工具循环完成。v1 暂接受旧整数值，`doctor.deprecated_settings` 会提示，可从本机配置移除；下一版配置迁移时删除此兼容字段。
