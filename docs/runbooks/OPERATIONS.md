# 工程与状态运维

先准备 [Hermes](../../workers/hermes/README.md) 与 [CCH](CCH.md)。工程不要求 Docker 或仓库白名单；依赖、网络和文件权限来自实际运行环境。

## 原生工程入口

```sh
python3.12 -m mikasa --config config/local/hermes-cch.json engineer --cwd /absolute/repo -- chat
python3.12 -m mikasa --config config/local/hermes-cch.json engineer --cwd /absolute/repo -- chat --resume latest
python3.12 -m mikasa --config config/local/hermes-cch.json engineer -- kanban --help
python3.12 -m mikasa --config config/local/hermes-cch.json engineer -- cron --help
```

省略 cwd 时使用 engineering.cwd，否则使用工程 profile/workspace。工程 profile 为 runtime/engineer/<账号摘要>，可通过原生 config、tools、skills 命令维护。terminal backend 默认 local，原生 Docker、SSH、浏览器、MCP 等按 Hermes 要求另行配置。不主动启用任务 daemon 或消息投递；确有调度需求时使用原生工程 gateway，遵守原生单 dispatcher 要求。

仓库是完整持久目录，包含 .git、二进制、规则文件和用户改动。中断后通过原生 --resume 恢复历史并核对现场；不会重新导出快照覆盖工作区。模型负责按项目要求测试、修复和交付，宿主不替模型创建提交或发布。推送、发消息和外部发布仍按用户实际授权执行。

GitHub 专用 token 映射为 Hermes 主进程的 GH_TOKEN。固定 Hermes 的终端环境会清除该变量，gh 命令不能据此直接视为已登录；终端 Git/gh 按原生 credential helper 或 gh auth 准备，FluxCore PR #28 已完成创建及负责人合并，正式 Review 仍待实测。repositories 仅作为 connections github --probe 的可选检查清单，不限制工程访问范围。GitHub 实际 token scope、仓库权限和操作系统权限继续生效。

## 旧链路退休

run/submit/publish/expand、Mikasa worker v1 RPC、旧 Kanban/Cron 业务适配已退出执行。旧数据不会迁成可自动运行的新任务，也不删除：engineering、kanban、scheduler、workspaces 和业务库作为档案保留。历史任务及发布歧义需在旧档案和外部平台核实，不能通过新入口自动重发。

旧配置中的 worker.command/home/max_attempts/max_output_bytes/max_context_bytes、schedules、server.auto_review、github.publish_enabled 已无执行作用，doctor 会提示清理。worker.timeout 只用于 HTTP 聊天等待；工程预算以原生配置为准。

## 备份与恢复

```sh
python3.12 -m mikasa --config config/local/hermes-cch.json backup /secure/backups/mikasa-state
python3.12 -m mikasa --config config/local/hermes-cch.json restore /secure/backups/mikasa-state /var/lib/mikasa-restored
```

先停止消息 Gateway、HTTP、工程 CLI/daemon 与其后台任务。受管入口的维护锁会拒绝运行期间备份；自行直接启动的 Hermes 进程也须停止。

v3 清单覆盖 runtime 下 native、engineer、mikasa.sqlite3 及旧 engineering/kanban/scheduler/workspaces。使用 Hermes WAL 安全快照，文件记录 SHA-256，保留内部记忆链接和 Git 对象，支持读取旧 v2 备份。恢复到源目录外的新目标，不覆盖、不启动服务、不自动执行旧任务。

聊天和独立工程的受管 workspace 均按项目文件备份，其中名为 cache、logs 的源码目录不作为运行缓存删除。原生 profile 的缓存、日志和 Gateway 控制 socket/路径指针排除；这些连接端点由 Hermes 启动时重建。

外部工程 cwd、外部符号链接、认证文件及未受管数据不包含；外部链接会拒绝备份。配置密钥字段被排除，key_env 引用保留。备份包含私密会话和本机 .api-key，不能公开。恢复后重新注入外部凭据并核对工作区、原生配置与自定义路径；Git worktree 的外部或绝对链接按 Git 原生 repair 流程处理。自定义 Cron 脚本的绝对路径和外部仓库需另行核对。

备份不会把工程限制为受管 workspace；选择外部 cwd 时同时承担独立备份责任。目录权限 0700，文件 0600/可执行文件 0700。VM 启动、恢复点与部署步骤见 [VM 手册](../../deploy/vm/README.md)。

### 专用 VM 维护

在 `mikasa` VM 内以 root 运行 [维护入口](../../deploy/vm/manage.py)：

```sh
sudo python3 /opt/mikasa/deploy/vm/manage.py status
sudo python3 /opt/mikasa/deploy/vm/manage.py backup
sudo python3 /opt/mikasa/deploy/vm/manage.py check
sudo python3 /opt/mikasa/deploy/vm/manage.py restore SNAPSHOT /var/lib/mikasa-restore-check
```

源码发布包由宿主的 `scripts/package_vm.py` 从干净 Git checkout 生成，再用 `manage.py deploy` 安装。维护先检查空闲，并通过 Hermes 原生 drain 请求关闭新任务准入；确认排空后才停止 Gateway。30 秒内未排空则取消维护，让任务继续执行。独立工程入口仍由维护锁保护；不通过停机强制中断任务。新版本身份加载、双平台连接和服务健康检查失败会自动回切，运行状态不回滚。`mikasa-backup.timer` 每日执行一次加密备份并保留 7 个日、4 个周、3 个月快照。Restic 密码文件只在 `/etc/mikasa-backup/password`，恢复到 VM 外时需另外保管该密码，不能提交 Git。

定时服务直接执行维护入口，不能声明 `After=mikasa-gateway.service`：维护中需要同步重启 Gateway，该排序会使自身启动作业与 Gateway 启动作业互相等待。自维护由独立 systemd 作业执行，不能从 Gateway 内同步等待自己的停止。

Restic 快照保留源目录的绝对链接和权限。演练时先在新目录检查 SQLite、记忆及 Git 字节，再修复副本中的 worktree 链接；不要通过副本的绝对链接误操作当前目录。灾难恢复需要先准备相同系统用户和系统依赖，再停服将选定数据放回原路径，恢复服务文件并核验；不是完整系统磁盘镜像。VM 外副本可由 Mac 显式拉取到被 Git 忽略的 `runtime/backups/`，密钥单独保存于 `config/local/`，两者不进入提交。每日 timer 只更新 VM 内仓库；VM 外副本应定期另行刷新，Mac 磁盘损坏仍需异机备份。
