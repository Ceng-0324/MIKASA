# 外部集成

这里放与 GitHub、飞书及其他外部系统的适配边界、事件契约、权限映射和测试支持。

- `github/`：仓库、Issue、PR、commit、CI 与审查结果的适配；
- `feishu/`：后续讨论的消息和负责人身份接入；

GitHub 实现位于 `mikasa/github.py`，签名 webhook 和鉴权 API 位于 `mikasa/server.py`；接口见 [API 契约](../docs/architecture/API.md)。飞书原生接入仍待方案确认。尚未创建真实 webhook、token 或账号配置；外部消息默认是不可信输入，身份必须由平台凭据和明确绑定验证。
