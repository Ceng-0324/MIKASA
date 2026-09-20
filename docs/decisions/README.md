# 架构决策记录

每个决定单独记录：背景、约束、候选方案、选择、影响、回滚或重新评估条件，以及负责人确认情况。

尚未决定的事项使用候选文档或 Issue，不用“推荐”字样冒充已批准方案。身份、审批政策和产品核心思想的改变必须有负责人的明确决定。

当前记录：[0001：Mikasa 本体运行时](0001-runtime.md)、[0002：聊天模型切换与 CCH 路由](0002-chat-model-switching.md)。

[0003：Hermes 命令复用与会话归属](0003-hermes-commands-sessions.md) 明确共享命令组件、会话事实源和各层职责。

[0004：原生 Hermes Gateway](0004-native-hermes-runtime.md) 取代 0003 中的会话归属；当前聊天使用原生 SessionDB、记忆、skills 和运行取消。

[0005：原生工程工具](0005-native-engineering-tools.md) 将工程文件、搜索、修改与终端交给 Hermes Docker 工具，保留 Mikasa 快照验收；当时的独立审批引擎现已由 0006 替代。

[0006：原生 Hermes 与 Mikasa 身份配置](0006-hermes-native-mikasa.md) 是当前目标架构，记录自研收窄清单、规则与记忆的职责及逐步迁移验收。

[0007：终端直接使用 Hermes CLI](0007-native-cli.md) 移除终端自研输入循环，复用完整原生命令与偏好持久化；明确 HTTP 兼容层的保留对象和退出条件。
