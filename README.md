# Mikasa

她叫 Mikasa。这并不是又一个把 Agent 重新包一遍的项目，而是把一个有身份、有记忆、会把事情做完的程序员接到真实工作环境里。

Mikasa 的底层是 [Hermes Agent](https://github.com/NousResearch/hermes-agent)，模型通过 [Claude Code Hub](https://github.com/ding113/claude-code-hub) 路由。Hermes 负责工具、会话、记忆、skills、Gateway 和工程执行；CCH 负责模型与协议路由；本项目只维护身份、协作规则、账号绑定和必要适配。能交给原生能力的事，就不在这里再造一套。

## 你会得到什么

- 在终端、飞书或微信里和同一个 Mikasa 交谈。
- 用 `/model` 在 CCH 提供的 GPT、Claude 等模型之间切换。
- 让她直接进入真实 Git 仓库，读规则、改代码、跑测试、使用后台进程并提交结果。
- 让身份和长期记忆跨会话保留，同时把具体聊天上下文交给 Hermes 管理。
- 看到原生工具进度、阶段说明和长任务提醒；任务结束时收到实际结果，而不是一张“已处理”的空收据。

她不是自动合并机器人，也不是把权限藏在另一套业务规则后面的审批系统。仓库规则、平台权限和人的授权仍然决定什么可以做。

## 快速开始

需要 Python 3.12+、Git，以及固定版本的 Hermes 环境。先复制示例配置到被 Git 忽略的本地目录，再准备模型来源：

```sh
mkdir -p config/local
cp config/examples/mikasa.json config/local/mikasa.json
python3.12 -m mikasa --config config/local/mikasa.json doctor
```

常用入口（命令都追加在 `python3.12 -m mikasa --config ...` 后）：

| 入口 | 用途 |
| --- | --- |
| `chat` | 终端聊天，使用 Hermes 原生系统命令 |
| `gateway --platform feishu --platform weixin` | 一个 Gateway 接入飞书和微信 |
| `engineer --cwd /path/to/repo -- chat` | 在真实仓库中使用完整 Hermes 工具 |

终端 CLI 可以和一个消息 Gateway 并存；两个 Gateway 不能同时占用同一 profile。聊天中直接使用 `/help`、`/new`、`/model <模型 ID>`。配置和平台接入步骤见[配置说明](config/README.md)、[聊天手册](docs/runbooks/CHAT.md)、[CCH 手册](docs/runbooks/CCH.md)和[接入手册](docs/runbooks/CONNECTIONS.md)。

## 开发

```sh
python3.12 -m unittest discover -v
python3.12 scripts/check_docs.py
python3.12 -m mikasa doctor
git diff --check
```

代码在 `mikasa/`，Hermes 适配在 `workers/hermes/`，开发验收脚本在 `scripts/`。部署实现和 VM 操作说明在 `deploy/vm/`。本地配置、认证、会话、备份、日志和缓存均不进入 Git；提交前请检查工作树，不要把自己的世界观写成别人的密钥管理方案。

身份与工程规则由 [identity.md](identity.md)、[engineering-contract.md](engineering-contract.md) 和 [engineering-workflow.md](engineering-workflow.md) 提供。它们约束协作方式，不替代 Hermes 的工具和权限模型。

## 分工

| 组件 | 责任 |
| --- | --- |
| [Hermes](https://github.com/NousResearch/hermes-agent) | Agent harness、原生 CLI/Gateway、工具、会话、记忆、skills、调度和状态 |
| [CCH](https://github.com/ding113/claude-code-hub) | 模型供应、协议选择、模型重写与服务端分组 |
| [Mikasa](https://github.com/Mikasa-0910/mikasa) | 身份、人格、工程协作规则、账号绑定、配置和平台适配 |

这就是项目的边界。Mikasa 保留判断和性格，Hermes 负责把判断变成可靠的工程动作，CCH 负责把请求送到合适的模型。
