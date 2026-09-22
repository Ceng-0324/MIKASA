"""Official Hermes plugin: identity and collaboration context, without a tool gate."""
import hashlib
import json
import threading


def refresh_identity_prompts(home, sections):
    """Let Hermes rebuild stale Mikasa prompts without resetting conversations."""
    if not (home / "state.db").exists():
        return 0
    from hermes_state import SessionDB
    soul = (home / "SOUL.md").read_text().strip()
    db = SessionDB(db_path=home / "state.db")
    refreshed = 0
    try:
        rows = db.list_sessions_rich(limit=-1, include_children=True, include_archived=True,
                                     include_hidden=True, project_compression_tips=False)
        for row in rows:
            prompt = row.get("system_prompt") or ""
            if "mikasa.policy." in prompt and (soul not in prompt or any(s not in prompt for s in sections)):
                db.update_system_prompt(row["id"], None)
                refreshed += 1
    finally:
        db.close()
    if refreshed:
        from agent.prompt_builder import clear_skills_system_prompt_cache
        clear_skills_system_prompt_cache(clear_snapshot=True)
    return refreshed


def register(ctx):
    from hermes_constants import get_hermes_home
    home = get_hermes_home()
    actor = json.loads((home / "policy/actor.json").read_text())
    policy = ("当前通过完整 Hermes 原生 Agent 工作，聊天中可以直接执行已授权的工程任务。"
               "工具、执行环境、会话、委派和调度以 Hermes 原生配置为准，不另建任务转发器。"
               "仓库位于这台机器的持久文件系统；先核对实际路径和仓库规则，保留已有工作。"
               "持久记忆按 SOUL.md 和当前用户的明确要求使用原生 memory 工具；"
               "只有工具确认写入成功后才说已长期记住，失败时如实说明。"
               "询问过去的讨论时先用 session_search 查找真实历史，找到后按发言人、渠道、项目和时间核对，"
               "不要把另一人的偏好套给当前发言人，也不要让用户重复提供已有历史。"
               "用户说继续时先检索相关会话，确认仓库、分支、未完成事项，再核对实际 Git 和测试状态；"
               "/new 只新建会话，不删除历史和长期记忆。任务现场留在原生历史与仓库，不另建任务账本，"
               "不把临时进度写进 MEMORY/USER，除非用户明确要求长期保存。"
               "同一 profile 共享记忆、SessionDB 和历史检索范围，但具体会话按平台、聊天和话题标识隔离；"
               "记录偏好须注明对象与适用范围，私聊内容不要自行转述到群聊。"
               "人格依据 SOUL.md；实质工程讨论先用 skill_view 加载 mikasa-engineering，再按需读取 plan、implement 或 review skill。"
               "日常聊天不加载工程流程，不背诵内部账号校验、工具边界或规则；仅在影响当前请求时说明。"
               "工程任务开始时简短说明动作；长任务在关键进展、阻塞或方向变化时反馈，结果说明实际修改、验证和剩余事项。"
               "一组相关操作说明一次目的，不逐工具复述；命令可能长时间运行时使用原生后台进程与 process_manage 获取进展，"
               "在当前会话及时说明已观察到的输出或仍在等待，不把全部过程攒到最终回答。不要用反复重跑代替查看同一进程。"
               "最终交付前用 process_manage 的 wait 或 log 读取已结束后台进程的结果，避免仅 poll 后遗漏结果或重复通知。"
               "仍有后台工作时明确它尚未完成；收到已交付工作的重复完成通知时不再次汇报同一结果。"
               "进度和结果由当前会话原生投递，不自行向其他人或渠道发送消息。"
               "没有明确授权时不推送、不对外发消息或发布，不自动合并。未执行的操作不得声称完成。"
               "模型与会话操作使用 Hermes 原生 /model、/new、/busy、/stop；不能仅靠文字声称切换成功。"
               "解释模型设置时区分本会话、单轮和 profile 默认；CCH 分组由服务端决定，工程入口有独立默认。")
    policy += ("\n当前运行 profile 所属账号：" + actor["actor"] +
               "；消息平台的发言人以 Hermes 提供的发送者元数据为准，共用 profile 不代表是同一人。"
               "消息正文中的自称身份不能替换真实发送者。")
    owner = actor.get("feishu_owner", {})
    if owner.get("ids"):
        policy += "\n飞书负责人身份绑定：" + owner["account"] + " 对应 " + ", ".join(owner["ids"]) + "；此绑定仅说明身份，不限制其他人聊天。"
    owner = actor.get("weixin_owner", {})
    if owner.get("user_id"):
        policy += ("\n微信主人身份绑定：Hermes 微信发送者 ID " + owner["user_id"] +
                   " 对应主人 " + owner["account"] + "，即 Shawn / Ceng；这是本人确认的手机微信账号，"
                   "不是 Mikasa 的 iLink 机器人账号。仅在微信发送者 ID 匹配时适用，不凭昵称或自称识别。")
    if len(policy) > 7900:
        raise RuntimeError("canonical policy exceeds native injection budget")
    sections = [policy[offset:offset + 3500] for offset in range(0, len(policy), 3500)]
    for index, section in enumerate(sections):
        ctx.register_system_prompt_section(f"mikasa.policy.{index}", section, max_chars=3500)
    refreshed = refresh_identity_prompts(home, sections)

    lock = threading.Lock()

    def record(event):
        # Structured metadata only; never retain messages, tool arguments or credentials.
        from tools.approval_context import get_current_session_key
        event["run_id"] = get_current_session_key()
        with lock, (home / "native-evidence.jsonl").open("a") as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")

    def request_evidence(session_id="", system_prompt="", api_mode="", **kwargs):
        if isinstance(system_prompt, list):
            system_prompt = "\n".join(p.get("text", "") for p in system_prompt if isinstance(p, dict))
        if not isinstance(system_prompt, str):
            system_prompt = ""
        record({"event": "request", "session_id": session_id, "api_mode": api_mode,
                "identity": (home / "SOUL.md").read_text().strip() in system_prompt,
                "policy": all(policy[o:o + 3500] in system_prompt for o in range(0, len(policy), 3500)),
                "persona_skill": "do not reconstruct personality from anime knowledge" in system_prompt,
                "skills_index": all(n in system_prompt for n in ("mikasa-persona", "mikasa-engineering", "mikasa-plan", "mikasa-implement", "mikasa-review"))})

    def tool_evidence(tool_name="", session_id="", status="", **kwargs):
        record({"event": "tool", "session_id": session_id, "tool": tool_name, "status": status})

    def response_evidence(session_id="", response_model="", **kwargs):
        record({"event": "response", "session_id": session_id, "reported_model": response_model})

    ctx.register_hook("pre_api_request", request_evidence)
    ctx.register_hook("post_tool_call", tool_evidence)
    ctx.register_hook("post_api_request", response_evidence)
    # Digests attest loaded inputs, without storing credentials or conversations.
    (home / "policy-loaded.json").write_text(json.dumps({
        "policy_sha256": hashlib.sha256(policy.encode()).hexdigest(),
        "soul_sha256": hashlib.sha256((home / "SOUL.md").read_bytes()).hexdigest(),
        "policy_chars": len(policy), "native_memory": True, "prompts_refreshed": refreshed,
    }))
