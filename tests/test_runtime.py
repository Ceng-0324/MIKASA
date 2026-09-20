import concurrent.futures
import json
import os
import sys
from unittest.mock import patch

from mikasa.errors import Conflict, Forbidden, MikasaError
from mikasa.process import run, git
from mikasa.service import Service
from mikasa.workspace import Workspace
from tests.support import BaseTest, REPO, SHA


class RuntimeTests(BaseTest):
    def test_implementation_commit_and_validation(self):
        task = self.submit()
        result = self.service.run_once()
        self.assertEqual(result["state"], "awaiting_review")
        self.assertEqual(result["result"]["checks"][0]["code"], 0)
        self.assertNotEqual(result["result"]["head"], result["result"]["base"])
        self.assertEqual((self.repo / "app.py").read_text(), "VALUE = 1\n")
        self.assertEqual(self.github.writes, [])
        completed = self.service.action(task["id"], "complete", self.config.owner,
                                        {"evidence": "本次验收只要求本地提交与测试，已完成"})
        self.assertEqual(completed["state"], "done")
        self.assertFalse(self.github.current["merged"])
        self.assertEqual(self.github.reviews, [])

    def test_failed_checks_block_delivery(self):
        self.data["repositories"][REPO]["checks"] = [[sys.executable, "-c", "raise SystemExit(2)"]]
        self.write_config()
        self.service = Service(self.config, github=self.github)
        self.submit()
        task = self.service.run_once()
        self.assertEqual(task["state"], "blocked")
        self.assertEqual(task["result"]["checks"][0]["code"], 2)

    def test_missing_checks_do_not_claim_verified(self):
        self.data["repositories"][REPO]["checks"] = []
        self.write_config()
        self.service = Service(self.config, github=self.github)
        self.submit()
        self.assertEqual(self.service.run_once()["state"], "blocked")

    def test_idempotency_and_payload_conflict(self):
        first = self.submit()
        self.assertEqual(self.submit()["id"], first["id"])
        with self.assertRaises(Conflict):
            self.submit("audit")

    def test_concurrent_claim_exactly_once(self):
        self.submit()
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.service.store.claim(self.config.bot), range(8)))
        self.assertEqual(sum(r is not None for r in results), 1)

    def test_cancel_invalidates_running_result(self):
        task = self.submit()
        _, token = self.service.store.claim(self.config.bot)
        self.service.action(task["id"], "cancel", self.config.owner)
        with self.assertRaises(Conflict):
            self.service.store.finish(task["id"], token, "done", {})
        self.assertEqual(self.service.store.get(task["id"])["state"], "cancelled")

    def test_recover_does_not_retry_side_effects(self):
        task = self.submit()
        self.service.store.claim(self.config.bot)
        self.assertEqual(self.service.store.recover("test"), 1)
        self.assertEqual(self.service.store.get(task["id"])["state"], "failed")
        self.assertIsNone(self.service.store.claim(self.config.bot))

    def test_pause_blocks_claim(self):
        self.submit()
        self.service.store.pause(True, self.config.owner)
        self.assertIsNone(self.service.run_once())
        self.service.store.pause(False, self.config.owner)
        self.assertEqual(self.service.run_once()["state"], "awaiting_review")

    def test_plan_expand_idempotent_dependencies(self):
        task = self.submit("plan")
        self.assertEqual(self.service.run_once()["state"], "done")
        children = self.service.expand(task["id"], self.config.owner)
        again = self.service.expand(task["id"], self.config.owner)
        self.assertEqual([t["id"] for t in children], [t["id"] for t in again])
        self.assertEqual(children[1]["payload"]["depends_on"], [children[0]["id"]])
        first = self.service.run_once()
        self.assertEqual(first["id"], children[0]["id"])
        self.assertIsNone(self.service.run_once())  # Awaiting review is not completed.

    def test_assigned_human_is_not_taken_over(self):
        task = self.submit(assignee="human")
        self.assertIsNone(self.service.run_once())
        self.service.action(task["id"], "assign", self.config.owner, {"assignee": self.config.bot})
        self.assertEqual(self.service.run_once()["id"], task["id"])

    def test_member_cannot_implement_or_assign(self):
        with self.assertRaises(Forbidden):
            self.service.submit({"kind": "implement", "repo": REPO, "title": "x", "acceptance": "y"}, "human", "member")

    def test_timeout_and_output_limit(self):
        with self.assertRaisesRegex(MikasaError, "超时"):
            run([sys.executable, "-c", "import time; time.sleep(5)"], cwd=self.path, timeout=0.1)
        with self.assertRaisesRegex(MikasaError, "上限"):
            run([sys.executable, "-c", "print('x'*10000)"], cwd=self.path, limit=100)

    def test_worker_env_excludes_github_secret(self):
        with patch.dict(os.environ, {"MIKASA_GITHUB_TOKEN": "not-in-worker"}):
            result = run([sys.executable, "-c", "import os; assert 'MIKASA_GITHUB_TOKEN' not in os.environ"], cwd=self.path)
        self.assertEqual(result["code"], 0)

    def test_workspace_rejects_escape_rules_symlink(self):
        task = self.submit()
        ws = Workspace(self.config, task, "attempt").prepare()
        for name in ("../outside", "/tmp/outside", ".git/config", ".github/workflows/x.yml", "AGENTS.md", ".env", "a/../../x"):
            with self.subTest(name=name), self.assertRaises(MikasaError):
                ws.apply([{"path": name, "content": "bad"}])
        (ws.path / "link").symlink_to(self.path)
        with self.assertRaises(MikasaError):
            ws.apply([{"path": "link/outside", "content": "bad"}])
        self.assertFalse((self.path / "outside").exists())

    def test_apply_validates_all_paths_before_writes(self):
        ws = Workspace(self.config, self.submit(), "attempt").prepare()
        with self.assertRaises(MikasaError):
            ws.apply([{"path": "new.py", "content": "x"}, {"path": "../bad", "content": "y"}])
        self.assertFalse((ws.path / "new.py").exists())

    def test_review_keeps_agent_judgment_without_authorship_gate(self):
        base = git(["rev-parse", "HEAD"], self.repo)
        git(["update-ref", "refs/pull/1/head", base], self.repo)
        self.github.current["head"]["sha"] = base
        self.github.current["base"]["sha"] = base
        self.github.current["user"]["login"] = self.config.bot
        self.submit("review", pr=1)
        task = self.service.run_once()
        self.assertEqual(task["state"], "done")
        self.assertEqual(task["result"]["verdict"], "APPROVED")
        self.assertNotIn("provenance", task["result"])
        self.service.publish(task["id"], self.config.owner)
        self.assertEqual(self.github.writes[-1][2]["verdict"], "APPROVED")

    def test_publish_plan_deduplicates(self):
        task = self.submit("plan")
        self.service.run_once()
        self.service.publish(task["id"], self.config.owner)
        with self.assertRaises(Conflict):
            self.service.publish(task["id"], self.config.owner)
        self.assertEqual(len(self.github.writes), 1)

    def test_review_missing_files_reported_without_rewriting_judgment(self):
        base = git(["rev-parse", "HEAD"], self.repo)
        (self.repo / "large.txt").write_text("x" * 70000)
        git(["add", "large.txt"], self.repo)
        git(["-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "large change"], self.repo)
        head = git(["rev-parse", "HEAD"], self.repo)
        git(["update-ref", "refs/pull/1/head", head], self.repo)
        # Move the fixture's main ref back without touching its worktree.
        git(["update-ref", "refs/heads/main", base], self.repo)
        self.github.current["head"]["sha"] = head
        self.github.current["base"]["sha"] = base
        self.submit("review", pr=1)
        task = self.service.run_once()
        self.assertEqual(task["state"], "done")
        self.assertEqual(task["result"]["verdict"], "APPROVED")
        self.assertTrue(any("未读取" in text for text in task["result"]["limitations"]))

    def test_review_complete_human_change_can_approve(self):
        base = git(["rev-parse", "HEAD"], self.repo)
        git(["update-ref", "refs/pull/1/head", base], self.repo)
        self.github.current["head"]["sha"] = base
        self.github.current["base"]["sha"] = base
        self.submit("review", pr=1)
        task = self.service.run_once()
        self.assertEqual(task["state"], "done")
        self.assertEqual(task["result"]["verdict"], "APPROVED")

    def test_review_ci_evidence_does_not_choose_verdict_but_cannot_go_stale(self):
        base = git(["rev-parse", "HEAD"], self.repo)
        git(["update-ref", "refs/pull/1/head", base], self.repo)
        self.github.current["head"]["sha"] = base
        self.github.current["base"]["sha"] = base
        self.github.passed = False
        self.submit("review", pr=1)
        task = self.service.run_once()
        self.assertEqual(task["result"]["verdict"], "APPROVED")
        self.assertFalse(task["result"]["ci"]["passed"])
        self.assertTrue(task["result"]["limitations"])
        self.github.passed = True
        with self.assertRaisesRegex(Conflict, "CI 证据已变化"):
            self.service.publish(task["id"], self.config.owner)
        self.assertEqual(self.github.writes, [])
        self.github.passed = False
        self.service.publish(task["id"], self.config.owner)
        self.assertEqual(self.github.writes[-1][2]["verdict"], "APPROVED")

    def test_uncertain_publication_not_retried(self):
        task = self.submit("plan")
        self.service.run_once()
        with patch.object(self.github, "request", side_effect=MikasaError("network")):
            with self.assertRaises(MikasaError):
                self.service.publish(task["id"], self.config.owner)
        with self.assertRaises(Conflict):
            self.service.publish(task["id"], self.config.owner)

    def test_unknown_repo_rejected(self):
        with self.assertRaises(MikasaError):
            self.submit(repo="elsewhere/unknown")
