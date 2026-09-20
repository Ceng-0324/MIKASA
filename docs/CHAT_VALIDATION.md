# 聊天模型切换验证

日期：2026-09-20；对象：Mikasa 基线 `3164e4e` 加本轮工作区。调研来源与方案见 [架构决定](decisions/0002-chat-model-switching.md)。真实结果摘要见 [chat-switch-evidence.json](chat-switch-evidence.json)。

## 真实执行

本机实际运行 HTTP API → Chat → Hermes 0.21.3 → 现有 Codex/CCH Responses。五次调用均经过真实模型；HTTP API token 仅在内存生成和使用。没有 CCH 管理端写入，也没有调用 GitHub 或改动 FluxCore。

| 输入/阶段 | 请求模型 | SDK 观察到的响应模型 | 结果 |
| --- | --- | --- | --- |
| 记住随机验收代号 | gpt-6-astra | gpt-6-astra | 正确确认 |
| 切换为 gpt-5.6-luna | gpt-5.6-luna | gpt-5.6-luna | 验证通过，revision=1 |
| 复述验收代号 | gpt-5.6-luna | gpt-5.6-luna | 正确复述，历史保留 |
| 恢复默认模型 | gpt-6-astra | gpt-6-astra | 验证通过，revision=2 |
| 再次复述代号 | gpt-6-astra | gpt-6-astra | 正确复述 |

同一 Idempotency-Key 重放切换请求，返回原回复，没有增加模型调用和聊天记录。之后通过新 CLI 进程查询会话，读到已保存的默认模型与 revision=2。

本轮 SDK 响应标识与请求相同；早先直接 Responses 探针曾返回不同标识，保留在历史联调记录中。不能用本轮结果抹去历史差异，也不能把标识当成底层模型身份的独立认证；实际供应商映射需以 CCH 管理端为准。

## 可重复执行

```sh
python3.12 scripts/probe_chat.py --config config/local/hermes-cch.json --target gpt-5.6-luna --report runtime/state/hermes-cch/chat-switch-probe.json
```

目标必须与当前默认请求模型不同，且支持当前配置的协议。该命令会创建新的合成聊天、调用真实模型并产生 API 费用，完成后关闭临时 HTTP 服务。报告和数据库只在被忽略的 runtime 中，报告权限 0600。

## 回归检查

`python3.12 -m unittest discover -v`：64 项通过，27.416 秒。文档链接/空白、Python compileall、Git diff 检查及网页 JavaScript 语法检查通过。扫描 136 个运行文件与 81 个 Git 可纳入文件，未发现当前实际 CCH API key 的完整字节串。

## 验证边界

自动化测试覆盖未知/错误模型导致验证失败时保留原配置、会话隔离、跨账号拒绝、命令歧义、重复请求、并发锁、暂停期间不提交、上下文截断，以及 bridge 传递模型和记录 response_model。失败场景使用确定性夹具；未向 CCH 反复发送无效模型请求。

网页静态入口、HTTP 鉴权与状态流已经自动化验证，内嵌 JavaScript 通过 Node 语法检查；未运行真实浏览器视觉验收。原工程工作流通过完整回归；模型切换目前仅作用于聊天。飞书入口、其他模型家族的协议兼容和网关后台热更新传播没有执行真实验收。
