import fnmatch
from pathlib import Path, PurePosixPath

from .errors import MikasaError
from .process import git

SECRET_NAMES = {"auth.json", ".env", "credentials", "credentials.json", "id_rsa", "id_ed25519"}
SECRET_PATTERNS = ("*.pem", "*.key", "*.p12", "*.secret.*", "*.secrets.*", "*.local.*")
PROTECTED = {".git", ".github", ".agents", ".codex", ".claude"}
RULES = {"AGENTS.md", "CLAUDE.md", "identity.md", "engineering-contract.md", "engineering-workflow.md"}


def sensitive(path):
    return any(part in SECRET_NAMES or part.startswith(".env.") or
               any(fnmatch.fnmatch(part, pattern) for pattern in SECRET_PATTERNS)
               for part in PurePosixPath(path).parts)


class Workspace:
    def __init__(self, config, task, attempt):
        self.config = config
        self.task = task
        self.path = config.runtime / "workspaces" / task["id"] / attempt
        self.spec = config.repo(task["payload"]["repo"])

    def prepare(self, pr=None):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        source = self.spec.get("source", f"https://github.com/{self.task['payload']['repo']}.git")
        git(["clone", "--no-local", "--single-branch", "--branch", self.spec["base"], "--", source, str(self.path)], self.path.parent)
        self.base = git(["rev-parse", "HEAD"], self.path)
        self.head = self.base
        if pr:
            if pr["base"]["ref"] != self.spec["base"] or pr["base"]["sha"] != self.base:
                raise MikasaError("PR 目标分支或基线已变化；重新获取上下文后重试")
            number = self.task["payload"]["pr"]
            git(["fetch", "origin", f"refs/pull/{number}/head"], self.path)
            self.head = git(["rev-parse", "FETCH_HEAD"], self.path)
            if self.head != pr["head"]["sha"]:
                raise MikasaError("PR head 在获取期间发生变化")
        return self

    def context(self):
        cap = self.config.data.get("worker", {}).get("max_context_bytes", 200000)
        names = git(["ls-tree", "-r", "--name-only", self.head], self.path).splitlines()
        changed = set(git(["diff", "--name-only", self.base, self.head, "--"], self.path).splitlines()) if self.head != self.base else set()
        names.sort(key=lambda p: (Path(p).name not in RULES, p not in changed, Path(p).name.lower() != "readme.md", p))
        files, omitted, used = {}, [], 0
        for name in names:
            if sensitive(name) or name.startswith(".git/"):
                omitted.append(name)
                continue
            size = int(git(["cat-file", "-s", f"{self.head}:{name}"], self.path))
            if size > min(cap - used, 60000):
                omitted.append(name)
                continue
            content = git(["show", f"{self.head}:{name}"], self.path)
            if "\x00" in content:
                omitted.append(name)
                continue
            files[name] = content
            used += len(content.encode())
        baseline_rules = {}
        for name in names:
            if Path(name).name in RULES:
                try:
                    baseline_rules[name] = git(["show", f"{self.base}:{name}"], self.path)
                except MikasaError:
                    pass
        diff = git(["diff", "--no-ext-diff", self.base, self.head, "--"], self.path) if self.head != self.base else ""
        return {"base": self.base, "head": self.head, "files": files, "omitted": omitted,
                "omitted_changed": sorted(changed.intersection(omitted)), "baseline_rules": baseline_rules, "diff": diff}

    def apply(self, changes, cancelled=None):
        if not isinstance(changes, list) or not 1 <= len(changes) <= 100:
            raise MikasaError("实现结果需包含 1–100 项 changes")
        seen = set()
        total = 0
        validated = []
        for item in changes:
            if not isinstance(item, dict) or set(item) != {"path", "content"}:
                raise MikasaError("change 仅允许 path 和 content")
            name, content = item["path"], item["content"]
            if not isinstance(name, str) or not name or "\\" in name or "\x00" in name:
                raise MikasaError("非法文件路径")
            parts = PurePosixPath(name).parts
            if (str(PurePosixPath(name)) != name or name.startswith("/") or any(p in {"..", "."} for p in parts) or
                    any(p in PROTECTED for p in parts) or Path(name).name in RULES or sensitive(name)):
                raise MikasaError("拒绝修改越界、凭据、规则或执行配置文件")
            target = self.path / name
            ancestors = [self.path.joinpath(*parts[:i]) for i in range(1, len(parts) + 1)]
            if not target.resolve().is_relative_to(self.path.resolve()) or any(p.is_symlink() for p in ancestors):
                raise MikasaError("拒绝符号链接路径")
            if name in seen or (content is not None and not isinstance(content, str)):
                raise MikasaError("重复路径或 content 类型错误")
            seen.add(name)
            total += len((content or "").encode())
            if total > 1_000_000:
                raise MikasaError("变更超出大小限制")
            if target.exists() and not target.is_file():
                raise MikasaError("变更目标不是文件")
            validated.append((target, content))
        if cancelled and cancelled():
            raise MikasaError("任务已取消或运行已暂停")
        for target, content in validated:
            if content is None:
                if target.exists():
                    target.unlink()
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content)
        git(["add", "--all", "--", *sorted(seen)], self.path, cancelled=cancelled)
        git(["diff", "--cached", "--check"], self.path, cancelled=cancelled)
        if not git(["diff", "--cached", "--stat"], self.path, cancelled=cancelled):
            raise MikasaError("执行者未产生实际变更")

    def commit(self):
        git(["-c", "user.name=Mikasa", "-c", "user.email=Mikasa-0910@users.noreply.github.com",
             "commit", "-m", f"Mikasa task {self.task['id']}"], self.path)
        return git(["rev-parse", "HEAD"], self.path)
