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

Hermes 工具、上下文自动发现、原生记忆、soul、trajectory 和后台 review 关闭。三个 canonical 规则及对应 [项目 skill](../../skills/README.md) 明确注入 system message。SDK stdout/stderr 不进入协议或持久化诊断；专用 home 仍有 SDK 自身日志/SQLite，联调后检查认证值是否落盘。工具数必须为零；GitHub/控制面 token 不传入 worker。

文件应用、验证、修复、提交和发布由宿主负责。默认最多修复 3 轮；超限保留工作区和阻塞状态。模型单轮最大输出 4096 tokens、最多 2 次内部迭代、预算 120 秒；复杂生成可能受到这些边界限制。worker 超时由宿主控制。

上下文优先保留规则与变更文件，被截断内容列入 omitted。缺少变更文件会阻止批准；当前没有交互式源码检索，合成小任务成功不证明任意规模仓库均可完成。运行证据中的 requested_model 只是请求值，reported_model 是 SDK 响应标识（没有观察到时为 null），两者均不独立保证供应商实际模型身份。聊天入口可以覆盖单次请求模型，详见 [聊天手册](../../docs/runbooks/CHAT.md)。
