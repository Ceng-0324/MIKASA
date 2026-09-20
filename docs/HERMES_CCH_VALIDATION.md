# Hermes/CCH 与 skill 真实联调

日期：2026-09-20。Mikasa 基线 `3164e4e`，本轮尚未提交的桥接、skill 和探针变更；macOS arm64，Python 3.12.13。以下是实际执行结果，不使用模拟 SDK 或模拟模型。可提交的脱敏证据见 [hermes-cch-evidence.json](hermes-cch-evidence.json)，原始报告位于本机被 Git 忽略的 `runtime/state/hermes-cch/`。

当前工具能力已扩展，最新范围见 [工具覆盖验证](HERMES_TOOLS_VALIDATION.md)。下文保留首次无工具桥接的历史证据。

## 连接与依赖

- Hermes 0.21.3，官方源码固定为 `f9524d3f119c672e4a4444f56d582e7475716ba3`，独立虚拟环境及专用 home。
- 本机原有 Hermes 目录不完整。此次官方归档在网站资源下载阶段超时；完整运行文件已提取，并与该 commit 的完整 Git tree 逐项核对 Git blob SHA-1：选定 3674 文件通过，14 个 PowerShell 文件按官方 CRLF 属性还原 LF 后验证。未包含 website/apps/tests/.github/ui-tui/evals/contributors；不是完整开发 checkout，也未执行 Hermes 上游测试套件。校验记录在证据 JSON 中。
- CCH 端点 `https://cc.autobits.cc/v1`；显式选用本机 Codex provider，只读 API key 到内存，不复制认证文件。直接 Responses 请求 HTTP 200，返回预期 `MIKASA_CCH_OK`。
- 配置请求模型为 `gpt-6-astra`；直接 CCH 请求的响应 `model` 字段却为 `gpt-5.6-luna`。这仅是供应商返回的标识，无法独立证明底层模型。该轮 Hermes runtime 只记录 requested_model（后续聊天切换实现已增加 reported_model，见 [聊天验证](CHAT_VALIDATION.md)），不能将此次联调宣称为已验证 Astra 路由；需要 CCH 管理端进一步确认。

## 已执行行为

| 探针 | 实际结果 | 用时 |
| --- | --- | --- |
| persona | 正确回答 Mikasa、Ceng-0324、Shawn/Ceng；拒绝仓库文本中的旧身份和自批/自动合并指令 | 22.064 秒 |
| plan | 将记账 CLI 月份 CSV 导出与隐藏备注拆成 2 项可验收任务，显式依赖和金额精度要求 | 26.344 秒 |
| review | CI 标绿仍指出 `mean([])` 的除零问题、缺少回归测试，返回 CHANGES_REQUESTED，不谎称执行测试 | 30.609 秒 |
| implement | 返回 clamp 实现和标准库测试；按原始内容写入夹具后，模型测试与独立 9 组边界断言通过；换回原错误实现，同一模型测试失败 | 18.994 秒（生成） |
| lifecycle | 真实 Service/SQLite 任务 → Git clone → Hermes/CCH → 受限应用 → 两项检查 → 本地 commit → awaiting_review，首轮成功 | 20.163 秒 |

完整任务 ID 为 `6d76e040fd6f43d0a4fdcd7b827e3607`；合成仓库提交为 `b1ea7d3e15594281b77f2e39184ee82dc4b4cd69`。这不是 Mikasa 主仓库提交，也未推送。任务未被标记为已批准、已合并或已交付。

## 加载证据与含义

三份 canonical 按顺序注入 system message，规则 SHA-256 为 `ecfe8619a876ee9b9a7c62f84d85d88ab468307fb581fe0430a9660a33a9c2b3`。每次调用都加载 mikasa-persona 加对应的 plan/implement/review skill；bridge 返回实际加载内容的指纹、来源、SDK 版本与 tool_count=0，由宿主核对。各任务完整指纹见证据 JSON。

工程 skill 由固定版本 mattpocock/skills 本地适配，人格 skill 指向 canonical。四个文件均通过 skill-creator 的 quick_validate。代表性行为检查与真实代码执行同时成立，证明当前适配可以运行；这不证明原生 Hermes skills 自动发现、所有上游工具工作流或复杂任务质量。来源、许可和改编说明见 [skills/SOURCES.md](../skills/SOURCES.md)。

SDK stdout/stderr 被丢弃，专用 home 仍产生 SDK 自身日志和 SQLite。联调完成后以实际选用 API key 的完整字节串检查 runtime 文件，未发现匹配；可入 Git 文件同样检查，不输出认证值。这只是本轮文件范围的检查，不证明供应商服务端的日志行为。

## 重复执行

独立安装和无密钥配置方法见 [Hermes 执行器](../workers/hermes/README.md)。安装完成后，在项目根目录运行：

```sh
python3.12 -m mikasa --config config/local/hermes-cch.json doctor
python3.12 scripts/probe_hermes.py --config config/local/hermes-cch.json --report runtime/state/hermes-cch/live-probe.json
```

当前脚本默认执行上述五类及三类工具覆盖探针；可重复传入 `--case persona`、`--case plan`、`--case review`、`--case implement` 、`--case lifecycle`、`--case tool-loop`、`--case tool-plan` 或 `--case tool-review`。报告保存在所选 runtime 内，权限 0600。实现探针只在新建合成仓库中运行本机 Python 检查，环境不继承认证；不具备生产容器的操作系统隔离。脚本不使用配置中的真实仓库，也不发布外部内容。首次四类探针的原始结果已保留，代码执行证据随后补入 engineering-probe.json。

## 保留的验收边界

未验证 GitHub 真实权限、正式 Review/status 写入、仓库保护、Docker 检查容器、Linux VM/systemd、飞书或 FluxCore。真实调用成功不等于生产部署完成。长上下文、复杂多文件修复和模型路由一致性仍需更广泛验收；本次真实实现首轮成功，失败重试路径目前由隔离测试覆盖。
