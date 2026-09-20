import json
import urllib.error
import urllib.request

from .errors import MikasaError, Forbidden


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class GitHub:
    def __init__(self, config):
        self.config = config
        self.opener = urllib.request.build_opener(NoRedirect)

    def request(self, method, path, body=None):
        token = self.config.secret("github", "token_env", "MIKASA_GITHUB_TOKEN")
        req = urllib.request.Request("https://api.github.com" + path, method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                                              "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json",
                                              "User-Agent": "mikasa/0.1"})
        try:
            with self.opener.open(req, timeout=30) as response:
                raw = response.read(5_000_001)
                if len(raw) > 5_000_000:
                    raise MikasaError("GitHub 响应超出限制")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            raise MikasaError(f"GitHub HTTP {exc.code}；检查权限、限额和请求状态") from exc
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            raise MikasaError("GitHub 响应不可用；写入请求可能已经送达，需核对后再试") from exc

    def paginate(self, path, field=None):
        output = []
        for page in range(1, 21):
            result = self.request("GET", path + ("&" if "?" in path else "?") + f"per_page=100&page={page}")
            rows = result[field] if field else result
            if not isinstance(rows, list):
                raise MikasaError("GitHub 列表响应结构不正确")
            output.extend(rows)
            if len(rows) < 100:
                return output
        raise MikasaError("GitHub 列表超过 2000 项；拒绝将截断数据当作完整审计")

    def pr(self, repo, number):
        self.config.repo(repo)
        return self.request("GET", f"/repos/{repo}/pulls/{number}")

    def checks(self, repo, sha):
        checks = self.paginate(f"/repos/{repo}/commits/{sha}/check-runs", "check_runs")
        statuses = self.paginate(f"/repos/{repo}/commits/{sha}/statuses")
        latest = {}
        for status in statuses:  # GitHub returns newest status first.
            if status["context"] != "mikasa/approval":
                latest.setdefault(status["context"], status)
        ok = bool(checks or latest) and all(
            c.get("status") == "completed" and c.get("conclusion") in {"success", "neutral", "skipped"} for c in checks)
        if any(s["state"] != "success" for s in latest.values()):
            ok = False
        return {"passed": ok, "checks": [{"name": c["name"], "status": c["status"], "conclusion": c.get("conclusion"), "url": c.get("html_url")} for c in checks],
                "statuses": [{"context": s["context"], "state": s["state"], "url": s.get("target_url")} for s in latest.values()], "head": sha}

    def audit(self, repo):
        self.config.repo(repo)
        issues = self.paginate(f"/repos/{repo}/issues?state=open")
        pulls = self.paginate(f"/repos/{repo}/pulls?state=open")
        risks = []
        prs = []
        for pr in pulls:
            ci = self.checks(repo, pr["head"]["sha"])
            prs.append({"number": pr["number"], "title": pr["title"], "head": pr["head"]["sha"], "url": pr["html_url"], "ci": ci})
            if not ci["passed"]:
                risks.append({"key": f"ci:{pr['number']}:{pr['head']['sha']}", "fact": "CI 尚未提供完整通过证据", "url": pr["html_url"]})
        return {"summary": f"读取 {len(pulls)} 个开放 PR 和 {sum('pull_request' not in i for i in issues)} 个开放 Issue",
                "issues": [{"number": i["number"], "title": i["title"], "url": i["html_url"], "assignees": [a["login"] for a in i.get("assignees", [])]} for i in issues if "pull_request" not in i],
                "pull_requests": prs, "risks": risks}

    def verify_publisher(self):
        if self.config.data.get("github", {}).get("publish_enabled") is not True:
            raise Forbidden("外部发布未启用；结果已保留为本地草稿")
        if self.request("GET", "/user").get("login", "").lower() != self.config.bot.lower():
            raise Forbidden("发布 token 必须属于 Mikasa-0910")

    def review(self, repo, number, sha, verdict, body):
        return self.request("POST", f"/repos/{repo}/pulls/{number}/reviews", {
            "commit_id": sha, "event": {"APPROVED": "APPROVE", "CHANGES_REQUESTED": "REQUEST_CHANGES", "INCOMPLETE": "COMMENT"}[verdict], "body": body})

    def gate(self, repo, number, store):
        pr = self.pr(repo, number)
        head = pr["head"]["sha"]
        provenance = store.get_provenance(repo, number, head)
        author = pr["user"]["login"]
        if author.lower() == self.config.bot.lower():
            provenance = "mikasa"
        expected = self.config.owner if provenance == "mikasa" else self.config.bot
        reasons = []
        if provenance == "unknown":
            reasons.append("当前 head 的产出归属未确认")
        if author.lower() == expected.lower():
            reasons.append("指定审批人与 PR 作者相同")
        latest = {}
        for review in self.paginate(f"/repos/{repo}/pulls/{number}/reviews"):
            if review["state"] in {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"}:
                latest[review["user"]["login"].lower()] = review
        review = latest.get(expected.lower(), {})
        if review.get("state") != "APPROVED" or review.get("commit_id") != head:
            reasons.append("指定审批人尚未批准当前 head")
        ci = self.checks(repo, head)
        if not ci["passed"]:
            reasons.append("CI 未确认通过")
        if pr["state"] != "open" or pr.get("draft"):
            reasons.append("PR 未开放或仍为草稿")
        if self.pr(repo, number)["head"]["sha"] != head:
            reasons.append("检查期间 head 变化")
        return {"allowed": not reasons, "head": head, "provenance": provenance, "required_reviewer": expected,
                "reasons": reasons, "ci": ci, "note": "此结果不自动配置 GitHub 分支保护，也不执行合并"}

    def publish_gate(self, repo, number, store):
        self.verify_publisher()
        result = self.gate(repo, number, store)
        if self.pr(repo, number)["head"]["sha"] != result["head"]:
            raise MikasaError("发布门禁前 head 变化；需要重新检查")
        self.request("POST", f"/repos/{repo}/statuses/{result['head']}", {
            "state": "success" if result["allowed"] else "failure", "context": "mikasa/approval",
            "description": "Current-head independent approval and CI verified" if result["allowed"] else "Independent approval or CI evidence missing"})
        return result
