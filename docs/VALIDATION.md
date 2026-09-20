# 本体开发验证记录

日期：2026-09-20。对象：基线 `6530d04` 加本轮 Hermes 主动工具循环变更，Python 3.12.13。本记录不证明后续变更。

## 已执行

| 检查 | 结果 |
| --- | --- |
| `python3.12 -m unittest discover -q` | 75 项通过，37.524 秒 |
| `python3.12 scripts/check_docs.py` | 相对链接、空白和 canonical 顺序通过 |
| `python3.12 -m compileall -q mikasa workers/hermes tests scripts` | 通过 |
| 本地配置 `doctor` | canonical 与四个 skill 可读取、worker 可执行；仓库为空、GitHub token 未配置、发布关闭 |
| `git diff --check` 与 Git 可纳入文本逐文件空白检查 | 通过，覆盖未跟踪文件 |
| 真实认证值字节扫描 | 650 个 runtime/state 文件、85 个 Git 可纳入文件未发现匹配；本地配置及联调报告权限 0600 |
| Hermes/CCH 工具探针 | 主动拆解、固定 head 审查、同会话红绿修复与最终宿主复验均通过，见 [工具覆盖验证](HERMES_TOOLS_VALIDATION.md) |
| 无工具人格探针 | 正确回应身份、负责人称谓和独立审批边界，通过 |

历史验证单独保留：[首次 Hermes/CCH 联调](HERMES_CCH_VALIDATION.md)、[聊天模型切换](CHAT_VALIDATION.md)。本轮没有重新运行真实 HTTP 聊天切换，聊天相关隔离回归包含在上述 75 项中。

## 证据范围

隔离回归真实执行临时 Git clone、文件应用、验证命令、失败修复、本地 commit、JSON worker 子进程、专用 FD 工具通信、超时/取消、线程清理、SQLite 事务与备份、HTTP 本地请求和鉴权。

Hermes 适配测试使用 SDK 夹具检查 system 参数、skill 指纹、官方插件注册接口、工具授权、Responses 模式与日志隔离。额外真实联调使用固定官方 Hermes、CCH Responses 和宿主工具执行，因此不把夹具通过当作真实工具兼容的唯一证据。GitHub REST、正式 Review 与外部发布仍模拟；Docker 测试仅验证启动参数和清理路径。

新增回归覆盖只读任务禁止写入与自选命令、读取固定 PR head、完整读取弥补初始上下文遗漏、保留原始空白与摘要、符号链接/敏感路径保护、Git 路径通配符不扩大暂存范围、工具调用预算与搜索截断、检查篡改后拒绝交付、关闭时取消检查与回收线程、模型伪造调用证据不可覆盖宿主记录、空 changes 必须有真实工具变更。

原有任务幂等、依赖、派发、不抢占人类任务、暂停、中断恢复、审批归属跨提交保留、过期批准失效、CI 缺失、重复发布阻止、发布歧义核对与负责人审批后完成等回归继续通过。

## 尚未验证

- 任意规模仓库、长上下文与长时间自主任务；模型响应标识也不能独立证明供应商实际底层模型。
- `Mikasa-0910` 真实仓库权限、远程推送、Issue/PR/Review/status 写入与 GitHub 分支保护。
- Linux VM、systemd、TLS、真实 Docker 检查镜像和部署恢复演练。
- 飞书机器人、Codex/Claude 可选执行器、Hermes 原生记忆/skills 自动发现与完整上游工作流。

FluxCore 仍仅用于后续运行验收，本轮没有修改它，也没有发布外部内容。
