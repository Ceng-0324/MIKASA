import json
import sys
import tempfile
import unittest
from pathlib import Path

from mikasa.config import Config
from mikasa.process import git
from mikasa.store import Store

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
        self.config_path = self.path / "config.json"
        self.write_config()
        self.store = Store(self.config.runtime)

    def write_config(self):
        self.config_path.write_text(json.dumps(self.data))
        self.config = Config.load(self.config_path)


def resolved_command(config, text, cancelled=lambda: False):
    return command_reply(text, cancelled)
