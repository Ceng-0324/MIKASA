# 0004：原生 Hermes Gateway 作为会话执行底座

日期：2026-09-20。依据：负责人要求最大化复用 Hermes harness，并在每个迁移阶段保留可验证提交。

## 决定

Mikasa 为每个已授权账号准备独立的 Hermes profile，并启动未修改的固定 Hermes Gateway。Gateway 的原生 SessionDB、上下文压缩、记忆、skills、工具循环和取消状态属于 Hermes；Mikasa 只保存账号授权、任务/审批事实、聊天幂等回执以及对原生 session ID 的引用。不会把 Hermes transcript 再复制到 Mikasa 的聊天表。

每个 profile 的 `SOUL.md` 和 policy snapshot 由项目 canonical 文件生成。Mikasa plugin 通过 Hermes 官方 system-prompt section 和 `pre_tool_call` hook 注入工程契约与工作边界；原生记忆只能服务连续性，不能改变身份、授权或审批政策。Profile、API key、sessions 和 memories 独立于其他账号，凭据只通过子进程环境变量传入。

模型请求仍由 CCH 路由。Mikasa 为显式模型 ID 生成 Hermes provider route，并在每个原生 session 上提交 model lock；`/v1/runs` 取消、幂等键和运行状态使用 Hermes API，CCH 不承担会话状态。

## 阶段边界

本提交证明原生 Gateway 的启动、真实 CCH 请求、身份边界、策略注入入口和 SessionDB 持久化。现有 Mikasa 聊天 HTTP/CLI 仍保留为下一阶段的入口适配，旧 SQLite 聊天记录不会删除；迁移入口必须在后续提交中完成一次性映射并保留旧数据。

原生 Feishu 平台和 GitHub 权限在外部账号信息确定后接入；FluxCore 试点与聊天工程任务最后验收。没有凭据时不宣称外部联调或 VM 部署完成。
