# 本体开发验证记录

最新清理验收：移除 `/chat` 网页入口及重复 Gateway 快速探针；聊天测试 16 项、接口测试 8 项通过，固定 SDK 离线迁移/身份/skills/权限 8 项通过。手动 HTTP 验证已鉴权 `GET /chat` 返回 404、`GET /health` 返回 200；文档链接与 diff 检查通过。清理了安装缓存、调研片段、24 个合成测试目录、临时调试文件和项目字节码，保留运行依赖、原始验收报告和运行中的原生 profile。以下网页验收内容仅为历史记录，不代表仍提供网页功能。

日期：2026-09-20。对象：基线 `4e2fa78` 加本轮 Hermes 命令复用与原生历史变更，Python 3.12.13。本记录不证明后续变更。

## 已执行

| 检查 | 结果 |
| --- | --- |
| `python3.12 -m unittest discover -q` | 112 项通过，57.671 秒 |
| `python3.12 scripts/check_docs.py` | 相对链接、空白和 canonical 顺序通过 |
| `python3.12 -m compileall -q mikasa workers/hermes tests scripts` | 通过 |
| 原生协议与安装依赖 | 沿用已锁定的 Hermes 0.21.3、Anthropic 0.87.0；本轮未更改依赖和上游源码 |
| `git diff --check` 与 Git 可纳入文本逐文件空白检查 | 通过，覆盖未跟踪文件 |
| 官方命令兼容探针 | `probe_commands.py` 在真实固定 Hermes 上 17 项通过；无模型请求，覆盖别名、Unicode 参数、冲突与未开放参数 |
| 真实 HTTP 系统命令与会话 | GPT Responses → Claude Messages → GPT、原生历史、/v、/init 延后、/reset 新会话与幂等，17 项全部通过；见 [本轮证据](hermes-commands-evidence.json) |
| `python3.12 -m mikasa doctor` | 规则和 skill 路由加载；默认示例未配置模型符合预期。本机真实配置另检查为 valid，worker 可执行；不以此证明外部权限 |
| 网页脚本 | Node --check 通过；CLI/HTTP 新会话 ID 跟随回归通过，未运行真实浏览器视觉/点击验收 |
| 真实认证值字节扫描 | Git 可纳入文件和 runtime/state 未发现实际 Key 匹配；本地配置及本轮真实报告权限 0600 |
| 人格与工程 skill | GPT/Claude 真实聊天加载 persona，宿主规则/skill 指纹核对通过；工程任务路由由 doctor 和隔离回归验证，本轮未重复真实工程任务 |

历史执行进度、分页及工程工具验证见 [工具覆盖记录](HERMES_TOOLS_VALIDATION.md)，本轮未重复这些真实工程场景。历史验证另保留：[首次 Hermes/CCH 联调](HERMES_CCH_VALIDATION.md)、[聊天模型切换](CHAT_VALIDATION.md)。

本轮可复现命令：

```sh
python3.12 scripts/probe_commands.py --config config/local/hermes-cch.json
python3.12 scripts/probe_chat.py --config config/local/hermes-cch.json --target claude-opus-4-6 --slash --commands --report runtime/state/hermes-cch/native-commands-chat.json
```

原始本地报告不提交，脱敏摘要及原报告 SHA-256 见 [本轮证据](hermes-commands-evidence.json)。此前跨协议验证见 [历史证据](cross-protocol-evidence.json)，诊断和同协议联调见 [路由证据](cch-routing-evidence.json)。

## 证据范围

隔离回归真实执行临时 Git clone、文件应用、验证命令、失败修复、本地 commit、JSON worker 子进程、专用 FD 工具通信、超时/取消、线程清理、SQLite 事务与备份、HTTP 本地请求和鉴权。

Hermes 适配测试使用 SDK 夹具检查 system 参数、skill 指纹、官方插件注册接口、工具授权、Responses 模式与日志隔离。额外真实联调使用固定官方 Hermes、CCH Responses 和宿主工具执行，因此不把夹具通过当作真实工具兼容的唯一证据。GitHub REST、正式 Review 与外部发布仍模拟；Docker 测试仅验证启动参数和清理路径。

本轮新增：官方 registry/alias 与 model parser 调用、未开放命令参数拒绝、无凭据命令进程、错误响应失败关闭；`/new` 原子创建、幂等、暂停回滚、跨账号隔离、CLI/HTTP 跟随新 ID；模型历史经原生 conversation_history 传递，控制回执排除。普通聊天测试的命令回复是夹具，官方语义另由真实命令探针验证。真实 GPT/Claude 往返后仍能复述同一随机代号；新会话 history_messages=0 且未带回该代号，旧聊天仍可读取。

先前跨协议配置、来源隔离、协议检查、输出 JSON 围栏兼容与失败处理回归继续通过。真实 CCH 未注入失败或修改后台配置；default 分组仍缺网关侧证据。

既有执行进度回归：运行中进度可查询、模型失败/超时后的证据持久化、取消后旧进度拒绝写入、重试令牌隔离、runner 恢复保留阶段、写入失败先于工具副作用中止、验证和提交阶段记录。

既有上下文回归：搜索跨越 100 文件并在单文件超过 100 匹配时无遗漏续查；Unicode/CRLF 分段重组；不混合不同内容摘要的读取证据；非法游标、偏移、二进制与超大文件拒绝；PR 只读一页时保持 INCOMPLETE，完整覆盖后方可解除限制。

既有回归覆盖只读任务禁止写入与自选命令、读取固定 PR head、完整读取弥补初始上下文遗漏、保留原始空白与摘要、符号链接/敏感路径保护、Git 路径通配符不扩大暂存范围、工具调用预算与搜索截断、检查篡改后拒绝交付、关闭时取消检查与回收线程、模型伪造调用证据不可覆盖宿主记录、空 changes 必须有真实工具变更。

原有任务幂等、依赖、派发、不抢占人类任务、暂停、中断恢复、审批归属跨提交保留、过期批准失效、CI 缺失、重复发布阻止、发布歧义核对与负责人审批后完成等回归继续通过。

## 尚未验证

- 任意规模仓库、长上下文与长时间自主任务；模型响应标识也不能独立证明供应商实际底层模型。
- `Mikasa-0910` 真实仓库权限、远程推送、Issue/PR/Review/status 写入与 GitHub 分支保护。
- Linux VM、systemd、TLS、真实 Docker 检查镜像和部署恢复演练。
- 飞书机器人、Codex/Claude 可选执行器与完整上游工作流。原生记忆/skills 已在后续迁移阶段验收，见下文。

FluxCore 仍仅用于后续运行验收，本轮没有修改它，也没有发布外部内容。

## 原生运行迁移阶段

2026-09-20：当前 checkout 的 116 项 unittest 通过（56.961 秒），文档链接、compileall、diff 检查通过。原生命令探针 17 项、聊天跨协议 18 项、原生记忆/隔离状态 20 项、固定 SDK 离线迁移/权限 8 项通过。详细证据与未完成边界见 [原生运行验收](NATIVE_HERMES_VALIDATION.md)。

## 原生工程迁移阶段

2026-09-20：基线 `b874d82` 加本轮原生工程变更，126 项 unittest 通过；文档链接、compileall 和 diff 检查通过。真实原生容器工具 11 项、只读/强制取消 8 项通过；真实 CCH 的生命周期、同会话红绿修复、拆解、审查和长文件分页均通过。另一次完整生命周期使用真实 Docker 独立验收检查，生成本地提交并停在 awaiting_review。证据见 [原生工程记录](NATIVE_HERMES_VALIDATION.md) 与 [脱敏摘要](native-engineering-evidence.json)。

新增回归覆盖固定 head 导出、暂存版本修复、秘密/执行配置/链接排除、非法差异不部分应用、特殊文件/硬链接/权限拒绝、原生逐行覆盖、防止覆盖未导出文件、冻结容器后导入、清理失败保留快照、进度写入失败先于宿主副作用。固定 SDK 的旧库导入与 plugin/原生 skills 8 项离线检查再次通过。实际 CCH 密钥扫描在 Git 可纳入文件和本地运行数据中未发现匹配。

工程工具与原生人格/skills 是本次真实验证范围；此前 Gateway 的跨模型聊天、长期记忆和取消结果仍保留原报告，本阶段未把这些历史真实请求冒充重新执行。Linux VM、GitHub/飞书真实权限、CCH default 分组和 FluxCore 联合验收仍未完成。早先“未验证 Docker”的说明现仅适用于正式 VM 环境；本机原生工程和独立检查容器均已实际运行。
