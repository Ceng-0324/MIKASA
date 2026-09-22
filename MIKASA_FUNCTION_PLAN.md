# 推进计划

目标：让 Mikasa 作为有持续身份和协作记忆的程序员参与实际工程。Hermes 承载原生执行与状态，CCH 提供模型，Mikasa 维护身份、skills 和必要适配。当前实现见[架构](docs/architecture/README.md)，验收事实见[验证边界](docs/VALIDATION.md)。

## 接下来的顺序

1. **消息体验收尾**：OrbStack `mylinux` 统一 Gateway 已正常收发并切换 GPT/Claude。原生并发、同会话排队、群内共享上下文、历史检索与按需工程 skills 已接入；模型作用范围沿用原生反馈，日常聊天不再常驻完整工程规章或 worker 输出协议。`/sethome` 与明确长期记忆请求的修复保留；自动验证和渠道边界见[验证边界](docs/VALIDATION.md)。不再重复手机端逐项验收，下一阶段为 VM 稳定性。
2. **VM 稳定性**：演练进程异常恢复与 VM 重启，落实备份、恢复和日志保留策略。本机 OrbStack 在线依赖 Mac，不作为独立云主机已部署的证据。
3. **VM 工程环境**：准备 Docker 隔离镜像，使用合成任务验证工程执行、测试、修复和交付。需要外部 API/webhook 时再落实公网 VM、TLS 与入站网络。
4. **聊天工程任务与 FluxCore**：联合验收自然语言任务入口、进度交互、真实仓库执行和 GitHub PR/Review。`Ceng-0324/FluxCore` 仅是试点，不以开发其业务为前置。
5. **按实际使用收窄适配**：确认 HTTP、worker RPC 与发布入口的消费者，满足下列迁移条件后删除重复实现。

CCH `default` 分组仍需网关侧配置与同次路由证据；本地模型名或连接成功不证明分组，见 [CCH 手册](docs/runbooks/CCH.md)。GitHub 已确认独立账号身份，具体仓库与操作权限在任务接入时验收。

## 收窄条件

消息平台统一使用 `gateway --platform feishu [--platform weixin]`，单飞书同样走此入口。旧 `feishu` 别名已移除。

HTTP 命令与回执适配在原生渠道覆盖鉴权、幂等、取消、会话访问并迁移调用方后删除。第三方 worker v1 RPC 在消费者迁移后删除。工程快照与最终验收在原生执行环境实现等价保护并通过验证后收窄。

审批分工等长期约定通过身份、skills、已确认交互和原生记忆维护，不重建业务门禁。每个可验证阶段创建本地提交，不自动推送。
