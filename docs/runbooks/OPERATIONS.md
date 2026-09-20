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
    "check_image": "your-prepared-test-image:version",
    "checks": [["python", "-m", "unittest", "discover", "-v"]]
  }
}
```

检查镜像必须提前安装且包含项目依赖，生产建议固定 digest。运行时使用 `--pull=never` 和 `--network=none`，不会在验证期间联网安装。宿主需有可用 Docker CLI；生产优先使用专用 VM 内的 rootless Docker。容器仅挂载任务工作区，不挂载 token、服务配置或 Docker socket。`allow_local_checks=true` 仅用于受信任夹具，不能用于不可信 PR。

公开仓库默认通过 HTTPS clone。本地绝对路径 `source` 可用于隔离测试或管理员预先准备的私有仓库镜像；当前不把 GitHub token 交给 clone 工作器。私有仓库首次拉取仍需管理员配置只读镜像获取机制。

模型配置见 [Hermes 执行器](../../workers/hermes/README.md)。需要明确模型名、兼容 API 端点和 API key；这些信息由环境提供，不从个人工具认证文件复制。

## 启动和任务流程

为配置中的每个 HTTP 账号准备不同的至少 32 字符 token。需要 GitHub 功能时设置 `MIKASA_GITHUB_TOKEN`，需要 webhook 时设置 `MIKASA_GITHUB_WEBHOOK_SECRET`。不要将真实值写入版本库、shell 命令示例或聊天。

分别启动两个进程：

```sh
python3.12 -m mikasa --config config/local/mikasa.json serve
python3.12 -m mikasa --config config/local/mikasa.json run
```

在另外的终端提交任务，`owner/repository` 替换成配置允许的仓库：

```sh
python3.12 -m mikasa --config config/local/mikasa.json submit plan owner/repository '需求描述' --acceptance '可验证的完成条件'
python3.12 -m mikasa --config config/local/mikasa.json list
python3.12 -m mikasa --config config/local/mikasa.json show TASK_ID
python3.12 -m mikasa --config config/local/mikasa.json events TASK_ID
```

拆解完成后 `expand TASK_ID` 生成具有依赖关系的实施任务。`assign TASK_ID ACCOUNT` 明确移交；交给人类的任务不会被 runner 自动接管。分析报告的 `done` 表示报告完成，代码任务的 `awaiting_review` 表示已生成并验证本地提交，尚未完成独立审批和交付。

## 发布与审批

默认 `github.publish_enabled=false`。在获得外部写入授权并配置 `Mikasa-0910` 账号 token 后才启用。`publish TASK_ID` 需要负责人 CLI 或 API 身份；首次发布前核验 token 的 GitHub login。

- plan 发布为包含完整拆解的单个 Issue；不会一次创建大量未确认的子 Issue。
- implement 推送 `mikasa/task-<任务ID>` 分支并创建草稿 PR，记录 Mikasa 产出；不会合并。
- review 发布正式 Review 及可阅读的结论。纯人类实现需先通过 `provenance REPO PR HEAD human` 确认当前 head 归属；任何 Mikasa 参与实现的 PR 保留为 Mikasa 产出。

发布前核对当前版本，head 或目标基线变化就重新审查。`gate REPO PR` 仅输出政策检查，`gate REPO PR --publish` 显式发布 `mikasa/approval` commit status；均不配置平台保护。门禁的 CI 判定排除自身 status，避免循环依赖。部署时需要将该 context 配为 required、绑定可信发布来源并要求分支更新，同时在 PR/Review/CI 变化后重新检查；这些平台设置需负责人另行授权和验证，不能用文档或 CLI 结果声称已强制执行。

Mikasa 实现的 PR 由 `Ceng-0324` 正式批准、有权限的人手动合并后，执行 `reconcile TASK_ID PR_NUMBER`。运行时核对 head、PR 作者、负责人当前审批、CI 和合并事实后才把任务置为 done。

## 暂停、失败和恢复

`pause` 阻止新任务和发布，并使正在运行的模型/检查子进程终止；网络读取可能在超时后返回。`resume` 允许后续任务。暂停不撤回已经发送的外部请求。

模型/检查有超时、输出上限和最多修复次数。失败结果及工作区保留在 runtime；`retry TASK_ID` 使用新尝试目录，不覆盖旧现场。runner 使用独占锁；进程崩溃后，下一次启动将遗留 running 标记失败，不自动重做可能已产生副作用的操作。

发布超时进入 uncertain，禁止自动重发。先在 GitHub 查找带有 `mikasa-task:<ID>` 标记的产物，再执行 `resolve-publication TASK_ID EXTERNAL_ID` 读取验证回执。若只有分支已推送而 PR 未创建，可人工按原任务标记建立 PR 后核对。确认完全没有发布时，取消旧任务并以新的幂等键重建任务；不要直接清除 publications 表以绕过防重。

一致性备份：

```sh
python3.12 -m mikasa --config config/local/mikasa.json backup /secure/backups/mikasa.sqlite3
```

目标文件必须不存在，备份权限为 0600。数据库包含任务上下文，工作区需按相同访问级别另行备份。恢复前停止 API 和 runner，用备份替换运行数据库并恢复相应工作区；不要在服务活跃时覆盖 WAL 数据库。保留当前数据库副本用于回滚。恢复后先运行 doctor，检查中断任务和发布回执，再 resume。

## VM 部署

`deploy/vm/` 提供 systemd API 和 runner 模板。以专用 `mikasa` 用户安装项目到 `/opt/mikasa`、Hermes 到 `/opt/hermes`，状态放 `/var/lib/mikasa`，受限环境文件放 `/etc/mikasa/runtime.env`。设置 `HERMES_HOME=/var/lib/mikasa/hermes`，不能使用个人 home。

模板包含只读系统目录、PrivateTmp、NoNewPrivileges、0077 umask 和进程组终止。模板尚未在目标 Linux VM 验证；部署时运行 `systemd-analyze verify`，确认 Python 路径、Docker 访问、可写目录、网络和 TLS 后再安装启用。停止服务由 systemd 杀死完整控制组；容器异常残留需按 `mikasa-check-` 前缀检查清理。

本体本地测试通过后再将 FluxCore 加入运行配置，执行只读审计和无破坏性任务验收。真实模型响应、GitHub 写权限、独立审批、仓库强制门禁和 VM 恢复分别验收，不以夹具结果替代。
