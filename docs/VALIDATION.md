# 本体开发验证记录

日期：2026-09-20。对象：本地未提交工作区，Python 3.12.13。仓库尚无首次 commit，因此没有可引用的提交 SHA；本记录不能证明后续变更。

## 已执行

| 检查 | 结果 |
| --- | --- |
| `python3.12 -m unittest discover -v` | 46 项通过，最后一轮耗时 23.822 秒 |
| `python3.12 scripts/check_docs.py` | 相对链接、空白和 canonical 顺序通过 |
| `python3.12 -m compileall -q mikasa workers/hermes tests` | 通过 |
| `python3.12 -m mikasa doctor` | CLI 正常；明确报告仓库/worker/真实 token 未配置，发布关闭 |
| `python3.12 -m mikasa --help` | 操作入口正常 |
| Python 文件逐文件 AST/空白检查 | 21 个文件通过，包含未跟踪文件 |
| `git diff --check` | 通过；因文件尚未跟踪，此项不替代逐文件检查 |

## 测试证据的范围

真实执行：临时 Git 仓库 clone、文件应用、验证命令、失败反馈修复、本地 commit、JSON worker 子进程、超时和取消、SQLite 并发事务与备份、HTTP 本地请求和鉴权。

模拟边界：GitHub REST、正式 Review 和外部发布使用模拟响应；Hermes 桥接使用与核对接口相容的 SDK 夹具；Docker 检查验证启动参数和清理路径，没有运行真实检查容器。没有修改 FluxCore，也没有发布消息、Issue、PR、Review 或 commit status。

覆盖：任务幂等、依赖、派发、不抢占人类任务、暂停、中断恢复、越界路径/符号链接/规则文件拒绝、模型输出契约、验证索引一致性、webhook 签名和重放、审批归属跨提交保留、过期批准失效、CI 缺失、审查遗漏、重复发布阻止、发布歧义核对、负责人审批与合并后完成。

## 尚未验证

- 固定版本 Hermes 的实际安装、CCH 模型端点和推理效果；需要专用模型配置与凭据。
- `Mikasa-0910` 的真实仓库权限、远程推送、Issue/PR/Review/status 写入及 GitHub 分支保护。
- 目标 Linux VM、systemd 单元、TLS、真实 Docker 检查镜像和备份恢复演练。
- 飞书原生机器人、Codex/Claude 可选执行器和第三方 skills 尚未实现或接入，沿用原规划的后续讨论边界。

下一阶段是外部运行条件接入与验收。FluxCore 只在本体完成后作为运行测试仓库，不作为本次实现目标。
