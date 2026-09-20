# GitHub 集成

负责人是 `Ceng-0324`，Mikasa 账号为 [`Mikasa-0910`](https://github.com/Mikasa-0910)。REST 适配支持分页读取 Issue/PR/CI、正式 Review、Issue/草稿 PR 发布和当前 head 审批检查；发布 token 会通过 `/user` 核对账号。代码见 `mikasa/github.py`、`mikasa/service.py`。

webhook 使用原始请求体 HMAC SHA-256 和 delivery ID 去重，可按配置触发只读审查草稿。自作归属跨提交保留；人类归属按 head 失效；发布前重新核对版本。不存在自动合并接口。

真实权限、token 注入、GitHub App 是否必要和分支保护部署尚未验证。CLI `gate` 不等于平台强制门禁。使用与恢复见 [操作手册](../../docs/runbooks/OPERATIONS.md)；本目录不包含凭据。
