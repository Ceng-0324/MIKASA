# AGENTS.md

本文件向在 Mikasa 仓库工作的 coding agent 提供开发指令：建立上下文、定位代码、遵守修改边界，并验证交付。适用范围为本仓库。项目介绍见 [README.md](README.md)，贡献流程见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 建立上下文

开始任务前，按顺序完整读取：

1. [identity.md](identity.md)：理解 Mikasa 的产品人格、关系与表达要求。
2. [engineering-contract.md](engineering-contract.md)：确认授权、质量和协作边界。
3. [engineering-workflow.md](engineering-workflow.md)：按任务类型选择执行与验证步骤。

上述文件各自维护完整规则，本入口只补充仓库开发细节。不要把身份正文复制到工具入口或 skills，也不要改写开发者的全局配置。

默认用中文沟通。先检查当前分支、工作树和相关实现，再动手修改；保留已有的未提交工作。以当前任务确定范围，实现任务持续推进到验证完成，咨询任务交付调查与判断。

## 定位实现

| 要修改的行为 | 从这里开始 |
| --- | --- |
| 命令入口与配置解析 | `mikasa/cli.py`、`mikasa/config.py` |
| Hermes 启动、profile 与工程入口 | `mikasa/native.py`、`mikasa/engineering_cli.py`、`workers/hermes/` |
| 模型来源与平台连接 | `mikasa/model_settings.py`、`mikasa/connections.py` |
| 人格与工程 skills 加载 | `mikasa/skills.py`、`skills/manifest.json`、`skills/` |
| 备份、部署与维护 | `mikasa/backup.py`、`mikasa/maintenance.py`、`deploy/vm/` |
| 回归测试与联调 | `tests/`、`scripts/` |

沿调用链读取相邻实现和测试。Hermes 的固定版本与安装方法见 [workers/hermes/README.md](workers/hermes/README.md)，配置字段见 [config/README.md](config/README.md)。搜索时排除运行数据、依赖缓存和生成目录。

## 修改时保持的约束

- 新增 Agent 能力前，先检查固定版本 Hermes 的原生实现。工具循环、会话、记忆、委派、调度和 Gateway 由 Hermes 管理，不在 Mikasa 中重复实现。
- 模型与服务端路由交给 CCH；协议和 `/model` 沿用 Hermes。Mikasa 只适配已配置的模型来源，不猜测分组或静默切换凭据。
- 更新 profile 时保留原生模型选择、用户偏好、会话和持久记忆；身份及受管配置的刷新不能覆盖用户状态。
- 协作约定放在规则、skills 和原生记忆中，不增加硬编码审批引擎或工具限制。架构依据见[架构说明](docs/architecture/README.md)。
- 修改行为时同步调用方、相关测试和使用文档。公开文档维护当前用法，避免保留失效入口或一次性进度记录。
- 本地配置、认证、会话、日志、缓存和工作副本不进入 Git。示例使用占位值，输出与提交中不得包含凭据。

## 验证改动

使用 Python 3.12+，在仓库根目录执行相关检查：

```sh
python3.12 -m unittest discover -v
python3.12 scripts/check_docs.py
python3.12 -m mikasa doctor
git diff --check
```

纯文档改动检查内容、相对链接、规则读取顺序与格式。运行代码改动先跑相关测试，再按影响面执行完整检查；涉及 Hermes 集成时准备固定版本依赖。`doctor` 默认检查本地配置，不证明真实模型或平台连通；联调须使用实际配置，并如实区分通过、未运行和缺少外部条件。

## 交付结果

复核 diff，只保留任务相关改动，说明行为变化、验证结果和未覆盖部分。提交、部署与发布按当前任务授权执行，不自动推送或合并。不要把代码已修改、测试通过和服务已部署混为同一状态。
