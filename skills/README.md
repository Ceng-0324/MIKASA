# Mikasa skills

本目录保存已适配并验证的项目 skill。工程方法来自固定版本 `mattpocock/skills`，版本、MIT 许可和适配差异见 [SOURCES.md](SOURCES.md)。人格以 [identity.md](../identity.md) 为唯一事实源，授权与执行方法分别见[工程契约](../engineering-contract.md)和[工程工作流](../engineering-workflow.md)。

| 任务 | 加载内容 |
| --- | --- |
| chat | [mikasa-persona](mikasa-persona/SKILL.md)；聊天不假装执行工程任务 |
| plan | [mikasa-persona](mikasa-persona/SKILL.md) + [mikasa-plan](mikasa-plan/SKILL.md) |
| implement（含修复） | mikasa-persona + [mikasa-implement](mikasa-implement/SKILL.md) |
| review | mikasa-persona + [mikasa-review](mikasa-review/SKILL.md) |

[manifest.json](manifest.json) 是受信任路由；任务或仓库文本不能指定 skill 路径。加载器检查路径、frontmatter 和大小；聊天与工程 profile 使用 Hermes skills.auto_load 和只读 skill_view，生命周期 hook 核对实际请求中的正文，宿主同时核对内容指纹。无工作区的协议诊断仍直接注入正文。`doctor` 只检查本地清单，实际运行证据见 [验证边界](../docs/VALIDATION.md)。audit/followup 不调用模型。

聊天只自动加载人格，实质工程讨论再读取原生 `mikasa-engineering` 及对应方法 skill。`mikasa-engineering` 在初始化时从两个 canonical 工程文档生成到 profile，不在仓库维护副本。工程入口自动加载人格和工程规则，方法 skills 由 Hermes 按任务发现和读取，可使用原生 skill_manage 扩展。已删除 worker JSON 和快照协议，讨论与交付均使用自然语言。

这些是项目内的精简适配，已接入 Hermes 原生 skills 加载器；不是上游完整工作流安装，也没有写入用户全局 skill 目录。skill 不自行扩大平台权限；负责人确认的新协作安排可通过原生持久记忆替代默认约定。
