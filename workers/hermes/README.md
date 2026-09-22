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

## 配置

本地 JSON 的 worker 区块保留名称作为部署配置兼容，只管理 Hermes 路径、CCH 来源及 HTTP 等待超时：

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

没有受限快照、无网容器、文件黑名单、固定任务工具集合、worker JSON 或宿主最终验收/提交。默认 local backend 的工程能力等于同账号原生 Hermes；是否安装依赖、获得网络和平台权限仍按环境判断。旧执行器和协议已退休，档案处理见 [运维](../../docs/runbooks/OPERATIONS.md)。

## 保留的集成文件

| 文件 | 职责 |
| --- | --- |
| native_engineer.py | 官方 hermes_cli.main.main 工程总入口 |
| native_cli.py / native_gateway.py | 聊天 CLI/Gateway 生命周期与加载检查 |
| plugin/ | 身份/协作提示及加载证据；仅聊天注册工具范围 hook |
| profile_config.py | 保留原生偏好、刷新受管 provider 与身份 skill |
| command_adapter.py | 保留的 HTTP 命令子集，独立于模型执行 |
| import_legacy.py | 旧聊天导入 SessionDB，保留原档案 |
| backup_adapter.py | Hermes SQLite 快照及恢复路径处理 |
| feishu_probe.py / weixin_login.py | 官方平台探针与扫码，凭据留本机 |

同一聊天 profile 的入口互斥，工程 profile 可独立工作。方法 skills 不包含 worker 输出协议。固定源码、身份、记忆、工具和真实模型验收范围见 [验证边界](../../docs/VALIDATION.md)。
