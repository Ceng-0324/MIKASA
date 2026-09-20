# 运行时目录

本地默认状态位于 `runtime/state/`：`mikasa.sqlite3` 保存任务与事件，`runner.lock` 限制并发执行，`workspaces/<task>/<attempt>/` 保存独立 Git 工作区。部署时可整体迁移到 `/var/lib/mikasa`。这些数据不入 Git，见根目录 `.gitignore`。

运行数据包含任务上下文和外部响应。数据库权限 0600，状态目录初始 0700；保留和清理由运维决定，默认不自动删除现场。备份与恢复见 [操作手册](../docs/runbooks/OPERATIONS.md)。
