# 验证

使用 `python3.12 -m unittest discover -v` 运行标准库 unittest。测试创建临时 Git 仓库，启动真正的 JSON worker 子进程和本地 HTTP 服务，GitHub 使用模拟适配器；不需要 token，不修改 FluxCore，不产生外部写入。

覆盖实现验证和提交、修复反馈、任务依赖与幂等、并发认领、中断恢复、取消、越界和符号链接拒绝、环境隔离、HTTP 鉴权、webhook 验签、过期审批、自审限制及发布歧义恢复。聊天测试还覆盖自然语言命令边界、会话归属、验证失败保留、切换重放、并发/暂停与上下文截断。文档检查使用 `python3.12 scripts/check_docs.py`。

隔离测试不能证明真实模型效果；本轮额外执行了 [Hermes/CCH 联调](../docs/HERMES_CCH_VALIDATION.md)。GitHub 账号权限、分支保护、真实 Docker 镜像和 systemd 部署仍待验收。
