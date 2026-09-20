# Hermes 执行器

固定源码：NousResearch/hermes-agent `f9524d3f119c672e4a4444f56d582e7475716ba3`，包版本 0.21.3。真实 CCH Responses、人格/工程 skill 和完整任务链已通过合成任务联调，证据与限制见 [联调记录](../../docs/HERMES_CCH_VALIDATION.md)。

## 独立安装

在项目根目录准备独立环境；目标目录须尚不存在。正常安装方式如下，本机安装来源校验细节见联调记录。

```sh
git clone https://github.com/NousResearch/hermes-agent.git runtime/cache/hermes-source
git -C runtime/cache/hermes-source checkout --detach f9524d3f119c672e4a4444f56d582e7475716ba3
uv --cache-dir runtime/cache/uv venv --python python3.12 runtime/cache/hermes-venv
uv --cache-dir runtime/cache/uv pip install --python runtime/cache/hermes-venv/bin/python -r workers/hermes/requirements-tested.txt
uv --cache-dir runtime/cache/uv pip install --python runtime/cache/hermes-venv/bin/python --no-deps --editable runtime/cache/hermes-source
```

[requirements-tested.txt](requirements-tested.txt) 是本次 macOS arm64/Python 3.12 的依赖版本快照；不是所有平台通用锁文件，Linux VM 需独立验证。没有运行上游全局安装器。

## 配置与认证

复制项目配置示例到 `config/local/hermes-cch.json` 后，将 worker 配置为下面内容，并把 `/absolute/mikasa` 替换为项目实际绝对路径。其余配置保持仓库为空、发布关闭。

```json
{
  "command": ["/absolute/mikasa/runtime/cache/hermes-venv/bin/python", "/absolute/mikasa/workers/hermes/bridge.py"],
  "hermes_source": "runtime/cache/hermes-source",
  "home": "runtime/state/hermes-cch/home",
  "model_source": {"type": "codex"},
  "timeout": 240,
  "max_attempts": 3,
  "env_allowlist": []
}
```

同时设置顶层 `runtime` 为 `runtime/state/hermes-cch`。本地配置权限设为 0600。显式选择 `codex` 才只读 `~/.codex/config.toml` 中选定 provider、model、base_url、wire_api；API key 从对应 env_key、配置 bearer token 或 `auth.json` 的 OPENAI_API_KEY 读取到内存。可用 `config_path`/`auth_path` 指定来源，不复制文件，不迁移 OAuth，不输出 key。Responses 映射为 Hermes 的 `codex_responses`。

默认 `model_source.type=environment` 不读取个人工具配置。生产通过专用环境注入 `MIKASA_MODEL`、`MIKASA_MODEL_BASE_URL`、`MIKASA_MODEL_API_KEY`、`MIKASA_MODEL_API_MODE`，并在 `worker.env_allowlist` 中列出；API 模式为 `chat_completions`（默认）或 `codex_responses`。home/source 也可用 `HERMES_HOME`/`MIKASA_HERMES_SOURCE` 白名单环境变量设置。专用 home 不可等于个人 home 或 `~/.hermes`。

## 执行协议与限制

bridge 是单次进程：stdin 接收 version=1、rules、instruction、skills、task、context、output_contract；stdout 返回 `{"version":1,"result":{...},"runtime":{...}}`。result 是任务对应严格 JSON；runtime 包含 SDK 版本、请求模型、通过公开 post_api_request hook 观察到的响应模型标识 reported_model、API 模式、规则/system/skill SHA-256、来源和工具数。宿主验证规则、skill 指纹及工具数并保存到任务 execution，不能用模型自述代替加载证据。

Hermes 通过官方 `PluginContext.register_tool` 加载宿主提供的工具。`plan/review` 获得 `mikasa_list_files`、`mikasa_read_file`、`mikasa_search`；`implement` 另获得 `mikasa_apply_changes`、`mikasa_run_checks`。没有工作区的直接探针与聊天仍无工具。固定上游默认通过 Tool Search 渐进披露插件工具，所以模型可见的是 `tool_search/tool_describe/tool_call`；`runtime.tools` 记录这个入口集合，`granted_tools` 记录实际授权集合，宿主核对两者。

工具经继承的专用 socket FD 请求宿主，串行处理，不能选择其他工作区、任意命令或扩展权限。审查读取固定 PR head 的 Git blob，实现读取当前工作树。文件应用沿用规则、凭据、执行配置和符号链接保护；检查只接受配置中的命令，生产仍需隔离镜像。检查修改 Git 索引、HEAD 或已暂存内容会中止交付。超时/取消会结束模型进程组、取消正在执行的检查并关闭通道。`runtime.tool_events` 由宿主记录工具名称、路径、读取版本/摘要与检查退出码，不采信模型自报。运行中宿主同步把工具开始/完成事件写入 SQLite；即使模型未返回最终 JSON，已执行证据仍可通过任务 events 查询。

上下文自动发现、原生记忆、soul、trajectory 和后台 review 关闭。三个 canonical 规则及对应 [项目 skill](../../skills/README.md) 明确注入 system message。SDK stdout/stderr 不进入协议或持久化诊断；专用 home 仍有 SDK 自身日志/SQLite，联调后检查认证值是否落盘。GitHub/控制面 token 不传入 worker。

有工作区时，Hermes 最多 20 次内部迭代、64 次宿主工具请求、单次输出 8192 tokens，时间预算遵守 `worker.timeout`。它可在一次会话内探索、应用修改、观察检查失败并修复。工具已应用最终修改时返回 `changes: []`，宿主要求真实变更证据；也支持直接返回 `changes` 的结构化文件交付。宿主最终仍独立执行配置检查，再创建本地提交并停在 `awaiting_review`。会话外失败修复上限仍由 `max_attempts` 控制，默认 3 轮；每轮保存 execution。聊天无工作区，保持 2 次迭代、4096 tokens。

初始上下文优先保留规则与变更文件，被截断内容列入 omitted。Hermes 可分段读取最多 1000000 字节的 UTF-8 文件，每页最多 16000 个 Unicode 字符，按 `next_offset` 继续；内容 SHA-256 与已读区间由宿主记录，`complete=true` 表示同一内容已完整覆盖。列表每页 200 项；搜索每次最多扫描 100 个文件/约 1 MB，返回最多 100 个匹配，按宿主生成的 `next_cursor` 可继续到后续文件或同一文件的后续匹配。游标绑定查询与仓库版本，应用变更后失效；跳过的文件明确报告。宿主只接受同一 PR head 的成功完整读取证据来消除未读变更限制；搜索命中不等于完整读取。尚未读到的变更文件仍阻止批准。

真实工具循环证据与复现命令见 [工具覆盖验证](../../docs/HERMES_TOOLS_VALIDATION.md)。小型合成任务成功不证明任意规模仓库都可完成。requested_model 是请求值，reported_model 是 SDK 响应标识（未观察到时为 null），均不能独立保证供应商底层模型身份。聊天切换见 [聊天手册](../../docs/runbooks/CHAT.md)。
