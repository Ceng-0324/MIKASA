# 原生 Hermes 迁移验收

2026-09-20，固定 Hermes `f9524d3f119c672e4a4444f56d582e7475716ba3`。不修改上游源码。

## 已运行

- 原生 Gateway 真实 CCH 请求：身份为 Mikasa，负责人 Shawn/Ceng，保留自作 PR 不自批。
- Gateway 关闭后重新启动，原生 SessionDB 仍能读取旧对话。
- `scripts/probe_chat.py --slash --commands` 通过 18 项检查：GPT → Claude → GPT、Responses/Messages 原生协议、历史连续、幂等、新旧会话、官方命令组件、完整 SOUL/工程规则与 skills 索引进入实际模型请求。脱敏检查见 [证据](native-chat-evidence.json)。
- 官方 lifecycle hook 观察到原生 `skill_view` 两次和 `memory` 一次成功；完整跨重启记忆与账号隔离由下一阶段的专门探针补充。

## 边界

聊天不再强制模型输出 JSON，不重建最近 40 轮上下文。Mikasa 只保留账号授权与 native session/run 引用，旧 SQLite 档案不删除。工程任务仍走受控 bridge：它保护固定 head 证据、检查命令和审批门禁。本机 Docker daemon 未运行，不能把受控工程工具尚未迁移说成原生终端已经隔离可用。

GitHub、飞书和 VM 真实接入依负责人安排稍后讨论。当前没有推送、外部发布或试点仓库修改。CCH default 分组仍须网关侧权限证据；`/model default` 仅恢复配置的默认请求模型。
