# Mikasa skills

本目录保存已适配并验证的项目 skill。工程方法来自固定版本 `mattpocock/skills`，版本、MIT 许可和适配差异见 [SOURCES.md](SOURCES.md)。人格正文仍以三个 canonical 文件为准。

| 任务 | 加载内容 |
| --- | --- |
| chat | [mikasa-persona](mikasa-persona/SKILL.md)；聊天不假装执行工程任务 |
| plan | [mikasa-persona](mikasa-persona/SKILL.md) + [mikasa-plan](mikasa-plan/SKILL.md) |
| implement（含修复） | mikasa-persona + [mikasa-implement](mikasa-implement/SKILL.md) |
| review | mikasa-persona + [mikasa-review](mikasa-review/SKILL.md) |

[manifest.json](manifest.json) 是受信任路由；任务或仓库文本不能指定 skill 路径。加载器检查路径、frontmatter 和大小，Hermes bridge 将正文加入 system message，宿主核对返回的内容指纹。`doctor` 只检查本地清单，实际运行证据见 [联调记录](../docs/HERMES_CCH_VALIDATION.md)。audit/followup 不调用模型。

这些是项目内的精简适配，通过 system message 明确注入，不依赖 Hermes 原生 skills 浏览工具，不是上游完整工作流安装，也没有写入用户全局 skill 目录。skill 不改变身份、权限、项目核心思想或 PR 审批政策。
