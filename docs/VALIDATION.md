# 本体开发验证记录

日期：2026-09-20。对象：基线 `3164e4e` 加本轮尚未提交的 Hermes/CCH、skill 与聊天模型切换变更，Python 3.12.13。本记录不证明后续变更。

## 已执行

| 检查 | 结果 |
| --- | --- |
| `python3.12 -m unittest discover -v` | 64 项通过，27.416 秒 |
| `python3.12 scripts/check_docs.py` | 相对链接、空白和 canonical 顺序通过 |
| `python3.12 -m compileall -q mikasa workers/hermes tests scripts` | 通过 |
| 本地配置 `doctor` | canonical 与四个 skill 可读取、worker 可执行；仓库为空、GitHub token 未配置、发布关闭 |
| skill-creator `quick_validate.py` | 四个项目 skill 均通过 |
| `git diff --check` 与 Git 可纳入文本逐文件空白检查 | 通过，覆盖未跟踪文件 |
| 真实认证值字节扫描 | 136 个 runtime 文件、81 个 Git 可纳入文件未发现匹配；本地配置及报告权限 0600 |
| 聊天模型切换 | 真实 HTTP/Hermes/CCH 下切换、恢复、历史连续性及幂等通过，见 [聊天验证](CHAT_VALIDATION.md) |
| 网页脚本 | Node 语法检查通过；未做浏览器视觉验收 |
| Hermes/CCH 真实探针 | 人格、拆解、审查、代码实现、完整任务链全部通过，详见 [联调记录](HERMES_CCH_VALIDATION.md) |

## 测试证据的范围

隔离回归真实执行：临时 Git 仓库 clone、文件应用、验证命令、失败反馈修复、本地 commit、JSON worker 子进程、超时和取消、SQLite 并发事务与备份、HTTP 本地请求和鉴权。

隔离回归模拟边界：GitHub REST、正式 Review 和外部发布使用模拟响应；Hermes 适配测试使用 SDK 夹具检查真实 system 参数、Responses 模式、工具禁用、输出换行与日志隔离；Docker 测试只验证启动参数和清理路径。

额外真实联调：固定 Hermes 0.21.3、CCH Responses、模型输出与实际 skill 注入；生成测试在正确代码通过，在原错误实现失败，独立边界断言通过。完整 Service 任务首轮验证成功并提交合成仓库，停在 awaiting_review。没有修改 FluxCore，也没有发布消息、Issue、PR、Review 或 commit status。

覆盖：任务幂等、依赖、派发、不抢占人类任务、暂停、中断恢复、越界路径/符号链接/规则文件拒绝、模型输出契约、验证索引一致性、webhook 签名和重放、审批归属跨提交保留、过期批准失效、CI 缺失、审查遗漏、重复发布阻止、发布歧义核对、负责人审批与合并后完成，以及 skill 来源/路径/指纹和显式本地模型配置读取。

## 尚未验证

- CCH 实际路由为 Astra：请求 gpt-6-astra，直接响应 model 却为 gpt-5.6-luna；不能用请求名证明实际模型身份。复杂多文件任务与大上下文质量尚未验收。
- `Mikasa-0910` 的真实仓库权限、远程推送、Issue/PR/Review/status 写入及 GitHub 分支保护。
- 目标 Linux VM、systemd 单元、TLS、真实 Docker 检查镜像和部署备份恢复演练。
- 飞书原生机器人、Codex/Claude 可选执行器、Hermes 原生 skill 自动发现及完整上游工程工作流。

下一阶段是平台权限和部署环境验收。FluxCore 仅作为本体完成后的运行测试仓库。
