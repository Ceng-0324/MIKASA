# 原生 Hermes 迁移验收

> 下文为此前原生迁移的验证记录。后续协作治理收窄与规则更新见 [0006](decisions/0006-hermes-native-mikasa.md)，工程续话与账号记忆共享见 [0008](decisions/0008-engineering-state.md)；旧审批门禁和按任务隔离长期记忆的描述不代表当前实现。

2026-09-20，固定 Hermes `f9524d3f119c672e4a4444f56d582e7475716ba3`。不修改上游源码。

## 已运行

- 原生 Gateway 真实 CCH 请求：身份为 Mikasa，负责人 Shawn/Ceng，保留自作 PR 不自批。
- Gateway 关闭后重新启动，原生 SessionDB 仍能读取旧对话。
- `scripts/probe_chat.py --slash --commands` 通过 18 项检查：GPT → Claude → GPT、Responses/Messages 原生协议、历史连续、幂等、新旧会话、官方命令组件、完整 SOUL/工程规则与 skills 索引进入实际模型请求。脱敏检查见 [证据](native-chat-evidence.json)。
- 官方 lifecycle hook 观察到原生 `skill_view` 两次和 `memory` 一次成功；专门状态探针进一步通过 20 项真实检查：重启和 `/new` 后记忆恢复、账号隔离、旧请求与运行证据稳定重放、取消终态、原生人格 skill 自动加载、两种协议完整注入与无 CCH 密钥落盘。见 [状态证据](native-state-evidence.json)。
- `scripts/probe_native_offline.py` 使用真实固定 SDK，通过 8 项离线检查：51 轮旧记录完整有序导入、重复导入不增加记录、其他账号隔离、旧库不变、官方 plugin 发现、persona auto_load 和工具权限边界。
- 新启动检查确认必需的人格 skill 加载后原生 API 才就绪，错误 API 凭据返回 401。
- 所属账号通过鉴权 HTTP 停止接口调用原生 stop API；该操作不等待聊天发送锁，先返回停止请求，再由 Hermes 进入 cancelled/interrupted。

## 边界

聊天不再强制模型输出 JSON，不重建最近 40 轮上下文。Mikasa 只保留账号授权与 native session/run 引用，旧 SQLite 档案不删除。工程任务的 bridge 保留结构化交付与政策适配，文件/终端、记忆和 skills 已改用官方原生实现。Docker 29.4.0 在本机 OrbStack 中运行；模型只能改快照，宿主独立核对差异、完整读取证据与审批门禁。原生容器探针与合成任务验收见下方工程证据。

GitHub、飞书和 VM 真实接入依负责人安排稍后讨论。当前没有推送、外部发布或试点仓库修改。CCH default 分组仍须网关侧权限证据；`/model default` 仅恢复配置的默认请求模型。

## 重复验收

```sh
python3.12 scripts/probe_native_offline.py --config config/local/hermes-cch.json
python3.12 scripts/probe_native_state.py --config config/local/hermes-cch.json --report runtime/state/hermes-cch/native-state-proof.json
python3.12 scripts/probe_chat.py --config config/local/hermes-cch.json --target claude-opus-4-6 --report runtime/state/hermes-cch/native-chat-proof.json --slash --commands
```

状态探针使用一次性短路径 profile，仅脱敏检查结果写入 runtime；不向真实账号记忆留下验收事实。普通运行 profile 若路径过长，macOS 上 Hermes 的可选 Unix 心跳 socket 会报告 AF_UNIX path too long；HTTP/会话仍可工作，正式 VM 使用较短状态路径并验收原生健康检查。

## 原生工程验收

2026-09-20，本轮接入原生文件/搜索/编辑/终端工具、工程 SOUL、按任务隔离的记忆/SessionDB 与原生 skills.auto_load。实际调用使用既有 Codex/CCH Responses 配置；没有修改网关后台或上游 Hermes。脱敏结果和原报告摘要见 [工程证据](native-engineering-evidence.json)。

- Docker 原生工具 11 项检查通过：读取、写入、终端、密钥隔离、无网络、只读根目录、资源约束、无 Docker socket 与退出清理。
- 无模型工程探针 8 项通过：原生文件与 shell 均不能写入只读快照、实际读取结果能核对完整 head 证据、原仓库不变、强制取消及时回收容器和快照。
- CCH 合成任务 5 类全部通过：完整生命周期、原生工具同会话红绿修复、只读拆解、发现边界缺陷的审查、超过 4500 行文件的原生分页完整覆盖。实现/审查随后重复通过；额外一轮生命周期使用真实 Docker 独立检查镜像，通过最终复验与本地提交。
- pre_api_request 对实际请求验证完整 Mikasa 身份、工程规则与任务 skill 正文；实现结果保留自作归属，停在 awaiting_review。

```sh
python3.12 scripts/probe_native_sandbox.py --report runtime/state/hermes-cch/native-sandbox-proof.json
python3.12 scripts/probe_native_engineering_offline.py --report runtime/state/hermes-cch/native-engineering-offline-proof.json
python3.12 scripts/probe_hermes.py --config config/local/hermes-cch.json --report runtime/state/hermes-cch/native-tools-proof.json --case lifecycle --case tool-loop --case tool-plan --case tool-review --case paged-context
```

工程镜像需提前拉取，默认 digest 见 [快照实现](../mikasa/sandbox.py)。验收覆盖本机 macOS/OrbStack 和合成 Python 仓库；其他语言依赖、Linux VM、真实平台权限与任意规模仓库仍需相应环境验证。固定源码的 archive 来源标记沿用既有 Git blob 验证，没有声称每次运行重新在线核验源码。
