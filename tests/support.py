import json
import sys
import tempfile
import unittest
from pathlib import Path

from mikasa.config import Config
from mikasa.process import git
from mikasa.service import Service

ROOT = Path(__file__).resolve().parents[1]
REPO = "Ceng-0324/TestFixture"
SHA = "a" * 40


def command_reply(text, cancelled=lambda: False):
    """Canned command RPC replies; real upstream semantics use probe_commands.py."""
    from mikasa.chat import HELP
    replies = {"/model": ("model", "status", None), "/model default": ("model", "reset", None),
               "/new": ("new", "new", None), "/reset": ("new", "new", None),
               "/init": ("init", "deferred_command", None), "/help": ("help", "help", None),
               "/version": ("version", "version", None)}
    for model in ("model-b", "model-c", "nonexistent", "claude-test"):
        replies["/model " + model] = ("model", "switch", model)
    name, kind, target = replies.get(text, (None, "unsupported_command", None))
    return {"name": name, "kind": kind, "target": target,
            "reply": HELP if kind == "help" else "fixture" if kind in {"version", "deferred_command"} else None}


class FakeGitHub:
    def __init__(self):
        self.current = {"number": 1, "title": "Test PR", "body": "Test", "user": {"login": "human"},
                        "head": {"sha": SHA}, "base": {"sha": "b" * 40, "ref": "main"},
                        "state": "open", "draft": False, "merged": False, "html_url": "https://github.com/example/pull/1"}
        self.passed = True
        self.writes = []
        self.reviews = []

    def pr(self, repo, number):
        return json.loads(json.dumps(self.current))

    def checks(self, repo, sha):
        return {"passed": self.passed, "head": sha, "checks": []}

    def paginate(self, path):
        return self.reviews

    def verify_publisher(self):
        pass

    def request(self, method, path, body=None):
        self.writes.append((method, path, body))
        return {"id": 1, "number": 1, "html_url": "https://example.test/1"}

    def review(self, repo, number, sha, verdict, body):
        return self.request("POST", "/reviews", {"head": sha, "verdict": verdict, "body": body})

    def audit(self, repo):
        return {"summary": "audit fixture", "risks": []}


class BaseTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="mikasa-test-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name).resolve()
        self.repo = self.path / "source"
        self.repo.mkdir()
        git(["init", "-b", "main"], self.repo)
        (self.repo / "app.py").write_text("VALUE = 1\n")
        (self.repo / "README.md").write_text("Fixture project.\n")
        git(["add", "."], self.repo)
        git(["-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "fixture"], self.repo)
        self.data = json.loads((ROOT / "config/examples/mikasa.json").read_text())
        self.data.update({"project_root": str(ROOT), "runtime": str(self.path / "runtime"), "members": ["human"]})
        self.data["repositories"] = {REPO: {"source": str(self.repo), "base": "main", "allow_local_checks": True, "checks": [[sys.executable, "-c", "from app import VALUE; assert VALUE == 2"]]}}
        self.data["worker"]["command"] = [sys.executable, str(ROOT / "tests/fixtures/worker.py")]
        self.config_path = self.path / "config.json"
        self.write_config()
        self.github = FakeGitHub()
        self.service = Service(self.config, github=self.github)

    def write_config(self):
        self.config_path.write_text(json.dumps(self.data))
        self.config = Config.load(self.config_path)

    def submit(self, kind="implement", key="test", **kwargs):
        return self.service.submit({"kind": kind, "repo": REPO, "title": "Change value", "acceptance": "VALUE equals 2", **kwargs}, self.config.owner, key)
