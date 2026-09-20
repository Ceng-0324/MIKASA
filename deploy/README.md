# 部署

这里记录 VM、容器、服务管理、网络入口、secret store、备份和恢复的部署设计。

已提供 Linux [systemd 模板](vm/README.md) 和 [操作手册](../docs/runbooks/OPERATIONS.md)，使用专用账号、受限环境文件和独立状态目录。真实 VM、模型服务、检查镜像、TLS 与 GitHub 权限尚未部署验收；模板存在不代表服务已经运行。
