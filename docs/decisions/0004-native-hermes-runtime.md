# 0004：原生 Hermes Gateway 作为会话执行底座

日期：2026-09-20。依据：负责人要求最大化复用 Hermes harness，并在每个迁移阶段保留可验证提交。

## 决定

Mikasa 为每个已授权账号准备独立的 Hermes profile，并启动未修改的固定 Hermes Gateway。Gateway 的原生 SessionDB、上下文压缩、记忆、skills、工具循环和取消状态属于 Hermes；Mikasa 只保存账号授权、任务/审批事实、聊天幂等回执以及对原生 session ID 的引用。不会把 Hermes transcript 再复制到 Mikasa 的聊天表。

每个 profile 的 `SOUL.md` 和 policy snapshot 由项目 canonical 文件生成。Mikasa plugin 通过 Hermes 官方 system-prompt section 和 `pre_tool_call` hook 注入工程契约与工作边界；原生记忆只能服务连续性，不能改变身份、授权或审批政策。Profile、API key、sessions 和 memories 独立于其他账号，凭据只通过子进程环境变量传入。

模型请求仍由 CCH 路由。Mikasa 为显式模型 ID 生成 Hermes provider route，并在每个原生 session 上提交 model lock；`/v1/runs` 取消、幂等键和运行状态使用 Hermes API，CCH 不承担会话状态。

## 阶段边界

第一阶段建立原生 Gateway 启动和会话持久化；第二阶段将 CLI/HTTP 聊天统一接入原生运行。旧 SQLite 普通对话通过 SessionDB 接口一次性导入，旧回执保留为档案。新普通聊天仅保存摘要与 native run 引用，原生 API 负责幂等运行、上下文压缩与中断状态。展示分页不限制下一轮推理历史。

每账号一个受控 Gateway 实例，HTTP 服务共享管理器，CLI 退出时关闭子进程。原生 API key 为本机随机生成的服务凭据，权限 0600，重启沿用以保留 Hermes 幂等命名空间。固定源码支持 Git checkout 和带既有 Git blob 验证来源标记的归档；标记不是每次启动重新进行远端完整性核验。

聊天目前只开放原生记忆和只读 skills。工程文件/终端已迁移至原生 Docker 工具，见 [后续工程决定](0005-native-engineering-tools.md)；bridge 保留业务交付适配。源码没有 fork，上游 API 本身可能每轮重建 AIAgent；会话持久化、压缩恢复和运行生命周期仍由 Hermes 实现，不能声称所有入口共享同一个常驻 AIAgent 对象。

原生 Feishu 平台和 GitHub 权限在外部账号信息确定后接入；FluxCore 试点与聊天工程任务最后验收。没有凭据时不宣称外部联调或 VM 部署完成。
