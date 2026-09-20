# 原生 Hermes 迁移验收

2026-09-20，固定 Hermes `f9524d3f119c672e4a4444f56d582e7475716ba3`。不修改上游源码。

## 已运行

- 原生 Gateway 真实 CCH 请求：身份为 Mikasa，负责人 Shawn/Ceng，保留自作 PR 不自批。
- Gateway 关闭后重新启动，原生 SessionDB 仍能读取旧对话。
- `scripts/probe_chat.py --slash --commands` 通过 18 项检查：GPT → Claude → GPT、Responses/Messages 原生协议、历史连续、幂等、新旧会话、官方命令组件、完整 SOUL/工程规则与 skills 索引进入实际模型请求。脱敏检查见 [证据](native-chat-evidence.json)。
- 官方 lifecycle hook 观察到原生 `skill_view` 两次和 `memory` 一次成功；专门状态探针进一步通过 20 项真实检查：重启和 `/new` 后记忆恢复、账号隔离、旧请求与运行证据稳定重放、取消终态、原生人格 skill 自动加载、两种协议完整注入与无 CCH 密钥落盘。见 [状态证据](native-state-evidence.json)。
- `scripts/probe_native_offline.py` 使用真实固定 SDK，通过 8 项离线检查：51 轮旧记录完整有序导入、重复导入不增加记录、其他账号隔离、旧库不变、官方 plugin 发现、persona auto_load 和工具权限边界。
- 新启动检查确认必需的人格 skill 加载后原生 API 才就绪，错误 API 凭据返回 401。
- 网页停止按钮调用原生 stop API；该操作不等待聊天发送锁，先返回停止请求，再由 Hermes 进入 cancelled/interrupted。

## 边界

聊天不再强制模型输出 JSON，不重建最近 40 轮上下文。Mikasa 只保留账号授权与 native session/run 引用，旧 SQLite 档案不删除。工程任务仍走受控 bridge：它保护固定 head 证据、检查命令和审批门禁。本机 OrbStack 已启动、Docker 29.4.0 可用；原生工程文件/终端仍需独立容器验收，不能把环境就绪说成迁移完成。

GitHub、飞书和 VM 真实接入依负责人安排稍后讨论。当前没有推送、外部发布或试点仓库修改。CCH default 分组仍须网关侧权限证据；`/model default` 仅恢复配置的默认请求模型。

## 重复验收

```sh
python3.12 scripts/probe_native_offline.py --config config/local/hermes-cch.json
python3.12 scripts/probe_native_state.py --config config/local/hermes-cch.json --report runtime/state/hermes-cch/native-state-proof.json
python3.12 scripts/probe_chat.py --config config/local/hermes-cch.json --target claude-opus-4-6 --report runtime/state/hermes-cch/native-chat-proof.json --slash --commands
```

状态探针使用一次性短路径 profile，仅脱敏检查结果写入 runtime；不向真实账号记忆留下验收事实。普通运行 profile 若路径过长，macOS 上 Hermes 的可选 Unix 心跳 socket 会报告 AF_UNIX path too long；HTTP/会话仍可工作，正式 VM 使用较短状态路径并验收原生健康检查。
