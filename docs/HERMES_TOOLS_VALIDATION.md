# Hermes 主动工具覆盖验证

日期：2026-09-20。基线 `6530d04` 加本轮工具扩展。固定 Hermes 0.21.3 源码 `f9524d3f119c672e4a4444f56d582e7475716ba3`，macOS arm64 / Python 3.12.13，沿用现有 Codex/CCH Responses 配置。脱敏机器证据见 [hermes-tools-evidence.json](hermes-tools-evidence.json)。

## 当前职责

| 路径 | Hermes 实际参与 | 宿主保留的职责 |
| --- | --- | --- |
| 拆解 | 主动列文件、搜索、读取源码，形成可验收任务 | 固定仓库版本、任务持久化、显式派发和发布 |
| 实现 | 检索源码、应用文件修改、请求预配置检查、根据失败在同一会话内修复 | 路径与权限校验、检查隔离、最终独立复验、本地 commit、等待负责人审批 |
| 审查 | 主动补读固定 PR head、分析需求和工程规范、报告缺陷 | 基线规则、产出归属、未读变更、CI 和 head/base 复核，审批/发布门禁 |
| 聊天 | 人格回复、连续上下文、会话模型选择 | 会话权限及存储；本轮未开放聊天执行仓库任务 |
| 审计与跟进 | 仍不调用 Hermes | 从 GitHub/SQLite 汇总确定性事实 |

这次扩展的是 Hermes 的实际工具循环。未开放任意终端、网页浏览、其他仓库、发布、自动合并、原生记忆或自主派发。

## 真实联调结果

所有场景都把初始源码快照预算设为 1 字节，强制通过工具获取完整文件。模型、SDK、工具通道、Git 工作区、SQLite 和本地检查真实执行；审查场景的 GitHub PR/CI 元数据使用合成数据，不证明真实 GitHub 权限。

| 场景 | 结果 | 用时 |
| --- | --- | --- |
| tool-loop | 10 次宿主工具调用，覆盖全部 5 个授权工具；读取 3 个源码/说明文件，先添加回归测试观察旧实现失败，再修复 clamp 使用 bounds 常量；2 项配置检查通过，宿主复验后提交，停在 awaiting_review | 124.308 秒 |
| tool-plan | 使用全部 3 个只读工具，基于实际源码拆解修复与测试任务，没有写入工具授权 | 34.600 秒 |
| tool-review | 使用全部 3 个只读工具，读取固定 PR head；在合成 CI 标绿的情况下发现负数未归零，返回 CHANGES_REQUESTED | 39.991 秒 |

实现任务 `952b990c2ce54625afe27d2b06f3c6ef` 的工具检查退出码顺序为 `5 → 1 → 0, 0`：首次无测试、加入回归测试后发现错误、修复后测试和独立行为断言均通过。最后宿主另外执行两项检查通过。工具调用和退出码来自宿主记录，不是模型自然语言自报。

另外运行无工作区人格探针（19.458 秒），正确回应身份、负责人和独立审批边界。三条工具链真实调用均加载人格 skill 和对应工程 skill，规则/skill SHA-256 由宿主核对。请求与 SDK 响应标识均为 `gpt-6-astra`；这仍不独立证明供应商底层模型身份。

上游会把插件工具渐进披露为 `tool_search/tool_describe/tool_call`。适配器使用官方注册及解析接口，分别核对模型可见入口和实际授权集合，没有改动 Hermes 上游源码。具体权限、上限和进程协议见 [执行器手册](../workers/hermes/README.md)。

## 复现

```sh
python3.12 scripts/probe_hermes.py --config config/local/hermes-cch.json --case tool-loop --case tool-plan --case tool-review --report runtime/state/hermes-cch/tool-coverage.json
```

探针只新建一次性合成仓库，发布关闭，真实密钥仅在内存传给模型进程；报告权限 0600。本机检查仅用于受信任的合成夹具，不能替代生产 Docker 隔离验收。

## 回归与边界

隔离回归覆盖专用 FD 进程通信、官方插件注册适配、红绿修复与最终复验、只读任务拒绝写入、固定 head 读取、凭据/规则/符号链接路径拒绝、禁止自选命令、工具预算、搜索截断、原始空白与读取摘要、Git 通配符路径不扩展、检查篡改索引/内容后拒绝交付、关闭时终止检查并回收线程、模型伪造证据覆盖，以及完整读取消除未读 PR 文件限制。检查命令与总结果见 [验证记录](VALIDATION.md)。

真实联调未涉及 FluxCore、GitHub 外部写入、Docker、Linux VM、飞书或长时间大仓库任务。搜索和读取仍有明确资源上限；超过上限必须报告缺口，不能据此宣称全仓审查完成。

## 后续：分页检索与分段上下文

基线 `c270b01` 上增加可续查搜索与分段读取。真实 Hermes/CCH 在 107 文件合成仓库中，初始源码预算为 1 字节：两次搜索越过前 100 个文件，找到 `z-spec.txt`；按偏移 0、16000、32000、48000、64000 分五页完整读取约 67 KB 文件，再读取 `calc.py` 并依据需求尾部示例生成任务。160.417 秒完成，8 次工具调用，全部验收通过。脱敏证据见 [hermes-pagination-evidence.json](hermes-pagination-evidence.json)。

```sh
python3.12 scripts/probe_hermes.py --config config/local/hermes-cch.json --case paged-context --report runtime/state/hermes-cch/paged-context.json
```

同一内容 SHA-256 的已读区间完整覆盖后，宿主才记录 `complete=true`；只读尾页、漏读中段或混用变化前后的内容均不能消除审查遗漏。单文件仍限制 1 MB、单次会话仍限制 64 次工具调用；本次不代表任意规模任务均能完成。搜索跳过的二进制、超限和受保护文件必须继续作为缺口说明。

## 后续：执行证据实时持久化

基线 `8aee0de` 上补齐宿主执行事件。真实 Hermes/CCH 实现任务完成 10 次工具调用、红绿修复、宿主独立验证及本地提交，84.779 秒，停在 awaiting_review；只读拆解使用 3 个工具，36.705 秒，完成。两条链路均通过持久化事件验收；只读任务仍为 running 时，另一个 SQLite 连接已可读到三次工具完成记录。脱敏证据见 [hermes-progress-evidence.json](hermes-progress-evidence.json)。

```sh
python3.12 scripts/probe_hermes.py --config config/local/hermes-cch.json --case tool-loop --case tool-plan --report runtime/state/hermes-cch/execution-progress.json
```

新增隔离测试证明模型失败/超时后证据保留、实时查询、取消后无迟到记录、旧令牌不能向重试任务写入、runner 恢复保留最后阶段、进度写入失败时不执行工具变更、成功时记录验证与提交。尚未在真实 VM 强杀/重启下验证；只有 started 的操作保持副作用未知，不自动重放。
