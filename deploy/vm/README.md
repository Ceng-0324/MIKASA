# Mikasa 专用工作机

Mikasa 作为具有持续身份和记忆的仿真人程序员，拥有自己的 Linux 工作机。她以普通用户 `mikasa` 工作，使用免密 sudo 安装依赖、维护文件和用户、运行容器、管理服务及调整自身环境。VM 内不再限制为只能写状态目录，也不建立命令白名单或额外业务审批。

Hermes 承载执行和原生工具，CCH 提供模型，Mikasa 保留身份、skills、记忆和配置适配。系统管理员权限不改变 GitHub、飞书的实际权限，也不自动授权对外发布或合并。

## 当前部署

| 项目 | 设置 |
| --- | --- |
| OrbStack 机器 | `mikasa`，Ubuntu 24.04 arm64；4 核、6 GiB 内存、32 GiB 磁盘上限 |
| 运行环境 | 独立 Python 3.12.14 / SQLite 3.53.1、固定 Hermes、Git/gh、Node 22/npm、编译工具、Docker/Compose、ripgrep |
| 代码与依赖 | `/opt/mikasa`、`/opt/hermes`、`/opt/hermes-venv`、`/opt/python` |
| 账号与工作目录 | `/home/mikasa`，可在 `~/work` 放仓库；默认工程 workspace 继续位于受管状态中 |
| 配置与状态 | `/etc/mikasa/config.json`、私密 `/etc/mikasa/runtime.env`、`/var/lib/mikasa` |
| 消息入口 | [mikasa-gateway.service](mikasa-gateway.service)，统一飞书与微信 |
| 工程入口 | `engineer --cwd DIR -- chat`，完整原生 Hermes CLI |
| HTTP | [mikasa-api.service](mikasa-api.service) 仅保留模板，未启用公网 API |

`mylinux` 是迁移前环境，保留回退数据，不再作为 Mikasa 的工作机。具体迁移和验收结果见[验证边界](../../docs/VALIDATION.md)。

## 机器边界

```sh
orb create --isolated --isolate-network --user mikasa --cpus 4 --memory 6G --disk 32G ubuntu:24.04 mikasa
```

不设置 `--mount` 或 `--forward-ssh-agent`。新机没有 Mac 文件挂载、宿主 `mac` 命令能力或 SSH Agent 转发；阻断宿主与其他 OrbStack 机器的网络访问，保留互联网和 Mac 主动管理新机的入口。代码在机内 clone 或由宿主显式传入，不挂载个人主目录。

根据 [OrbStack 官方说明](https://docs.orbstack.dev/machines/isolated)，隔离机器共享 OrbStack 的 Linux 内核，不是每台拥有独立内核的完整虚拟机；适合日常开发与 Agent 执行，不应描述为内核级强隔离。机器依赖 Mac 在线。`app.start_at_login` 当前关闭，Mac 重启后不会仅凭 Linux 服务 enabled 自动上线；按需启动 OrbStack 和 `orb start mikasa`。

## 安装与权限

1. 创建上述隔离机器，确认 `machine.mikasa.isolated=true`、`isolate_network=true`、`forward_ssh_agent=false`、`mounts` 为空。不要通过打开宿主共享解决依赖问题。
2. 安装 Python 3.12、Git、gh、编译工具、Node/npm 和所需工具。Hermes 按[固定版本说明](../../workers/hermes/README.md)准备。当前使用 `/opt/python` 中已验证的 Python 3.12.14，系统 Python 保持不变；两个 venv 的解释器必须实际指向它。检查 `python -m pip check` 及 `sqlite3.sqlite_version`，避免旧 SQLite 使原生 WAL 降级。
3. `mikasa` 使用正常登录 shell。将 [sudo 规则](mikasa.sudoers) 经 `visudo -cf` 校验后放入 `/etc/sudoers.d/mikasa`，root:root 0440。验证 `sudo -n id -u` 返回 `0`；OrbStack 默认用户通常已具备免密 sudo。
4. `/etc/mikasa` 为 root:mikasa 0750，配置和环境文件为 0640。参考[配置模板](config.example.json)和[环境模板](runtime.env.example)，仅提供专用模型/平台凭据；不复制个人 Codex/Claude 认证目录。systemd 环境文件不是 shell 脚本，不使用 `source`、`export` 或命令替换。
5. 安装服务模板，执行 `systemd-analyze verify`、`systemctl daemon-reload`。服务以 mikasa 运行，保留 0077 umask、进程组清理和异常重启；不设置阻断 sudo/全盘管理的 `NoNewPrivileges`、`ProtectSystem` 或 `ReadWritePaths`。此模板只适用于专用机器。
6. 将 [journald.conf](journald.conf) 安装到 `/etc/systemd/journald.conf.d/mikasa.conf`：持久 journal 最多 256 MiB、14 天。Hermes 文件日志继续按原生机制管理；不限制工程产出和数据库空间。

聊天 profile 为 `/var/lib/mikasa/native/<账号摘要>`，独立工程 profile 为 `/var/lib/mikasa/engineer/<账号摘要>`。本机两者均采用原生 `approvals.mode: off` 处理普通命令；Hermes 的规则文件保护及其他不可绕过的原生检查仍保留。此项是专用机配置，不强制覆盖其他部署的选择，不修改上游源码。

GitHub 使用 mikasa 自己的 `gh auth login --with-token` 和 `gh auth setup-git`。专用 token 经标准输入登录，不出现在命令行；`~/.config/gh/hosts.yml` 为 0600。固定 Hermes 会清除 terminal 子进程的 GH_TOKEN，只注入主进程不足以支持 gh。认证与普通状态备份分别管理。

## 原生外部工具

可选 Python 依赖按固定快照安装，保留核心包版本：

```sh
/opt/hermes-venv/bin/python -m pip install -r /opt/mikasa/workers/hermes/requirements-tools.txt
/opt/hermes-venv/bin/python -m pip check
sudo apt-get install -y ffmpeg
sudo npm install -g agent-browser@0.26.0
npx --yes playwright@1.58.2 install chromium --with-deps
```

浏览器安装以 `mikasa` 用户执行，系统依赖由 sudo 安装。Linux arm64 不使用 `agent-browser install` 的 Chrome for Testing 下载，使用 Playwright Chromium。当前固定版本的可执行文件为 `/home/mikasa/.cache/ms-playwright/chromium-1208/chrome-linux/chrome`，将其链接为 `/usr/local/bin/chromium`；确保 `agent-browser` 也在服务 PATH 中。Hermes 使用原生 local browser backend，无自研浏览器驱动。

两个 profile 的原生 `config.yaml` 使用以下搜索配置；避免安装 ddgs 后自动选择当前网络无法访问的搜索后端：

```yaml
web:
  search_backend: exa
  extract_backend: exa
```

Exa 免费入口和 Edge TTS 仍依赖外网服务可用性。图像理解使用现有 CCH；当前 GPT Codex Responses 路由不接受原生 `video_url`。视频理解、图像/视频生成及其他外部服务按 Hermes 原生 provider、凭据和权限配置，不将依赖已安装解释为全部工具可用。MCP 在原生 `mcp_servers` 配置所需服务；无需部署一个重复本地文件工具的常驻 MCP。

固定 Hermes 的飞书文档/评论工具依赖原生评论事件提供的客户端上下文，仅配置聊天机器人凭据不足以在普通聊天直接调用这些工具。该入口、文档授权及其他未配置平台保留原生接入方式，不以工具出现在列表中认定已经接通。

## 迁移与回退

先在新机验证依赖、真实模型和平台认证，旧机继续服务。路径一致时保留 provider、模型选择、会话路由和记忆链接；模型来源改变导致 provider ID 变化时，按模型对应关系单独重绑。

切换前检查没有活跃任务，停止旧消息、HTTP、工程及调度进程，按[状态手册](../../docs/runbooks/OPERATIONS.md)执行 `backup`。在新机 `restore` 到尚不存在的 `/var/lib/mikasa`，核验数据库数量、记忆哈希和内部链接，再调整为新机 mikasa 用户所有。不要覆盖运行中的 SQLite。

微信 `credentials/weixin.json`、服务凭据和 gh 认证不在普通状态备份内，分别私密迁移或重新登录；既有机器人绑定无需重新扫码。外部仓库、用户工具和 `/home/mikasa` 数据须另行备份；管理员权限不会自动扩大 `backup` 范围。

旧服务停用后才启用新服务，避免双实例消费。回退先停新服务，保存并核对新增会话、记忆和工程产出，再选择恢复点；不盲目重启旧副本，不重新执行旧任务。

当前切换恢复点位于旧机 `/var/backups/mikasa/dedicated-machine-20260922`，部署依据在 `/var/backups/mikasa-service/dedicated-machine-20260922`。旧机和更早的 `native-engineering-20260922` 等恢复点均保留；私密状态不能提交 Git。

## 日常使用

```sh
orb -m mikasa
sudo -n id -u
sudo systemctl status mikasa-gateway.service --no-pager
sudo journalctl -u mikasa-gateway.service -n 80 --no-pager
```

工程入口由 systemd 注入专用凭据，不手工拼接密钥：

```sh
sudo systemd-run --pty --wait --collect --property=User=mikasa --property=Group=mikasa --property=EnvironmentFile=/etc/mikasa/runtime.env --working-directory=/opt/mikasa /opt/mikasa/.venv/bin/python -m mikasa --config /etc/mikasa/config.json engineer --cwd /home/mikasa/work/REPO -- chat
```

替换 REPO 为已有仓库，或省略 `--cwd ...` 使用默认持久 workspace。也可以在飞书、微信直接说明仓库绝对路径和任务；Hermes 在当前会话执行并反馈。消息 Gateway 自带原生 Cron/Kanban 调度，独立工程 profile 需要常驻调度时使用工程入口的 `gateway run`，不恢复 Mikasa runner。

Mac 管理命令明确指定 `orb -m mikasa -u root -w / ...`。启动和重启机器分别用 `orb start mikasa`、`orb restart mikasa`；由 Mac 发起，不让机内程序控制 OrbStack 其他机器。`connected` 只证明当前连接状态，不能代替持续收发和用户交互验收。
