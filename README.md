# Mikasa

Mikasa 是基于原生 Hermes 运行、通过 CCH 使用模型、拥有持续身份和协作记忆的仿生程序员。身份、工程 skills 和记忆承载协作约定，不另建强制审批业务引擎。

当前包含人格与工程规则 1.1 和 Python 运行时 0.1。专属审批引擎已移除；聊天使用原生 Gateway，工程使用原生 Docker harness，任务调度与部分入口仍在迁移。保留、迁移、删除清单及本次验证见 [收窄决定](docs/decisions/0006-hermes-native-mikasa.md)。此前 Hermes 0.21.3/CCH 已完成合成任务真实联调；GitHub、飞书和 VM 尚未完成运行验收。

## 本地运行

需要 Python 3.12+、Git；核心运行时仅使用 Python 标准库，无需安装第三方依赖即可执行：

```sh
python3.12 -m mikasa doctor
python3.12 -m unittest discover -v
python3.12 scripts/check_docs.py
python3.12 -m mikasa --help
```

将 [配置示例](config/examples/mikasa.json) 复制到 `config/local/mikasa.json` 并填写仓库、模型执行器和账号环境变量后：

```sh
python3.12 -m mikasa --config config/local/mikasa.json serve
python3.12 -m mikasa --config config/local/mikasa.json run
```

API 和 runner 分别运行。默认示例不启用仓库、模型、定期审计或外部发布；`doctor` 会明确显示缺少的运行条件。完整说明见 [运行手册](docs/runbooks/OPERATIONS.md)、[API 契约](docs/architecture/API.md) 和 [架构决定](docs/decisions/0001-runtime.md)。

本地回归检查见 [验证记录](docs/VALIDATION.md)，新增主动工具循环见 [工具覆盖验证](docs/HERMES_TOOLS_VALIDATION.md)，模型、skill 与完整任务链的早期真实证据见 [Hermes/CCH 联调记录](docs/HERMES_CCH_VALIDATION.md)。

## 聊天与模型切换

```sh
python3.12 -m mikasa --config config/local/hermes-cch.json chat
```

输入 `/model 完整模型ID`，或直接说“切换为 gpt-5.6-luna”“恢复默认模型”。`/new` 开始新聊天并保留当前模型，`/help` 查看已接入命令。Hermes 共享组件负责通用命令解析，Hermes Gateway 负责会话、记忆、skills 和取消，Mikasa 负责授权、命令适配及业务回执，详见 [职责边界](docs/decisions/0004-native-hermes-runtime.md)。切换经真实调用验证后对当前聊天生效，保留上下文；原工程任务仍使用运行配置。配置、会话恢复和鉴权见 [聊天用法](docs/runbooks/CHAT.md)，调研依据见 [CCH 路由决定](docs/decisions/0002-chat-model-switching.md)，真实结果见 [聊天验证](docs/CHAT_VALIDATION.md)。

## 规则文件

| 文件 | 职责 |
| --- | --- |
| [identity.md](identity.md) | 基于动画官方角色资料进行本地适配的身份、关系与交流方式 |
| [engineering-contract.md](engineering-contract.md) | 授权、事实边界、工程质量、协作与 PR 审批责任 |
| [engineering-workflow.md](engineering-workflow.md) | 调查、拆解、实现、审查、验证与交付步骤 |
| [AGENTS.md](AGENTS.md) | 目录级规则入口及 canonical 读取顺序 |
| [CLAUDE.md](CLAUDE.md) | 指向同一套规则的入口 |
| [docs/ADAPTATION_SOURCES.md](docs/ADAPTATION_SOURCES.md) | 官方角色依据、适配判断及两处 AptS 来源的版本记录 |
| [MIKASA_FUNCTION_PLAN.md](MIKASA_FUNCTION_PLAN.md) | 已确认的产品方向和后续待定项 |

## 当前目录骨架

```text
config/          无密钥配置模板与 schema
mikasa/          任务、存储、执行、GitHub 适配、CLI 与 HTTP API
docs/            架构、决策记录、来源和运行手册
integrations/    GitHub、飞书等外部系统适配边界
workers/         Codex、Claude 等执行器契约与隔离说明
skills/          工程 skills 的来源、筛选和适配记录
deploy/          VM 与服务部署设计
runtime/         运行时状态、日志、缓存和工作区（默认不入 Git）
tests/           规则、配置和集成验证支持
scripts/         可重复的检查和运行辅助脚本
```

运行代码集中在 `mikasa/`；聊天由未修改的 Hermes Gateway 执行，`workers/hermes/bridge.py` 适配工程交付协议，工程文件/终端与工具循环由原生 Hermes Docker harness 执行。原生迁移与限制见 [原生运行记录](docs/NATIVE_HERMES_VALIDATION.md)。其他集成目录记录接入边界，不复制实现。代码存在、隔离测试通过与生产服务已运行是不同状态。

## 使用与维护

在本目录工作时，从 `AGENTS.md` 按顺序读取身份、工程契约和工程工作流。所有引用使用相对路径；目录可以整体迁移，不依赖主机全局 canonical 路径。

不同工具是否自动加载入口，需在各自会话中核实。运行时按 canonical 顺序读取规则，并通过 [Hermes 桥接](workers/hermes/README.md) 注入会话；规则和任务对应 skill 已在真实 SDK/CCH 调用中验证；其他工具的自动加载机制不由此证明。

角色风格集中在身份文件，工程权限和质量标准集中在契约，操作步骤集中在工作流。修改时同步直接受影响的入口和文档，避免复制多份正文。官方事实与本地判断分别注明来源。

纯文档变更检查相对链接、读取顺序、身份残留、审批规则一致性及空白格式。有 Git 仓库时增加 `git diff --check`，不运行会改写主目录的上游安装器。

## 当前边界

GitHub 主人为 `Ceng-0324`，Mikasa 称其为 `Shawn` 或 `Ceng`，`origin` 为 `git@github.com:Ceng-0324/MIKASA.git`；飞书对应人为曾俊轩。代码支持审计、任务拆解与分配、代码验证和提交、Issue/草稿 PR/正式 Review 发布；外部写入必须显式启用，并使用经账号核验的 Mikasa token。

默认由 Mikasa 审查人类 PR、负责人审查 Mikasa 的产出；该分工是可通过已确认交互更新的协作约定，默认不自动合并。

试点仓库 [Ceng-0324/FluxCore](https://github.com/Ceng-0324/FluxCore) 仅用于 Mikasa 开发完成后的运行验收，不作为先行开发对象。当前顺序为 Hermes 底层 → CCH 路由 → GitHub/飞书权限接入 → VM 部署 → 聊天工程任务与 FluxCore 联合验收，见 [功能规划](MIKASA_FUNCTION_PLAN.md)。任务事实源目前仍是本地 SQLite，计划迁往 Hermes Kanban；GitHub/飞书实际权限与 VM 尚未验收。不把平台强制审批门禁作为本体开发前置。CCH 返回模型标识与请求名的差异见联调记录。

## Git 工程状态

本目录默认分支为 `main`，远端为 `git@github.com:Ceng-0324/MIKASA.git`。Shawn/Ceng 已授权后续每轮任务完成后自动创建本地提交，禁止自动推送；远端推送由 Shawn/Ceng 执行。提交范围与验证约定见 [CONTRIBUTING.md](CONTRIBUTING.md)。

提交前阅读 [CONTRIBUTING.md](CONTRIBUTING.md)，并使用 [.github/PULL_REQUEST_TEMPLATE.md](.github/PULL_REQUEST_TEMPLATE.md) 记录变更目的、实际验证、安全边界和未完成事项。
