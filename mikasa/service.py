import base64
import fcntl
import json
import re
import time
from pathlib import Path

from .config import KINDS
from .errors import Conflict, Forbidden, MikasaError
from .github import GitHub
from .process import clean_env, git
from .store import Store
from .worker import Worker
from .workspace import Workspace
from .agent_tools import run_checks


class Service:
    def __init__(self, config, github=None, worker=None):
        self.config = config
        self.store = Store(config.runtime)
        self.github = github or GitHub(config)
        self.worker = worker or Worker(config)

    def submit(self, data, actor, key):
        self.config.authorize(actor)
        if not isinstance(data, dict) or set(data) - {"kind", "repo", "title", "acceptance", "depends_on", "pr", "assignee"}:
            raise MikasaError("任务字段不正确")
        payload = dict(data)
        if payload.get("kind") not in KINDS:
            raise MikasaError("不支持的任务类型")
        self.config.repo(payload.get("repo"))
        for field in ("title", "acceptance"):
            if not isinstance(payload.get(field), str) or not 1 <= len(payload[field].strip()) <= 10000:
                raise MikasaError(f"任务需要 1–10000 字符的 {field}")
        deps = payload.get("depends_on", [])
        if not isinstance(deps, list) or len(deps) > 50 or any(not isinstance(d, str) for d in deps):
            raise MikasaError("depends_on 必须为任务 ID 数组")
        if payload["kind"] == "review" and (type(payload.get("pr")) is not int or payload["pr"] < 1):
            raise MikasaError("review 需要正整数 pr")
        assignee = payload.pop("assignee", self.config.bot)
        if assignee not in {self.config.bot, self.config.owner, *self.config.data.get("members", [])}:
            raise MikasaError("执行者未配置")
        if actor != self.config.owner and (assignee != self.config.bot or payload["kind"] == "implement"):
            raise Forbidden("成员可提交分析需求；实现和任务派发需负责人授权")
        return self.store.create(payload, actor, assignee, key)

    def action(self, task_id, action, actor, data=None):
        self.config.authorize(actor, owner=True)
        data = data or {}
        fields = {"assign": {"assignee"}, "complete": {"evidence"}, "cancel": set(), "retry": set()}
        if action not in fields or set(data) - fields[action]:
            raise MikasaError("任务操作包含不支持的字段")
        if action == "assign":
            if data.get("assignee") not in {self.config.bot, self.config.owner, *self.config.data.get("members", [])}:
                raise MikasaError("执行者未配置")
        if action == "complete":
            task = self.store.get(task_id)
            if task["payload"]["kind"] == "implement" and task["assignee"] == self.config.bot:
                raise Conflict("Mikasa 实现任务必须由 reconcile 验证 PR 审批与合并，不能手动标记完成")
            if not isinstance(data.get("evidence"), str) or not data["evidence"].strip():
                raise MikasaError("完成任务必须记录证据")
        return self.store.transition(task_id, action, actor, assignee=data.get("assignee"), evidence=data.get("evidence"))

    def expand(self, task_id, actor):
        self.config.authorize(actor, owner=True)
        task = self.store.get(task_id)
        if task["state"] != "done" or task["payload"]["kind"] != "plan":
            raise Conflict("只有已完成的拆解任务可以转成实施任务")
        children = []
        for i, item in enumerate(task["result"]["tasks"]):
            children.append(self.submit({"kind": "implement", "repo": task["payload"]["repo"], "title": item["title"],
                                         "acceptance": item["acceptance"], "depends_on": [children[d]["id"] for d in item.get("depends_on", [])]},
                                        actor, f"plan:{task_id}:{i}"))
        return children

    def run_once(self):
        lock_path = self.config.runtime / "runner.lock"
        with lock_path.open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise Conflict("已有任务执行进程运行") from exc
            self.store.recover("runtime")
            self.schedule()
            claimed = self.store.claim(self.config.bot)
            if not claimed:
                return None
            task, token = claimed
            try:
                result, state = self.execute(task, token)
                self.store.finish(task["id"], token, state, result)
            except Exception as exc:
                error = str(exc) if isinstance(exc, MikasaError) else f"内部错误 {type(exc).__name__}；保留工作区供诊断"
                try:
                    self.store.finish(task["id"], token, "failed", error=error)
                except Conflict:
                    pass
            return self.store.get(task["id"])

    def schedule(self):
        interval = self.config.data.get("schedules", {}).get("audit_interval_seconds", 0)
        if not interval or self.store.paused():
            return
        slot = int(time.time() // interval)
        active = {t["payload"]["repo"] for t in self.store.list()
                  if t["payload"]["kind"] == "audit" and t["state"] in {"queued", "running"}}
        for repo in self.config.data["repositories"]:
            if repo not in active:
                self.submit({"kind": "audit", "repo": repo, "title": "定期仓库审计",
                             "acceptance": "记录当前 Issue、PR、CI 与可定位的交付风险"},
                            self.config.owner, f"audit:{repo}:{slot}")

    def execute(self, task, token):
        payload = task["payload"]
        repo, kind = payload["repo"], payload["kind"]
        if kind == "audit":
            return self.github.audit(repo), "done"
        if kind == "followup":
            tasks = [t for t in self.store.list() if t["payload"]["repo"] == repo and t["id"] != task["id"]]
            return {"summary": f"当前记录 {len(tasks)} 个任务", "tasks": [
                {"id": t["id"], "title": t["payload"]["title"], "assignee": t["assignee"], "state": t["state"],
                 "blocker": t["error"], "depends_on": t["payload"].get("depends_on", []),
                 "updated": t["updated"], "result": t["result"]} for t in tasks]}, "done"
        pr = self.github.pr(repo, payload["pr"]) if kind == "review" else None
        workspace = Workspace(self.config, task, token).prepare(pr)
        context = workspace.context()
        cancelled = lambda: self.store.paused() or self.store.get(task["id"])["state"] != "running"
        if pr:
            context["pr"] = {"number": payload["pr"], "title": pr["title"], "body": pr.get("body"), "author": pr["user"]["login"]}
            context["ci"] = self.github.checks(repo, workspace.head)
            context["provenance"] = self.store.get_provenance(repo, payload["pr"], workspace.head)
            if pr["user"]["login"].lower() == self.config.bot.lower():
                context["provenance"] = "mikasa"
        result = self.worker.execute(task, context, cancelled, workspace=workspace)
        if getattr(self.worker, "last_runtime", None):
            result["execution"] = self.worker.last_runtime
        result.update({"head": workspace.head, "base": workspace.base, "workspace": str(workspace.path), "observed_at": time.time()})
        if cancelled():
            raise MikasaError("任务已暂停或取消")
        if kind == "plan":
            return result, "done"
        if kind == "review":
            current = self.github.pr(repo, payload["pr"])
            result["ci"] = context["ci"]
            result["provenance"] = context["provenance"]
            if context["provenance"] != "human":
                result["verdict"] = "INCOMPLETE"
                result["limitations"].append("自作产出仅提供自检；未知产出归属需要负责人确认")
            read_paths = {event["path"] for event in result.get("execution", {}).get("tool_events", [])
                          if event.get("tool") == "mikasa_read_file" and event.get("ok") and event.get("complete") is True
                          and event.get("revision") == workspace.head}
            unread = set(context["omitted"]) - read_paths
            if unread:
                result["limitations"].append("仓库上下文仍省略文件：" + ", ".join(sorted(unread)))
            if set(context["omitted_changed"]) - read_paths or not context["ci"]["passed"]:
                if result["verdict"] == "APPROVED":
                    result["verdict"] = "INCOMPLETE"
                result["limitations"].append("存在未读取的变更文件或 CI 尚未提供通过证据")
            if current["head"]["sha"] != workspace.head or current["base"]["sha"] != workspace.base:
                raise MikasaError("审查期间 PR head 或目标分支发生变化")
            return result, "done"
        return self.implement(task, workspace, context, result, cancelled)

    def implement(self, task, workspace, context, result, cancelled):
        repo = task["payload"]["repo"]
        checks = self.config.repo(repo).get("checks", [])
        attempts = self.config.data.get("worker", {}).get("max_attempts", 3)
        history = []
        for attempt in range(attempts):
            changes = result.pop("changes", None)
            if changes != []:
                workspace.apply(changes, cancelled=cancelled)
            elif not git(["diff", "--cached", "--stat"], workspace.path):
                raise MikasaError("执行者未产生实际变更")
            if not checks:
                result["summary"] += "；未配置验证命令，变更保留为未验证草稿"
                return result, "blocked"
            evidence = run_checks(workspace, cancelled)
            history.append({"attempt": attempt + 1, "checks": evidence, "execution": result.get("execution")})
            if all(check["code"] == 0 for check in evidence):
                break
            if attempt + 1 == attempts:
                result["checks"] = evidence
                result["attempts"] = history
                return result, "blocked"
            context["repair"] = {"attempt": attempt + 2, "checks": evidence,
                                 "current_diff": git(["diff", "--no-ext-diff", "HEAD", "--"], workspace.path)}
            updated = self.worker.execute(task, context, cancelled, workspace=workspace)
            result.update({"summary": updated["summary"], "changes": updated["changes"]})
            if getattr(self.worker, "last_runtime", None):
                result["execution"] = self.worker.last_runtime
        # Tests may mutate tracked files. Require validation and committed content to match.
        if git(["diff", "--name-only"], workspace.path):
            raise MikasaError("验证命令修改了已暂存内容；拒绝提交未经验证的版本")
        result["checks"] = evidence
        result["attempts"] = history
        if cancelled():
            raise MikasaError("任务已暂停或取消")
        result["head"] = workspace.commit()
        result["branch"] = f"mikasa/task-{task['id']}"
        result["provenance"] = "mikasa"
        return result, "awaiting_review"

    def publish(self, task_id, actor):
        self.config.authorize(actor, owner=True)
        if self.store.paused():
            raise Conflict("运行已暂停")
        task = self.store.get(task_id)
        payload, result = task["payload"], task["result"]
        kind, repo = payload["kind"], payload["repo"]
        if not result or kind not in {"plan", "implement", "review"}:
            raise Conflict("该任务没有可发布的结果")
        if (kind == "implement" and task["state"] != "awaiting_review") or (kind != "implement" and task["state"] != "done"):
            raise Conflict("任务尚未到发布阶段")
        self.github.verify_publisher()
        if kind == "review":
            current = self.github.pr(repo, payload["pr"])
            if current["head"]["sha"] != result["head"] or current["base"]["sha"] != result["base"]:
                raise Conflict("PR 已变化，必须重新审查")
            provenance = self.store.get_provenance(repo, payload["pr"], result["head"])
            if result["verdict"] != "INCOMPLETE" and (provenance != "human" or current["user"]["login"].lower() == self.config.bot.lower()):
                raise Forbidden("禁止对自作或归属未知的产出发出审查决定")
            if result["verdict"] == "APPROVED" and not self.github.checks(repo, result["head"])["passed"]:
                raise Conflict("CI 状态已变化，不能发布批准")
        self.store.reserve_publication(task_id)
        try:
            marker = f"<!-- mikasa-task:{task_id} -->"
            if kind == "review":
                body = self.review_body(result) + "\n\n" + marker
                published = self.github.review(repo, payload["pr"], result["head"], result["verdict"], body)
            elif kind == "plan":
                # One issue preserves idempotency and contains the full proposed breakdown.
                body = result["summary"] + "\n\n" + "\n".join(
                    f"- [ ] {i + 1}. {t['title']}\n  验收：{t['acceptance']}；依赖：{t.get('depends_on', [])}" for i, t in enumerate(result["tasks"]))
                published = self.github.request("POST", f"/repos/{repo}/issues", {"title": payload["title"], "body": body + "\n\n" + marker})
            else:
                path = Path(result["workspace"])
                if not path.resolve().is_relative_to((self.config.runtime / "workspaces").resolve()):
                    raise Conflict("工作区越界")
                if git(["rev-parse", "HEAD"], path) != result["head"] or git(["status", "--porcelain"], path):
                    raise Conflict("工作区已变化；不能发布旧验证结果")
                token = self.config.secret("github", "token_env", "MIKASA_GITHUB_TOKEN")
                auth = base64.b64encode(f"x-access-token:{token}".encode()).decode()
                env = clean_env({"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader", "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {auth}"})
                git(["push", f"https://github.com/{repo}.git", f"{result['head']}:refs/heads/{result['branch']}"], path, env=env)
                published = self.github.request("POST", f"/repos/{repo}/pulls", {"title": payload["title"], "head": result["branch"],
                    "base": self.config.repo(repo)["base"], "draft": True,
                    "body": result["summary"] + "\n\n自检说明，等待 Ceng-0324 审批。\n\n验证：\n```json\n" + json.dumps(result["checks"], ensure_ascii=False) + "\n```\n\n" + marker})
                self.store.provenance(repo, published["number"], result["head"], "mikasa", actor)
            receipt = {k: published[k] for k in ("id", "number", "html_url") if k in published}
            self.store.publication(task_id, "sent", receipt)
            return receipt
        except Exception:
            self.store.publication(task_id, "uncertain", {"note": "可能已发生外部写入；人工核对后处理，不自动重发"})
            raise

    def resolve_publication(self, task_id, external_id, actor):
        self.config.authorize(actor, owner=True)
        task = self.store.get(task_id)
        payload = task["payload"]
        kind, repo = payload["kind"], payload["repo"]
        if type(external_id) is not int or external_id < 1:
            raise MikasaError("外部记录 ID 必须为正整数")
        with self.store.connect() as db:
            record = db.execute("SELECT state FROM publications WHERE task_id=?", (task_id,)).fetchone()
        if not record or record[0] not in {"pending", "uncertain"}:
            raise Conflict("任务没有待核对的发布")
        path = {"plan": f"/issues/{external_id}", "implement": f"/pulls/{external_id}",
                "review": f"/pulls/{payload.get('pr')}/reviews/{external_id}"}.get(kind)
        if not path:
            raise Conflict("不支持该任务发布类型")
        record = self.github.request("GET", f"/repos/{repo}" + path)
        if record.get("user", {}).get("login", "").lower() != self.config.bot.lower() or f"<!-- mikasa-task:{task_id} -->" not in (record.get("body") or ""):
            raise Conflict("外部记录作者或任务标记不匹配")
        if kind == "implement":
            if record["head"]["sha"] != task["result"]["head"]:
                raise Conflict("PR 产出版本不匹配")
            self.store.provenance(repo, external_id, task["result"]["head"], "mikasa", actor)
        if kind == "review" and record.get("commit_id") != task["result"]["head"]:
            raise Conflict("Review 版本不匹配")
        receipt = {k: record[k] for k in ("id", "number", "html_url") if k in record}
        self.store.publication(task_id, "sent", receipt)
        return receipt

    @staticmethod
    def review_body(result):
        return "\n\n".join((f"结论：{result['verdict']}\n{result['summary']}", f"审查版本：{result['head']}；目标版本：{result['base']}",
                            "依据：\n" + "\n".join(result["basis"]), "发现：\n" + "\n".join(result["findings"]),
                            "验证：\n```json\n" + json.dumps(result["ci"], ensure_ascii=False) + "\n```",
                            "限制：\n" + "\n".join(result["limitations"])))

    def record_provenance(self, repo, number, head, value, actor):
        self.config.authorize(actor, owner=True)
        self.config.repo(repo)
        if not re.fullmatch(r"[0-9a-f]{40}", head):
            raise MikasaError("head 必须为完整 SHA")
        pr = self.github.pr(repo, number)
        if pr["head"]["sha"] != head:
            raise Conflict("PR head 已变化")
        if value == "human" and pr["user"]["login"].lower() == self.config.bot.lower():
            raise Forbidden("Mikasa 创建的 PR 不得标为人类产出")
        self.store.provenance(repo, number, head, value, actor)
        return {"repo": repo, "pr": number, "head": head, "provenance": value}

    def reconcile(self, task_id, number, actor):
        self.config.authorize(actor, owner=True)
        task = self.store.get(task_id)
        if task["state"] != "awaiting_review" or task["payload"]["kind"] != "implement":
            raise Conflict("任务未处于实现待审阶段")
        repo, head = task["payload"]["repo"], task["result"]["head"]
        pr = self.github.pr(repo, number)
        if pr["head"]["sha"] != head or pr["user"]["login"].lower() != self.config.bot.lower():
            raise Conflict("PR 与本任务产出不匹配")
        reviews = self.github.paginate(f"/repos/{repo}/pulls/{number}/reviews")
        decisions = [r for r in reviews if r["user"]["login"].lower() == self.config.owner.lower() and r["state"] in {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"}]
        if not decisions or decisions[-1]["state"] != "APPROVED" or decisions[-1]["commit_id"] != head:
            raise Conflict("负责人尚未批准当前产出")
        if not pr.get("merged") or not self.github.checks(repo, head)["passed"]:
            raise Conflict("PR 尚未合并或 CI 未通过")
        return self.store.transition(task_id, "complete", actor, evidence=pr["html_url"])
