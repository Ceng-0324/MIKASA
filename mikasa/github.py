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
            exc.close()
            raise MikasaError(f"GitHub HTTP {exc.code}；检查权限、限额和请求状态") from None
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            raise MikasaError("GitHub 响应不可用；写入请求可能已经送达，需核对后再试") from exc

    def probe(self):
        """Read-only access evidence, never infer token write scopes from repo roles."""
        from urllib.parse import quote
        identity = self.request("GET", "/user")
        if not isinstance(identity, dict) or str(identity.get("login", "")).lower() != self.config.bot.lower():
            raise Forbidden("GitHub token 必须属于 Mikasa-0910；仓库检查未执行")
        repositories = []
        for name, settings in self.config.data.get("repositories", {}).items():
            row = {"repo": name, "read_access": "failed", "write_access": "not_checked"}
            try:
                repo = self.request("GET", f"/repos/{name}")
                if not isinstance(repo, dict) or str(repo.get("full_name", "")).lower() != name.lower():
                    raise MikasaError("GitHub 仓库响应身份不匹配")
                self.request("GET", f"/repos/{name}/branches/{quote(settings['base'], safe='')}")
                for endpoint in ("issues", "pulls"):
                    if not isinstance(self.request("GET", f"/repos/{name}/{endpoint}?state=open&per_page=1"), list):
                        raise MikasaError("GitHub 列表响应结构不正确")
                permissions = repo.get("permissions", {})
                row.update(read_access="passed", private=repo.get("private"),
                           account_push_role=permissions.get("push") if isinstance(permissions, dict) else None)
            except MikasaError as exc:
                row["error"] = str(exc)
            repositories.append(row)
        accessible = all(r["read_access"] == "passed" for r in repositories)
        return {"connection": "passed" if accessible else "incomplete",
                "identity": "passed", "account": self.config.bot, "repositories": repositories,
                "repository_access": ("passed" if accessible else "incomplete") if repositories else "not_checked",
                "write_access": "not_checked", "webhook": "not_checked"}

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
