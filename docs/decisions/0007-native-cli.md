# 0007：终端直接使用 Hermes CLI

日期：2026-09-20。基于负责人确认的 [原生优先目标](0006-hermes-native-mikasa.md)，完成终端交互迁移。该决定更新 0003/0004 的终端入口设计，HTTP API 的既有协议暂保留。

## 选择与所有权

固定 Hermes 0.21.3，源码 revision `f9524d3f119c672e4a4444f56d582e7475716ba3`。其 `/v1/runs` 不会调用完整 CLI 命令分派；复用 registry 和参数解析并不等于复用交互实现。终端因此直接调用官方 `cli.main()`，删除 Mikasa 的 `input()` 循环，不再维护终端命令映射。

| 层 | 本轮职责 |
| --- | --- |
| Hermes | 终端 UI、系统命令、model scope、SessionDB、会话恢复、MEMORY/USER、skills 与工具循环 |
| CCH | 模型供应、上游重写、分组及网关路由；由 Hermes 原生 transport 请求 |
| Mikasa | 账号 profile、固定 SDK 启动与进程回收、CCH 配置引用转换、SOUL/工程规则/persona 准备和必要插件 |

本地 `chat` 不创建 Mikasa Service/业务数据库。已有业务库存在时，通过原有 SessionDB 导入器保留旧聊天。CLI 与 Gateway 使用同一账号 home 和进程锁，同账号不能同时运行；不同账号的记忆与会话保持隔离。终端按受信任的本机负责人操作，不能用共享 shell 替代多用户鉴权。

## 配置与数据连续性

- 从受信任来源读取模型配置，生成 Hermes providers 与精确 model_aliases。默认模型和显式 models 可直接跨 GPT/Claude 切换；未列入的模型需添加配置或显式选择原生 provider，不重做前缀解析器。
- 模型 Key 只进入子进程环境，生成配置记录 key_env；不复制 Codex/Claude 认证，不继承无关平台和模型凭据。
- 首次生成 profile 默认值；后续保留原生默认模型、推理和显示偏好，并补齐必需 skills/plugin。更新由 SDK 解释器解析 YAML/JSON，原子写回 JSON（合法 YAML），不保留 YAML 注释。
- `cch-<16 位来源摘要>` 为生成配置的命名空间；更新时清除被移除的生成 provider/别名，保留其他原生配置。若已保存的默认 provider 被移除，保留原配置并中止启动；须恢复来源或显式修正 profile 默认 provider，不能悄悄回退模型。
- 不覆盖 MEMORY、USER 或 state.db。`--global` 只改变该 profile，不改个人 Codex/Claude、Mikasa worker 默认值或 CCH 分组。
- 锁冲突在配置更新前失败；坏配置保留原文件；正常退出与 SIGTERM 回收子进程，超时后终止进程，释放 profile 锁。

## 可观察行为与兼容范围

| 行为 | 原生终端 | 暂留的 HTTP/单条 `--message` |
| --- | --- | --- |
| 命令 | Hermes 完整分派及帮助 | 原有已接入命令，未开放项明确拒绝 |
| 模型选择 | 原生 session/once/global、provider/reasoning 等参数 | 只开放 session；支持中文切换及 default 别名 |
| 切换验证 | 原生配置/目录校验；实际推理可用性由请求确认 | 额外真实推理探针成功后保存 |
| `/new` | 官方确认流程；固定版本对自定义 CCH provider 保留当前模型，见下方上游限制 | 明确保留当前模型，返回新 chat_id 和幂等回执 |
| 恢复 | 原生 `/resume`、`/sessions` 和 `--session` | 已绑定的旧 API chat_id；不自动登记 CLI 新会话 |
| 工作区动作 | 本机用户触发原生命令；初始为 profile/workspace | `/init` 仍返回 deferred_command |

原生 `/model` 的参数或路由解析失败会保留旧选择，不承诺实际推理失败后自动回滚。模型可调用工具仍限于 memory 和只读 skills；本地系统命令是独立通道，这个工具范围不构成操作系统沙箱。中文“切换为……”在 CLI 是普通消息，确定的切换入口为 `/model`。

固定上游的已复现限制：`hermes_cli/cli_session_mixin.py::_reset_model_to_config_default` 读取启动时的 CLI_CONFIG，调用 switch_model 时未传 user_providers/custom_providers；`model_switch.py::_route_explicit_provider` 因而无法识别生成的 CCH provider，重置失败被忽略，`/new` 正常创建会话并保留当前模型。同进程刚写入的 `--global` 也不刷新该配置快照。Mikasa 不改写上游或添加另一套 `/new` 分派；恢复模型可显式执行 `/model ID`，保存的默认值在重启后生效。升级 Hermes 时需重新验收此路径。

HTTP/`--message` 的兼容对象是已存在的 JSON 客户端和幂等回执，不将它保留为长期第二套 Agent 平台。退出条件：原生渠道覆盖认证账号映射、原有会话访问、取消、幂等与中断恢复，并完成调用方迁移，随后删除 chat/command adapter 对应实现。不会为了立即删文件而破坏现有会话和客户端。

## 验证与剩余范围

本阶段全量 `python3.12 -m unittest discover -v` 共 130 项通过，包含原生入口委托、profile 互斥、偏好保留、坏配置保护、路由删除与 SIGTERM 子进程清理。`scripts/check_docs.py`、`git diff --check` 通过；默认 doctor 正确报告示例配置未启用模型，本机 CCH 配置 doctor 报告 configuration=valid、connection=not_checked、provider_group=unverified。

固定 SDK 的 `scripts/probe_native_cli.py` 使用一次性 profile、本地模型目录和合成 Key，验证原生 /model 的两种协议与凭据选择、上下文保留、非法参数保持原路由、/new、/resume、persona、全局默认值重载、正式入口启动和 EOF 退出，扫描 profile 中无合成模型 Key；单独记录 `/new` 自定义 provider 的上游回退行为，不把它当作默认值重置成功。它不读取真实 CCH 认证，不调用真实模型。

该探针最终 13 项检查通过，其中一项专门确认上述上游限制仍存在；通过不表示该限制已修复。

同轮 `probe_native_offline.py` 的 12 项检查通过：旧会话完整导入、账号隔离、身份/工程规则/persona/工程 skills、MEMORY 更新与替换、MEMORY/USER 新进程恢复及工具范围。该探针证明 SDK 加载与存储链路，不能证明模型必然遵循全部协作约定。

本轮未重复请求被 WAF 拒绝的 CCH 目录；此前真实联调记录仍是历史证据，`default` 分组仍未取得网关侧确认。未重启已有生产 profile 或服务，新的入口/配置在下次启动时生效。

本阶段完成终端交互。工程仍用每任务 profile，尚未继承账号聊天记忆；任务队列/runner 尚未迁入 Kanban。下一步落实原生工程持续会话与长期记忆继承，再收口 Kanban、Cron、事件与备份，随后 GitHub/飞书、VM，最后聊天工程任务和 FluxCore。外部信息按负责人要求稍后讨论。

如原生版本升级破坏命令或配置契约，在一次性 profile 复现并重新验收；不修改上游源码或悄悄恢复自研交互循环。保留完整 runtime 才能恢复原生数据，业务 SQLite 备份不是完整回滚点。
