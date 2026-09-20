import argparse
import json
import os
import shutil
import signal
import sys
import time
import uuid
from pathlib import Path

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
    chat = commands.add_parser("chat", help="与 Mikasa 聊天，支持：切换为 完整模型ID")
    chat.add_argument("--session", help="继续已有聊天 ID")
    chat.add_argument("--message", help="发送单条消息并输出 JSON；省略则交互聊天")
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
    reconcile = commands.add_parser("reconcile")
    reconcile.add_argument("task")
    reconcile.add_argument("pr", type=int)
    resolve = commands.add_parser("resolve-publication")
    resolve.add_argument("task")
    resolve.add_argument("external_id", type=int)
    commands.add_parser("pause")
    commands.add_parser("resume")
    provenance = commands.add_parser("provenance")
    provenance.add_argument("repo")
    provenance.add_argument("pr", type=int)
    provenance.add_argument("head")
    provenance.add_argument("value", choices=["human", "mikasa"])
    gate = commands.add_parser("gate")
    gate.add_argument("repo")
    gate.add_argument("pr", type=int)
    gate.add_argument("--publish", action="store_true", help="显式发布 mikasa/approval commit status；需启用发布")
    backup = commands.add_parser("backup")
    backup.add_argument("destination")
    return p


def doctor(config, *, probe_model=False, selected_model=None):
    from .skills import skill_inventory
    from .model_settings import model_diagnostics
    from .model_errors import ModelFailure
    from .worker import Worker
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
            "rules": "loaded", "skills": skill_inventory(config.root), "repositories": list(config.data.get("repositories", {})),
            "worker_configured": bool(command), "worker_executable": bool(command and shutil.which(command[0])),
            "github_token_present": bool(os.environ.get(config.data.get("github", {}).get("token_env", "MIKASA_GITHUB_TOKEN"))),
            "publishing_enabled": config.data.get("github", {}).get("publish_enabled", False), "model": model,
            "note": "默认仅检查本地前提；模型探针不证明 CCH 分组、GitHub 权限或 VM 已完成联调"}


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        config = Config.load(args.config)
        if args.command == "doctor":
            value = doctor(config, probe_model=args.probe_model, selected_model=args.model)
            print(json.dumps(value, ensure_ascii=False, indent=2))
            return int(args.probe_model and value["model"]["connection"] != "passed")
        else:
            service = Service(config)
            actor = config.owner
            cmd = args.command
            if cmd == "chat":
                from .chat import Chat
                with Chat(config) as chat:
                    session = chat.get(args.session, actor) if args.session else chat.create(actor)
                    if args.message is not None:
                        value = chat.send(session["id"], actor, args.message, uuid.uuid4().hex)
                        print(json.dumps(value, ensure_ascii=False, indent=2))
                        return 0
                    print(f"Mikasa · 会话 {session['id']} · 请求模型 {session['model']}\n输入 /model 查看候选，/model 完整模型ID 切换，/new 新聊天，/help 帮助，/exit 退出。")
                    while True:
                        try:
                            message = input("你：").strip()
                        except EOFError:
                            return 0
                        if message == "/exit":
                            return 0
                        if not message:
                            continue
                        try:
                            result = chat.send(session["id"], actor, message, uuid.uuid4().hex)
                            session.update(id=result["chat_id"], model=result["model"])
                            print("Mikasa：" + result["reply"])
                        except MikasaError as exc:
                            print(str(exc), file=sys.stderr)
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
                value = service.store.list()
            elif cmd == "show":
                value = service.store.get(args.task)
            elif cmd == "events":
                value = service.store.events(args.task)
            elif cmd in {"cancel", "retry", "assign", "complete"}:
                value = service.action(args.task, cmd, actor, {k: getattr(args, k) for k in ("assignee", "evidence") if hasattr(args, k)})
            elif cmd in {"expand", "publish"}:
                value = getattr(service, cmd)(args.task, actor)
            elif cmd in {"pause", "resume"}:
                service.store.pause(cmd == "pause", actor)
                value = {"paused": service.store.paused()}
            elif cmd == "provenance":
                value = service.record_provenance(args.repo, args.pr, args.head, args.value, actor)
            elif cmd == "gate":
                if args.publish and service.store.paused():
                    raise MikasaError("运行已暂停，不能发布门禁状态")
                value = (service.github.publish_gate if args.publish else service.github.gate)(args.repo, args.pr, service.store)
            elif cmd == "reconcile":
                value = service.reconcile(args.task, args.pr, actor)
            elif cmd == "resolve-publication":
                value = service.resolve_publication(args.task, args.external_id, actor)
            elif cmd == "backup":
                import sqlite3
                target = Path(args.destination).resolve()
                if target.exists():
                    raise MikasaError("备份目标已存在，拒绝覆盖")
                target.parent.mkdir(parents=True, exist_ok=True)
                with service.store.connect() as source, sqlite3.connect(target) as destination:
                    source.backup(destination)
                target.chmod(0o600)
                value = {"backup": str(target)}
        print(json.dumps(value, ensure_ascii=False, indent=2))
        return 0
    except MikasaError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
