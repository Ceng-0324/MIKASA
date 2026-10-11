# Skill 来源与本地适配

核对日期：2026-09-20。上游为 [mattpocock/skills](https://github.com/mattpocock/skills/tree/c55ee46073ed923f86ce59a5eb3b6d895095d1b7)，固定 commit `c55ee46073ed923f86ce59a5eb3b6d895095d1b7`，MIT 许可见 [LICENSE.mattpocock](LICENSE.mattpocock)。本目录是经过适配的本地版本，不是上游原文的完整安装。

| 本地 skill | 实际读取的上游 | 保留 | 适配 |
| --- | --- | --- | --- |
| mikasa-persona | 本项目 identity.md | 身份、关系和表达的唯一事实源 | 仅添加路由；人格正文仍由 canonical 注入，不复制到 skill |
| mikasa-plan | skills/engineering/to-tickets/SKILL.md | 可独立验证的垂直任务、显式阻塞关系 | 输出 JSON；确认、派发和发布交给宿主；不强制配置上游 tracker 或保留内部兼容层 |
| mikasa-implement | skills/engineering/tdd/SKILL.md、implement/SKILL.md | 公共行为测试、独立预期值、按失败证据迭代 | 通过宿主工具探索、应用与观察红绿检查；最终复验和提交仍由宿主执行；已有明确验收不重复索要低风险许可 |
| mikasa-review | skills/engineering/code-review/SKILL.md | 需求与工程规范两个审查轴、定位依据、区分偏好与缺陷 | 同一调用内分别评估；不要求并行子 agent；输出宿主契约，按规则与已确认记忆判断审查安排；宿主不改写结论 |
| verified-pr-review | 本项目的已确认审查约定与验收经验；非 mattpocock 上游 | 从逐项验收到正式 Review、合并及 Issue 收尾的交付闭环 | 主流程由本项目维护；专项验收说明在 references，模板在 templates；不建立自研审批服务 |

触发配置集中在 [manifest.json](manifest.json)。`plan`、`implement` 各加载人格与对应工程 skill，`review` 同时包含 `mikasa-review` 与 `verified-pr-review`；`chat` 只加载人格 skill；audit/followup 是确定性数据路径，不调用模型，因此不声称执行人格或工程 skill。

当前聊天与工程 profile 使用 Hermes 原生 auto_load/skill_view，仓库技能经 release 的 `skills.external_dirs` 发现；`mikasa-engineering` 由 canonical 工程文档生成到 profile，非仓库维护副本。`load_skills` 和 manifest 保留用于受信任的技能清单与本地检查，无工作区的协议诊断仍直接注入正文。不要把项目适配宣称为 mattpocock 上游的完整工作流。
