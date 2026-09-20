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
  "env_allowlist": []
}
```

同时设置顶层 `runtime` 为 `runtime/state/hermes-cch`。本地配置权限设为 0600。显式选择 `codex` 才只读 `~/.codex/config.toml` 中选定 provider、model、base_url、wire_api；API key 从对应 env_key、配置 bearer token 或 `auth.json` 的 OPENAI_API_KEY 读取到内存。可用 `config_path`/`auth_path` 指定来源，不复制文件，不迁移 OAuth，不输出 key。Responses 映射为 Hermes 的 `codex_responses`。

默认 `model_source.type=environment` 不读取个人工具配置。生产通过专用环境注入 `MIKASA_MODEL`、`MIKASA_MODEL_BASE_URL`、`MIKASA_MODEL_API_KEY`、`MIKASA_MODEL_API_MODE`，并在 `worker.env_allowlist` 中列出；API 模式支持 `chat_completions`（默认）、`codex_responses` 和 `anthropic_messages`。home/source 也可用 `HERMES_HOME`/`MIKASA_HERMES_SOURCE` 白名单环境变量设置。专用 home 不可等于个人 home 或 `~/.hermes`。

跨 GPT/Claude 的配置来源由 `worker.model_routes` 选择，示例见 [CCH 手册](../../docs/runbooks/CCH.md)。工程和旧 API 按完整 ID 或前缀匹配；原生 CLI 将默认模型及显式 models 生成精确别名，由 Hermes 选择对应 provider，不复刻前缀解析。`model_source.type=claude` 显式只读 `~/.claude/settings.json` 或指定 `config_path` 的 env.ANTHROPIC_BASE_URL、env.ANTHROPIC_AUTH_TOKEN（优先）/env.ANTHROPIC_API_KEY，使用 Hermes 原生 `anthropic_messages`。不执行 apiKeyHelper，不读取 OAuth/keychain，不合并其他 Claude 设置文件或继承未经允许的全局认证变量。`opus[1m]` 等客户端别名不作为模型 ID；切换命令传入完整网关模型名。默认请求模型首次来自 worker.model_source；原生 CLI 可以用 `--global` 保存自己的默认选择，models 不是可用性承诺。

Anthropic 协议依赖 Hermes 官方声明的 `anthropic==0.87.0`，已纳入安装快照；缺失时返回 missing_dependency。请求保持 provider=custom，避免触发原生 Anthropic OAuth 或个人凭据回退，SDK 请求、工具和响应转换由 Hermes 官方 transport 完成。

三种模型来源使用同一配置校验：完整模型 ID、有效 HTTP(S) 端点、无空白 API key 和受支持的协议；端点不得嵌入认证、查询参数或片段。`doctor` 输出配置状态、端点 origin（不含路径）、请求模型和协议，不输出认证值或认证文件路径。显式 `doctor --probe-model` 才通过当前 worker 发起一次无工具聊天验证，不创建聊天记录或工程任务；探针失败返回非零退出码。详细步骤见 [CCH 诊断](../../docs/runbooks/CCH.md)。

## 执行协议与限制

bridge 是单次进程：stdin 接收 version=1、rules、instruction、skills、task、context、output_contract；stdout 返回 `{"version":1,"result":{...},"runtime":{...}}`。result 是任务对应严格 JSON；runtime 包含 SDK 版本、请求模型、通过公开 post_api_request hook 观察到的响应模型标识 reported_model、API 模式、规则/system/skill SHA-256、来源和工具数。宿主验证规则、skill 指纹及工具数并保存到任务 execution，不能用模型自述代替加载证据。

模型原始回复允许整个 JSON 文档包在一个完整 JSON 代码围栏内；bridge 仅剥除这层外壳，不从说明文字中搜索 JSON，不修复畸形内容，不接受多段代码块。字段和实际工具副作用继续由宿主校验。响应 API 模式还必须与宿主选定路由一致。

失败时 bridge 以非零码退出，stdout 只返回 `{"version":1,"error":{"code":"固定错误码"}}`。使用官方 `api_request_error` hook 的结构化 reason/status 分类；不复制 error.message、request 或原始 SDK 异常。宿主再次按固定词表校验，并将可识别的 `error_code` 写入失败进度。恢复成功后的 API 错误不会继续当作最终失败；未知原因仍为泛化错误，不猜测网关故障来源。

工程工作区使用 Hermes 原生 `read_file/search_files/write_file/patch/terminal`、MEMORY/USER、SOUL 和 skills.auto_load。bridge 只适配结构化任务交付、模型来源、工具授权与宿主证据；推理和工具循环由官方 AIAgent harness 执行，上游源码不修改。聊天另由原生 Gateway 持久化会话，工程调用不重建聊天上下文。

Mikasa 将当前暂存树（实现/修复）或固定 PR head（计划/审查）的普通 UTF-8 文件导出到隔离快照；不导出凭据、链接、二进制、`.git`、`.hermes` 等执行配置。单文件最多 1 MB，总计最多 5000 文件/50 MB。省略项明确保留为未覆盖范围。原生终端使用 Docker，无网络、只读根目录、资源限制，挂载快照、受信任 skills 及 Hermes 原生的任务附件/缓存目录；不挂载账号记忆、SessionDB 或 profile 配置，模型认证保留在宿主 SDK。只读任务的快照挂载为 ro，不授权 write_file/patch。

默认工程镜像固定为 Python 3.12 slim 的 digest，见 [snapshot 配置](../../mikasa/sandbox.py)。需预先启动 Docker 并拉取镜像；其他语言可在仓库配置 `agent_image`，镜像应预装依赖。它与 `check_image` 分开：前者用于原生探索，后者执行独立验收。离线容器内不能临时联网安装包。

仅 `mikasa_run_checks` 是自研业务工具，不能指定命令。执行时宿主暂停本任务容器，验收并导入快照差异，再运行既定检查；随后恢复容器供模型修复。最终先清理本任务容器，再导入最后差异、独立复验并创建本地提交。规则、认证、执行配置、符号/硬链接、特殊文件、超大产物或权限变更均不能进入真实工作区。检查修改 Git 索引、HEAD 或暂存内容会拒绝交付。超时或取消也清理任务容器；不清理他人的 Docker 资源。

原生 `post_tool_call` hook 经专用 FD 将实际工具结果交给宿主。宿主把 read_file 的带行号内容逐行对照固定快照，累积相同 PR head 的完整覆盖证据；仅读尾页、搜索命中或模型宣称读过不能消除审查限制。SQLite 持久化元数据，不保存读取正文、shell 命令或认证值。真实输出协议的失败诊断只记录异常类型和栈位置，不复制 SDK 错误正文。

工程 profile 位于 `runtime/engineering/<task-id>`，SessionDB 按任务隔离；每轮从稳定根会话恢复原生工具历史及压缩后续。memories 目录直接链接提交账号的原生 MEMORY/USER，由 Hermes 负责锁、原子写入与加载；不复制聊天正文。任务 profile 绑定可信 actor、task-id 和 repo，同任务进程互斥。旧任务记忆留在 `memories.legacy`，旧随机会话仍保留在原 SessionDB，均不自动合并。SOUL 和任务对应 skills 由 canonical 与受信任 manifest 生成，pre_api_request 验证实际请求内的完整身份、规则与 skill 正文。只准加载本任务的可信 skills，不开放 skill_manage、委派、浏览器、外部消息或发布工具。每次至多 24 次原生迭代、128 个工具证据事件；时间仍由 worker.timeout 限制。

持久根会话为 `mikasa-task-<task-id>`；每轮随机 `run_id` 单独传给原生工具作为 task_id，容器按该 ID 标记、验收及清理。Python 启动路径保留虚拟环境符号链接，避免切换到缺少 SDK 的基础解释器。续话、记忆、真实 Docker 与固定 SDK 验证见 [0008](../../docs/decisions/0008-engineering-state.md)。

工程返回严格 JSON，原生实现必须通过工具修改快照并返回 `changes: []`。宿主暂保留任务、固定 revision、检查和发布适配；审查分工由 Agent 依据规则与记忆判断，不再由宿主归属分类或指定审批人引擎执行。没有工作区的诊断调用仍为无工具结构化请求，不代表工程执行。

每次任务认领只调用一次 worker；Hermes 在原生工具循环中自行读取失败、修改并重跑 `mikasa_run_checks`。宿主结束后独立验收一次，失败返回 blocked、保留结果与工作区，不启动新的 Agent 修复轮。显式 retry 恢复同任务原生历史，并传递上次最终验收结果；新工作区不自动复制旧失败改动。旧 `worker.max_attempts` 仅供 v1 配置读取兼容，doctor 明确报告已停用。详见 [0009](../../docs/decisions/0009-native-repair-loop.md)。

可配置的第三方 worker 暂保留 version=1 的宿主 RPC 协议（旧 mikasa_list/read/search/apply）；它是已公开进程协议的兼容对象，内置 Hermes 工程路径不使用它。待第三方协议升级、调用方与协议测试一起迁移后删除该兼容实现，不提供 Hermes 新旧后端切换开关。

原生容器、工程循环与分页证据见 [原生验收](../../docs/NATIVE_HERMES_VALIDATION.md)。旧自研工具的验证保留为 [历史记录](../../docs/HERMES_TOOLS_VALIDATION.md)，不能当作当前实现的验收结果。

## 命令与会话接口

终端 `mikasa chat` 由 `native_cli.py` 调用官方 `cli.main()`；TTY、输入循环和完整命令分派由 Hermes 拥有。身份/工程规则、Mikasa plugin 与 persona 加载检查在启动前完成；`/model` 使用 Hermes providers/model_aliases 和官方 scope 语义，`/new` 确认后新建会话，`/resume` 恢复原生会话。固定版本 `/new` 恢复默认模型的路径对自定义 CCH provider 有上游限制，当前保留原模型；详见 0007。

HTTP 和 `chat --message` 暂留既有进程协议 `{"version":1,"operation":"command","text":"/model ..."}`，返回 `version` 与 `result`（name、kind、target、reply）。该命令解析进程只接收专用 home 和源码位置，不读取模型配置、不注入模型/平台认证。bridge 在模型环境校验之前调用官方命令注册表、model 参数解析器及 version 执行器；错误仍返回固定错误信封，不转交模型。此适配将在原生渠道接管既有 API 的鉴权、幂等和取消并迁移调用方后删除。

HTTP 聊天使用原生 Gateway 的 SessionDB、运行幂等和取消；Mikasa 只保存账号与 session/run 引用。API 的 `/new` 明确保留模型和账号长期记忆，客户端须跟随返回的新 chat_id。见 [原生运行决定](../../docs/decisions/0004-native-hermes-runtime.md) 和 [原生 CLI 决定](../../docs/decisions/0007-native-cli.md)。

不耗模型额度的兼容探针：`python3.12 scripts/probe_commands.py --config config/local/hermes-cch.json`。真实跨协议与新会话验收使用 `probe_chat.py --slash --commands`，其余参数见 [验证记录](../../docs/VALIDATION.md)。

原生 CLI 的本地 SDK 验收：`python3.12 scripts/probe_native_cli.py`，使用一次性 profile、本机模型目录和合成 Key，验证官方命令分派、跨协议路由、历史恢复、偏好重载与入口启动退出，不调用真实模型。

## 原生聊天 Gateway

HTTP/单条消息调用未修改的 `gateway.run`、`/api/sessions` 和 `/v1/runs`。账号 profile 位于 runtime/native，与原生 CLI 共用会话与记忆；CLI/Gateway 通过同一进程锁互斥。`native_gateway.py` 校验 Mikasa plugin 成功加载后启动官方生命周期。Mikasa 原生适配不实现另一套 agent loop。

Gateway 需要固定版本的额外依赖：

```sh
uv --cache-dir runtime/cache/uv pip install --python runtime/cache/hermes-venv/bin/python aiohttp==3.14.3 lark-oapi==1.6.8
```

`worker.native_python` 可指定 CLI/Gateway 解释器，默认 runtime/cache/hermes-venv/bin/python；`worker.hermes_source` 指向固定源码。配置沿用现有 model_source/model_routes，所有已配置来源须可读取。生成的 Hermes providers 只包含 Key 环境变量名，无实际 Key。`profile_config.py` 在该解释器中解析 YAML/JSON，刷新集成配置并保留 Hermes 原生偏好；格式错误不覆盖文件。当前模型工具只启用 memory 与 skills，plugin 拒绝未授予的工具；本地 CLI 系统命令仍采用原生行为，这不是操作系统沙箱。

`bridge.py` 保留工程结构化协议、原生 harness 配置和交付证据适配；文件、搜索、修改、shell、任务续话与账号长期记忆已使用官方原生能力。审批引擎与外层修复循环已移除；任务队列和调度仍待迁入 Kanban。
