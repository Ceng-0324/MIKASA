import argparse
import json
import os
import shutil
import signal
import sys
import time
import uuid

from .config import Config, KINDS
from .errors import MikasaError
from .service import Service


def parser():
    p = argparse.ArgumentParser(description="Mikasa 工程协作运行时；本地 CLI 使用受信任的操作系统账号")
    p.add_argument("--config", default="config/examples/mikasa.json")
    commands = p.add_subparsers(dest="command", required=True)
    diagnostic = commands.add_parser("doctor")
    diagnostic.add_argument("--probe-model", action="store_true", help="经当前 worker 发起一次真实模型调用；会消耗模型额度")
    diagnostic.add_argument("--model", help="诊断指定模型的路由；不改变默认模型或聊天")
    commands.add_parser("serve")
    connections = commands.add_parser("connections", help="检查平台配置；--probe 只读联网，不发消息或发布")
    connections.add_argument("platform", choices=("github", "feishu", "weixin"))
    connections.add_argument("--probe", action="store_true")
    gateway = commands.add_parser("gateway", help="启动一个 Hermes 原生 Gateway，可同时接入多个消息平台")
    gateway.add_argument("--platform", choices=("feishu", "weixin"), action="append", required=True)
    commands.add_parser("weixin-login", help="用 Hermes 原生二维码绑定微信；不启动收发或调用模型")
    chat = commands.add_parser("chat", help="启动原生 Hermes 交互；/model、/new 等由 Hermes 处理")
    chat.add_argument("--session", help="恢复原生会话 ID；--message 模式使用旧 API 聊天 ID")
    chat.add_argument("--message", help="使用现有 HTTP 聊天适配发送单条消息，输出 JSON")
    worker = commands.add_parser("run")
    worker.add_argument("--once", action="store_true")
    create = commands.add_parser("submit")
    create.add_argument("kind", choices=sorted(KINDS))
    create.add_argument("repo")
    create.add_argument("title")
    create.add_argument("--acceptance", required=True)
    create.add_argument("--pr", type=int)
    create.add_argument("--assignee")
    create.add_argument("--depends-on", action="append", default=[])
    create.add_argument("--key", default=None)
    commands.add_parser("list")
    for name in ("show", "events", "cancel", "retry", "expand", "publish"):
        cmd = commands.add_parser(name)
        cmd.add_argument("task")
    assign = commands.add_parser("assign")
    assign.add_argument("task")
    assign.add_argument("assignee")
    complete = commands.add_parser("complete")
    complete.add_argument("task")
    complete.add_argument("--evidence", required=True)
    resolve = commands.add_parser("resolve-publication")
    resolve.add_argument("task")
    resolve.add_argument("external_id", type=int)
    commands.add_parser("pause")
    commands.add_parser("resume")
    backup = commands.add_parser("backup", help="停服后备份完整受管状态到新目录")
    backup.add_argument("destination")
    restore = commands.add_parser("restore", help="校验备份并恢复到新 runtime；不覆盖现有目录或启动服务")
    restore.add_argument("source")
    restore.add_argument("destination")
    return p


def doctor(config, *, probe_model=False, selected_model=None):
    from .skills import skill_inventory
    from .model_settings import model_diagnostics
    from .model_errors import ModelFailure
    from .worker import Worker
    from .kanban import Kanban
    command = config.data.get("worker", {}).get("command", [])
    model = model_diagnostics(config.data.get("worker", {}), selected_model)
    if probe_model and model["configuration"] == "valid":
        worker = Worker(config)
        try:
            worker.execute({"payload": {"kind": "chat", "title": "请简短回复：模型连接验证完成。"}}, {},
                           lambda: False, model=model["requested_model"])
        except MikasaError as exc:
            model.update({"connection": "failed", "error": str(exc)})
            if isinstance(exc, ModelFailure):
                model["error_code"] = exc.code
        else:
            runtime = worker.last_runtime or {}
            reported = runtime.get("reported_model")
            model.update({"connection": "passed", "backend": runtime.get("backend"),
                          "reported_model": reported,
                          "model_match": "unreported" if not reported else "same" if reported == model["requested_model"] else "different",
                          "identity_note": "响应标识不能独立证明底层模型身份"})
    return {"python": sys.version.split()[0], "git": bool(shutil.which("git")),
            "rules": "loaded", "tasks": Kanban(config).diagnostics(), "skills": skill_inventory(config.root), "repositories": list(config.data.get("repositories", {})),
            "schedules": {"backend": "hermes_cron", "connection": "not_checked",
                          "audit_interval_seconds": config.data.get('schedules', {}).get('audit_interval_seconds', 0)},
            "worker_configured": bool(command), "worker_executable": bool(command and shutil.which(command[0])),
            "github_token_present": bool(os.environ.get(config.data.get("github", {}).get("token_env", "MIKASA_GITHUB_TOKEN"))),
            "publishing_enabled": config.data.get("github", {}).get("publish_enabled", False), "model": model,
            "deprecated_settings": (["worker.max_attempts 已停用；检查和修复由执行器工具循环完成"]
                                    if "max_attempts" in config.data.get("worker", {}) else []),
            "note": "默认仅检查本地前提；模型探针不证明 CCH 分组、GitHub 权限或 VM 已完成联调"}


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        config = Config.load(args.config)
        if args.command == "weixin-login":
            from .connections import login_weixin
            return login_weixin(config)
        if args.command == "connections":
            from .connections import diagnostics
            value = diagnostics(config, args.platform, probe=args.probe)
            print(json.dumps(value, ensure_ascii=False, indent=2))
            return int(value["configuration"] != "ready" or (args.probe and value["connection"] != "passed"))
        if args.command == "gateway":
            from .native import interactive
            return interactive(config, platforms=args.platform)
        if args.command == "restore":
            from .backup import restore_state
            print(json.dumps(restore_state(config, args.source, args.destination), ensure_ascii=False, indent=2))
            return 0
        if args.command == "doctor":
            value = doctor(config, probe_model=args.probe_model, selected_model=args.model)
            print(json.dumps(value, ensure_ascii=False, indent=2))
            return int(args.probe_model and value["model"]["connection"] != "passed")
        else:
            if args.command == "chat" and args.message is None:
                from .native import interactive
                return interactive(config, args.session)
            service = Service(config)
            actor = config.owner
            cmd = args.command
            if cmd == "chat":
                from .chat import Chat
                with Chat(config) as chat:
                    session = chat.get(args.session, actor) if args.session else chat.create(actor)
                    value = chat.send(session["id"], actor, args.message, uuid.uuid4().hex)
                    print(json.dumps(value, ensure_ascii=False, indent=2))
                    return 0
            if cmd == "serve":
                from .server import make_server
                server = make_server(service)
                def stop_api(signum, frame):
                    raise SystemExit(0)
                previous_handler = signal.signal(signal.SIGTERM, stop_api)
                try:
                    server.serve_forever()
                finally:
                    server.server_close()
                    signal.signal(signal.SIGTERM, previous_handler)
                return 0
            if cmd == "run":
                stopping = False

                def stop(signum, frame):
                    nonlocal stopping
                    stopping = True

                signal.signal(signal.SIGTERM, stop)
                while True:
                    value = service.run_once()
                    if args.once or stopping:
                        break
                    time.sleep(1)
            elif cmd == "submit":
                payload = {"kind": args.kind, "repo": args.repo, "title": args.title,
                           "acceptance": args.acceptance, "depends_on": args.depends_on}
                if args.pr is not None:
                    payload["pr"] = args.pr
                if args.assignee:
                    payload["assignee"] = args.assignee
                value = service.submit(payload, actor, args.key or uuid.uuid4().hex)
            elif cmd == "list":
                value = service.tasks.list()
            elif cmd == "show":
                value = service.tasks.get(args.task)
            elif cmd == "events":
                value = service.tasks.events(args.task)
            elif cmd in {"cancel", "retry", "assign", "complete"}:
                value = service.action(args.task, cmd, actor, {k: getattr(args, k) for k in ("assignee", "evidence") if hasattr(args, k)})
            elif cmd in {"expand", "publish"}:
                value = getattr(service, cmd)(args.task, actor)
            elif cmd in {"pause", "resume"}:
                service.store.pause(cmd == "pause", actor)
                value = {"paused": service.store.paused()}
            elif cmd == "resolve-publication":
                value = service.resolve_publication(args.task, args.external_id, actor)
            elif cmd == "backup":
                from .backup import backup_state
                value = backup_state(service, args.destination)
        print(json.dumps(value, ensure_ascii=False, indent=2))
        return 0
    except MikasaError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
