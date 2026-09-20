# 本体开发验证记录

日期：2026-09-20。对象：基线 `471e7c0` 加本轮 CCH 配置与诊断变更，Python 3.12.13。本记录不证明后续变更。

## 已执行

| 检查 | 结果 |
| --- | --- |
| `python3.12 -m unittest discover -q` | 96 项通过，53.767 秒 |
| `python3.12 scripts/check_docs.py` | 相对链接、空白和 canonical 顺序通过 |
| `python3.12 -m compileall -q mikasa workers/hermes tests scripts` | 通过 |
| 本地配置 `doctor --probe-model` | 真实 Hermes → CCH Responses 通过，请求/响应均为 gpt-6-astra；配置 valid，分组 unverified；仓库为空、GitHub token 未配置、发布关闭 |
| `git diff --check` 与 Git 可纳入文本逐文件空白检查 | 通过，覆盖未跟踪文件 |
| 官方 Hermes 错误钩子 | 临时 loopback HTTP 服务返回 401；官方 SDK 发出 2 次请求后桥接输出 auth，未调用 CCH，未使用真实凭据 |
| 真实 HTTP 聊天切换 | gpt-6-astra → gpt-5.6-luna → 恢复默认，8 项检查全部通过：模型切换、后续请求、上下文保留、幂等重放与持久化；见 [本轮路由证据](cch-routing-evidence.json) |
| 真实认证值字节扫描 | Git 可纳入文件和 runtime/state 未发现实际 Key 匹配；本地配置及两份联调报告权限 0600 |
| 人格与工程 skill | 真实连接探针加载 persona，宿主指纹核对通过；四个 skill 可读取，工程任务路由由隔离回归验证 |

历史执行进度、分页及工程工具验证见 [工具覆盖记录](HERMES_TOOLS_VALIDATION.md)，本轮未重复这些真实工程场景。历史验证另保留：[首次 Hermes/CCH 联调](HERMES_CCH_VALIDATION.md)、[聊天模型切换](CHAT_VALIDATION.md)。

本轮真实聊天复现：`python3.12 scripts/probe_chat.py --config config/local/hermes-cch.json --target gpt-5.6-luna --report runtime/state/hermes-cch/routing-chat-probe.json`。原始本地报告不提交，脱敏摘要及原报告 SHA-256 保存在上述路由证据中。

## 证据范围

隔离回归真实执行临时 Git clone、文件应用、验证命令、失败修复、本地 commit、JSON worker 子进程、专用 FD 工具通信、超时/取消、线程清理、SQLite 事务与备份、HTTP 本地请求和鉴权。

Hermes 适配测试使用 SDK 夹具检查 system 参数、skill 指纹、官方插件注册接口、工具授权、Responses 模式与日志隔离。额外真实联调使用固定官方 Hermes、CCH Responses 和宿主工具执行，因此不把夹具通过当作真实工具兼容的唯一证据。GitHub REST、正式 Review 与外部发布仍模拟；Docker 测试仅验证启动参数和清理路径。

本轮新增：环境白名单与 Codex 来源统一校验、非法端点/协议/凭据在 worker 启动前拒绝、诊断不暴露密钥和端点路径、探针显式执行及失败退出码、403 与 WAF/认证区分、结构化错误白名单、失败进度与聊天错误码、切换失败保留状态与幂等重放、API 恢复后清除旧错误。真实 CCH 不注入失败、不修改后台配置；default 分组仍缺网关侧证据。

既有执行进度回归：运行中进度可查询、模型失败/超时后的证据持久化、取消后旧进度拒绝写入、重试令牌隔离、runner 恢复保留阶段、写入失败先于工具副作用中止、验证和提交阶段记录。

既有上下文回归：搜索跨越 100 文件并在单文件超过 100 匹配时无遗漏续查；Unicode/CRLF 分段重组；不混合不同内容摘要的读取证据；非法游标、偏移、二进制与超大文件拒绝；PR 只读一页时保持 INCOMPLETE，完整覆盖后方可解除限制。

既有回归覆盖只读任务禁止写入与自选命令、读取固定 PR head、完整读取弥补初始上下文遗漏、保留原始空白与摘要、符号链接/敏感路径保护、Git 路径通配符不扩大暂存范围、工具调用预算与搜索截断、检查篡改后拒绝交付、关闭时取消检查与回收线程、模型伪造调用证据不可覆盖宿主记录、空 changes 必须有真实工具变更。

原有任务幂等、依赖、派发、不抢占人类任务、暂停、中断恢复、审批归属跨提交保留、过期批准失效、CI 缺失、重复发布阻止、发布歧义核对与负责人审批后完成等回归继续通过。

## 尚未验证

- 任意规模仓库、长上下文与长时间自主任务；模型响应标识也不能独立证明供应商实际底层模型。
- `Mikasa-0910` 真实仓库权限、远程推送、Issue/PR/Review/status 写入与 GitHub 分支保护。
- Linux VM、systemd、TLS、真实 Docker 检查镜像和部署恢复演练。
- 飞书机器人、Codex/Claude 可选执行器、Hermes 原生记忆/skills 自动发现与完整上游工作流。

FluxCore 仍仅用于后续运行验收，本轮没有修改它，也没有发布外部内容。
