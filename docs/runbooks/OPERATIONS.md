# Mikasa 操作手册

## 环境和配置

本地核心需要 Python 3.12+ 和 Git；Hermes 单独安装。以下命令在项目根目录执行，Python 命令按机器实际路径替换。本地验证不需要真实 GitHub、CCH 或飞书凭据。

```sh
python3.12 -m unittest discover -v
python3.12 scripts/check_docs.py
python3.12 -m mikasa doctor
```

将 `config/examples/mikasa.json` 复制到 `config/local/mikasa.json`，保留 `project_root` 指向本项目。部署到 `/etc/mikasa/config.json` 时改为 `/opt/mikasa`，`runtime` 改为 `/var/lib/mikasa`。

仓库配置示例（仅结构示例，不代表已经授权该仓库）：

```json
"repositories": {
  "owner/repository": {
    "base": "main",
    "agent_image": "your-prepared-agent-image:version",
    "check_image": "your-prepared-test-image:version",
    "checks": [["python", "-m", "unittest", "discover", "-v"]]
  }
}
```

检查镜像必须提前安装且包含项目依赖，生产建议固定 digest。运行时使用 `--pull=never` 和 `--network=none`，不会在验证期间联网安装。宿主需有可用 Docker CLI；生产优先使用专用 VM 内的 rootless Docker。容器仅挂载任务工作区，不挂载 token、服务配置或 Docker socket。`allow_local_checks=true` 仅用于受信任夹具，不能用于不可信 PR。

`agent_image` 用于 Hermes 原生探索/编辑容器，省略时使用固定 Python slim 镜像；`check_image` 用于独立验收。原生容器只挂载导出的快照（审查为只读），没有真实 `.git`。验收和最终提交前由宿主校验并导入变更。工程能力与实际容器验证见 [验证边界](../VALIDATION.md)。

公开仓库默认通过 HTTPS clone。本地绝对路径 `source` 可用于隔离测试或管理员预先准备的私有仓库镜像；当前不把 GitHub token 交给 clone 工作器。私有仓库首次拉取仍需管理员配置只读镜像获取机制。

模型配置见 [Hermes 执行器](../../workers/hermes/README.md)。需要明确模型名、兼容 API 端点和 API key；默认由环境提供；本机联调也可显式选择 `worker.model_source.type=codex`，只读 provider 配置和 API key，不复制认证文件，不迁移 OAuth 会话。真实联调范围见 [验证边界](../VALIDATION.md)。任务结果的 `execution.granted_tools` 显示授权集合，`execution.tool_events` 保存同次执行的工具/检查证据，`checks` 保存最终独立验收；旧结果中的 `attempts` 仅为历史，新的任务不再生成外层修复轮列表。

## 启动和任务流程

上线前使用 `doctor --probe-model` 检查实际 worker → 模型端点调用；普通 `doctor` 不联网。配置、故障分类和 `default` 分组的证据边界见 [CCH 诊断](CCH.md)。

为配置中的每个 HTTP 账号准备不同的至少 32 字符 token。需要 GitHub 功能时设置 `MIKASA_GITHUB_TOKEN`，需要 webhook 时设置 `MIKASA_GITHUB_WEBHOOK_SECRET`。不要将真实值写入版本库、shell 命令示例或聊天。

分别启动两个进程：

```sh
python3.12 -m mikasa --config config/local/mikasa.json serve
python3.12 -m mikasa --config config/local/mikasa.json run
```

周期审计由同一个 runner 唤醒 Hermes Cron。设置 `schedules.audit_interval_seconds` 后，首次等待一个间隔才入板；0 关闭。原生 job、下次时间、失败与 execution 保存在配置 runtime 下的 `scheduler/cron/`，暂停和重启语义见 [当前架构](../architecture/README.md)。不要为该专用 home 再启动另一个原生 ticker。它只生成审计任务，不调用模型或对外投递消息。

在另外的终端提交任务，`owner/repository` 替换成配置允许的仓库：

```sh
python3.12 -m mikasa --config config/local/mikasa.json submit plan owner/repository '需求描述' --acceptance '可验证的完成条件'
python3.12 -m mikasa --config config/local/mikasa.json list
python3.12 -m mikasa --config config/local/mikasa.json show TASK_ID
python3.12 -m mikasa --config config/local/mikasa.json events TASK_ID
```

运行期间可重复查询 `events TASK_ID`，读取 `kind=execution` 的阶段与工具记录，不必等待任务结束。worker/tool 的 `invocation` 区分每次模型调用；tool 的 `call` 配对 started/completed。completed 只表示调用返回，检查是否成功看退出码。失败、超时、进程中断后已记录事件继续保留；最后只有 started 时，副作用状态未知，应核对工作区后再重试。

拆解完成后 `expand TASK_ID` 生成具有依赖关系的实施任务。`assign TASK_ID ACCOUNT` 明确移交；交给人类的任务不会被 runner 自动接管。分析报告的 `done` 表示报告完成，代码任务的 `awaiting_review` 表示已生成并验证本地提交、等待后续协作处理。它是过渡任务状态，不是指定审批人的硬门禁；可按本次验收约定执行 `complete TASK_ID --evidence '实际交付依据'`，无需绑定 PR 合并。

## 发布与审批

默认 `github.publish_enabled=false`。在获得外部写入授权并配置 `Mikasa-0910` 账号 token 后才启用。`publish TASK_ID` 需要负责人 CLI 或 API 身份；首次发布前核验 token 的 GitHub login。

- plan 发布为包含完整拆解的单个 Issue；不会一次创建大量未确认的子 Issue。
- implement 推送 `mikasa/task-<任务ID>` 分支并创建草稿 PR，提供实现与验证说明；不会合并。
- review 发布 Agent 给出的正式 Review 及可阅读结论，不要求先登记产出归属。默认审查安排由工程规则、skills 和已确认的记忆指导；GitHub 自身权限与 Review 限制仍生效。

发布前核对 head、目标基线及 CI 证据；发生变化需重新审查，避免发布过期报告。宿主附上缺失文件/CI 证据的限制说明，但不改写 Agent 的结论，也不选择必须批准的人。审查结论不再保证经过 Mikasa 专属机器政策校验。

`gate`、`provenance`、`reconcile` 已删除，不再发布 `mikasa/approval` status。已有数据库的 reviews 表只保留历史内容，不再读写。若某个外部仓库曾手工要求该 status，需要仓库管理员另行调整平台配置；本次没有读取或修改远端保护规则。现有 CI status 统一按实际状态报告，不隐去旧审批 status。

## 暂停、失败和恢复

`pause` 阻止新任务和发布，并使正在运行的模型/检查子进程终止；网络读取可能在超时后返回。`resume` 允许后续任务。暂停不撤回已经发送的外部请求。

模型/检查有超时、输出上限和原生工具迭代预算。检查/修复在同次 worker 内完成；宿主最终验收失败返回 blocked，不启动额外修复轮。失败结果及工作区保留在 runtime；`retry TASK_ID` 使用新尝试目录，不覆盖旧现场，恢复原生任务历史并传入上次最终验收结果，Agent 须重新确认当前源码。`worker.max_attempts` 已停用，旧配置由 doctor 提示清理。runner 使用独占锁；进程崩溃后，下一次启动将遗留 running 标记失败，不自动重做可能已产生副作用的操作。

发布超时进入 uncertain，禁止自动重发。先在 GitHub 查找带有 `mikasa-task:<ID>` 标记的产物，再执行 `resolve-publication TASK_ID EXTERNAL_ID` 读取验证回执。若只有分支已推送而 PR 未创建，可人工按原任务标记建立 PR 后核对。确认完全没有发布时，取消旧任务并以新的幂等键重建任务；不要直接清除 publications 表以绕过防重。

一致性备份：

```sh
python3.12 -m mikasa --config config/local/mikasa.json backup /secure/backups/mikasa-state
python3.12 -m mikasa --config config/local/mikasa.json restore /secure/backups/mikasa-state /var/lib/mikasa-restored
```

先停止 API、runner、原生 CLI 及自行启动的 Hermes 进程。备份覆盖 runtime 下的 mikasa.sqlite3、kanban、scheduler、native、engineering、workspaces，包括会话、记忆、Cron、回执和 Git 对象；受管进程的维护锁与旧 profile/runner 锁阻止并发快照。运行数据库使用固定 Hermes 的 WAL 安全快照 helper；停服后的 Git 工作区按字节保留数据库夹具及其 WAL，避免改写已验证文件。备份清单版本 2，逐文件记录 SHA-256；旧双库目录不作为完整恢复点。

备份与恢复均要求源目录外的新目标，先在私有临时目录完成，再整体发布。目录 0700，普通文件 0600，可执行文件 0700。恢复先验证清单与内容，重建内部符号链接，并迁移配置和任务的运行定位路径；历史会话和事件保留原文。不覆盖现有 runtime，不启动服务，也不改当前配置。将外部配置的 runtime 指向恢复目录后，先 doctor、检查任务与回执，再显式启动；失败或中断任务按原生恢复语义处理，不自动重做。

备份是私密数据，含本机生成的 `.api-key`，用于维持原生运行回执的认证范围。外部模型/GitHub/飞书认证来源不读取；已知凭据文件、profile 日志/缓存/锁和未受管根目录不包含，profile config 的直接密钥字段被移除，环境变量引用保留。Git 工作区按现场保留，不因源码目录名为 cache 或 logs 而排除。源码、Git 历史和会话本身可能包含敏感内容，备份不是脱敏导出；外部工具/provider 状态与自定义认证须独立管理。外部符号链接拒绝备份，不跟随读取。目标机器仍需相同 Hermes 版本、项目、镜像和外部凭据。恢复后 scheduler 的受管配置在首次 tick 重新生成；自定义原生任务和工具引用的外部路径须自行核对。

## VM 部署

按 [VM 部署手册](../../deploy/vm/README.md)执行。当前提供统一消息 Gateway、API 和 runner 的 systemd 模板；首先部署飞书/微信，工程任务及公网 API 后续接入。以专用 `mikasa` 用户运行，代码位于 `/opt/mikasa`、Hermes 位于 `/opt/hermes`，状态位于 `/var/lib/mikasa`，凭据由 `/etc/mikasa/runtime.env` 注入；各 home 由项目配置与 Hermes profile 管理，不能使用个人 home。

模板包含只读系统目录、PrivateTmp、NoNewPrivileges、0077 umask 和进程组终止。模板尚未在目标 Linux VM 验证；部署时运行 `systemd-analyze verify`，确认 Python 路径、Docker 访问、可写目录、网络和 TLS 后再安装启用。停止服务由 systemd 杀死完整控制组；容器异常残留需按 `mikasa-check-` 前缀检查清理。

本体本地测试通过后再将 FluxCore 加入运行配置，执行只读审计和无破坏性任务验收。真实模型响应、GitHub 写权限、协作审查流程和 VM 恢复分别验收，不以夹具结果替代。

旧任务首次访问会迁入原生 Kanban，原表改名为只读 legacy_tasks。升级前停止旧 API/runner 并保留整套 runtime；不混跑新旧版本，不仅恢复业务 SQLite。迁移校验与回滚边界见 [当前架构](../architecture/README.md)。
