# Hermes 集成

固定 NousResearch/hermes-agent `f9524d3f119c672e4a4444f56d582e7475716ba3`，版本 0.21.3。Mikasa 不修改上游、不重写工具循环。

## 安装

在项目根目录准备独立环境，目录须尚不存在：

```sh
git clone https://github.com/NousResearch/hermes-agent.git runtime/cache/hermes-source
git -C runtime/cache/hermes-source checkout --detach f9524d3f119c672e4a4444f56d582e7475716ba3
uv --cache-dir runtime/cache/uv venv --python python3.12 runtime/cache/hermes-venv
uv --cache-dir runtime/cache/uv pip install --python runtime/cache/hermes-venv/bin/python -r workers/hermes/requirements-tested.txt
uv --cache-dir runtime/cache/uv pip install --python runtime/cache/hermes-venv/bin/python --no-deps --editable runtime/cache/hermes-source
```

依赖快照已用于 macOS arm64 与 Ubuntu arm64/Python 3.12，其他平台需复验。未执行上游全局安装器。原生工具还可能需要 gh、Node、浏览器、Docker 或远端服务凭据；实际可用性用原生 tools 检查。

专用 VM 的搜索、语音和 MCP 可选依赖见 [requirements-tools.txt](requirements-tools.txt)，在核心快照之后安装。浏览器、FFmpeg 和原生搜索后端的准备见[工作机手册](../../deploy/vm/README.md)。工具注册或依赖检查通过不代表对应外部服务已经连通。

## 配置

本地 JSON 的 worker 区块保留名称作为部署配置兼容，只管理 Hermes 路径和 CCH 来源：

```json
{
  "hermes_source": "runtime/cache/hermes-source",
  "native_python": "runtime/cache/hermes-venv/bin/python",
  "model_source": {"type": "codex"},
  "env_allowlist": []
}
```

Codex/Claude 来源仅显式只读本机配置；VM 使用环境引用，不复制认证文件。GPT Responses 与 Claude Messages 由 Hermes 官方 transport 处理；Key 只经环境注入。完整配置见 [CCH](../../docs/runbooks/CCH.md)。

## 原生工程

`mikasa engineer --cwd DIR -- chat` 直接进入官方总入口，-- 后透传所有原生参数。工具、终端 backend、skills、插件、MCP、委派、后台进程、会话、Kanban、Cron 和预算由 Hermes 管理。独立工程 profile 不继承聊天工具子集，memories 链接同账号聊天，配置刷新保留原生偏好。

聊天 Gateway 同样直接使用原生完整工具集，可在原会话执行工程任务并反馈进度与结果。各入口共用系统账号、依赖和原生 gh 认证，保留各自会话与工具偏好。没有受限快照、无网容器、文件黑名单、固定任务工具集合、worker JSON 或宿主最终验收/提交。默认 local backend 的工程能力等于同账号原生 Hermes；外部能力仍需依赖和平台权限。

聊天默认显示新的工具阶段并合并同类进度，长任务每 60 秒通过原生 Gateway 提醒仍在执行；可在 profile 的 `display.tool_progress`、`agent.gateway_notify_interval` 和平台覆盖中调整。提醒不等于终端 stdout 逐行直播；长命令使用 Hermes 原生后台进程和 `process_manage` 查看输出，模型在工具调用间反馈已观察到的进展。

更新身份或协作提示并重启入口时，插件通过原生 SessionDB 清除过期的 Mikasa 系统提示缓存，下次请求重新组装；消息历史、会话 ID 和持久记忆保留，无需 `/new`。文件同步和模型实际加载分别由 `policy-loaded.json` 摘要与 `native-evidence.jsonl` 请求证据检查。

## 保留的集成文件

| 文件 | 职责 |
| --- | --- |
| native_engineer.py | 官方 hermes_cli.main.main 工程总入口 |
| native_cli.py / native_gateway.py | 聊天 CLI/Gateway 生命周期与加载检查 |
| plugin/ | 身份/协作提示及加载证据；不注册工具拦截器 |
| profile_config.py | 保留原生偏好、刷新受管 provider 与身份 skill |
| backup_adapter.py | Hermes SQLite 快照及恢复路径处理 |
| feishu_probe.py / weixin_login.py | 官方平台探针与扫码，凭据留本机 |

同一聊天 profile 的入口互斥，工程 profile 可独立工作。方法 skills 不包含 worker 输出协议。固定源码、身份、记忆、工具和真实模型验收范围见 [验证边界](../../docs/VALIDATION.md)。
