# 运行时目录

本地默认状态位于 `runtime/state/`：`kanban/kanban.db` 是原生任务/依赖/run/事件的唯一事实源，`mikasa.sqlite3` 保存发布/聊天回执、控制设置与历史档案，`runner.lock` 限制并发执行，`workspaces/<task>/<attempt>/` 保存独立 Git 工作区。部署时可整体迁移到 `/var/lib/mikasa`。这些数据不入 Git，见根目录 `.gitignore`。

运行数据包含任务上下文和外部响应。数据库权限 0600，状态目录初始 0700；保留和清理由运维决定，默认不自动删除现场。备份与恢复见 [操作手册](../docs/runbooks/OPERATIONS.md)。

清理时按用途区分，不能直接删除整个 `runtime/cache/` 或 `runtime/state/`：

- `cache/hermes-source`、`cache/hermes-venv` 是当前运行依赖，虽然位于 cache，仍需保留。
- `cache/uv` 是可重新下载的安装缓存，安装进程停止后可以清理。
- `state/.../native` 中的原生会话、记忆、幂等数据库与服务凭据，、原生 `kanban/kanban.db` 以及业务 `mikasa.sqlite3` 是持久数据，不能当缓存删除；运行中的 profile 不做文件级清理。
- `implementation-*` 仅在确认来自合成验收、没有运行中任务后清理；真实任务工作区按其交付与恢复需求保留。
- 脱敏验收记录保存在 `docs/`，仍用于复现的验收脚本保存在 `scripts/`。清除重复调试入口不等于删除回归测试。
