"""Hermes command APIs with Mikasa's explicitly enabled chat surface."""
from mikasa.errors import MikasaError
from mikasa.model_settings import validate_model


def dispatch(text):
    from hermes_cli.commands import resolve_command

    word, *rest = text.strip().split(maxsplit=1)
    args = rest[0] if rest else ""
    definition = resolve_command(word)
    name = definition.name if definition else None
    result = {"name": name, "kind": "unsupported_command", "target": None, "reply": None}
    if name == "model":
        from hermes_cli.model_switch import parse_model_switch_args
        parsed = parse_model_switch_args(args)
        # Hermes also supports global config writes, credential discovery and
        # one-turn overrides. Those are not capabilities of this chat surface.
        if (parsed.errors or parsed.is_global or parsed.is_once or parsed.force_refresh
                or parsed.explicit_provider or parsed.reasoning_effort):
            result.update(kind="help", reply="当前只支持会话内切换，可使用 --session；未启用全局配置、单轮覆盖、provider、reasoning 或目录刷新参数。")
        elif not parsed.target:
            result["kind"] = "status"
        elif parsed.target == "default":
            result["kind"] = "reset"
        else:
            try:
                result.update(kind="switch", target=validate_model(parsed.target))
            except MikasaError:
                result.update(kind="help", reply="请使用一个完整模型 ID。")
    elif name in {"new", "help", "version"}:
        if args:
            result.update(kind="help", reply=f"当前 /{name} 不接受参数，未执行操作。")
        elif name == "version":
            from hermes_cli.slash_exec import CommandContext, execute_command
            result.update(kind="version", reply=execute_command(name, CommandContext(surface="gateway")).text)
        else:
            result["kind"] = name
    elif name == "init":
        result.update(kind="deferred_command", reply="/init 会生成或修改仓库 AGENTS.md，尚未接入聊天工程任务与仓库授权；本次未执行文件操作。")
    return result
