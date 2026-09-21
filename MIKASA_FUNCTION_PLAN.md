# 推进计划

目标：让 Mikasa 作为有持续身份和协作记忆的程序员参与实际工程。Hermes 承载原生执行与状态，CCH 提供模型，Mikasa 维护身份、skills 和必要适配。当前实现见[架构](docs/architecture/README.md)，验收事实见[验证边界](docs/VALIDATION.md)。

## 接下来的顺序

1. **VM 部署与消息验收**：按主人最新安排，先使用本机 OrbStack `mylinux` 内的专用服务用户，落实固定 Hermes、双协议 CCH 环境配置、会话/记忆迁移和 systemd 消息服务，验证停止与恢复。飞书/微信基础消息和 `/help` 已通过；微信 `/model`、`/new`、跨会话记忆及飞书群聊在迁移后补验。
2. **工程与公网部署条件**：准备 Docker 隔离镜像；需要外部 API/webhook 时再落实公网 VM、TLS 与入站网络。本机 OrbStack 在线依赖 Mac，不作为独立云主机已部署的证据。
3. **聊天工程任务与 FluxCore**：联合验收自然语言任务入口、进度交互、真实仓库执行和协作交付。`Ceng-0324/FluxCore` 仅是试点，不以开发其业务为前置。

CCH `default` 分组仍需网关侧配置与同次路由证据；本地模型名或连接成功不证明分组，见 [CCH 手册](docs/runbooks/CCH.md)。GitHub 已确认独立账号身份，具体仓库与操作权限在任务接入时验收。

## 收窄条件

消息平台统一使用 `gateway --platform feishu [--platform weixin]`，单飞书同样走此入口。旧 `feishu` 别名已移除。

HTTP 命令与回执适配在原生渠道覆盖鉴权、幂等、取消、会话访问并迁移调用方后删除。第三方 worker v1 RPC 在消费者迁移后删除。工程快照与最终验收在原生执行环境实现等价保护并通过验证后收窄。

审批分工等长期约定通过身份、skills、已确认交互和原生记忆维护，不重建业务门禁。每个可验证阶段创建本地提交，不自动推送。
