import json
import os
import sys
from unittest.mock import patch

from mikasa.config import Config
from mikasa.errors import Conflict, MikasaError
from mikasa.process import check_command, git
from mikasa.service import Service
from mikasa.worker import Worker
from tests.support import BaseTest, REPO, SHA


class RecoveryTests(BaseTest):
    def test_repair_uses_failed_check_evidence(self):
        calls = []

        class RepairWorker:
            def execute(self, task, context, cancelled):
                calls.append(json.loads(json.dumps(context)))
                return {"summary": "repair", "changes": [{"path": "app.py", "content": f"VALUE = {2 if len(calls) > 1 else 0}\n"}]}

        self.service.worker = RepairWorker()
        self.submit()
        result = self.service.run_once()
        self.assertEqual(result["state"], "awaiting_review")
        self.assertEqual(len(calls), 2)
        self.assertNotEqual(calls[1]["repair"]["checks"][0]["code"], 0)
        self.assertEqual(len(result["result"]["attempts"]), 2)

    def test_provenance_cannot_be_laundered_by_new_head(self):
        self.service.store.provenance(REPO, 1, SHA, "mikasa", self.config.owner)
        self.assertEqual(self.service.store.get_provenance(REPO, 1, "b" * 40), "mikasa")
        with self.assertRaises(Conflict):
            self.service.store.provenance(REPO, 1, "b" * 40, "human", self.config.owner)

    def test_periodic_audit_is_idempotent_and_pauses(self):
        self.data["schedules"] = {"audit_interval_seconds": 60}
        self.write_config()
        service = Service(self.config, github=self.github)
        with patch("mikasa.service.time.time", return_value=120):
            service.schedule()
            service.schedule()
            self.assertEqual(len(service.store.list()), 1)
            self.assertEqual(service.run_once()["state"], "done")
            self.assertIsNone(service.run_once())
        service.store.pause(True, self.config.owner)
        with patch("mikasa.service.time.time", return_value=180):
            service.schedule()
        self.assertEqual(len(service.store.list()), 1)

    def test_reconcile_requires_independent_approval_and_merge(self):
        task = self.submit()
        result = self.service.run_once()["result"]
        self.github.current["head"]["sha"] = result["head"]
        self.github.current["user"]["login"] = self.config.bot
        with self.assertRaises(Conflict):
            self.service.reconcile(task["id"], 1, self.config.owner)
        self.github.reviews = [{"user": {"login": self.config.owner}, "state": "APPROVED", "commit_id": result["head"]}]
        with self.assertRaises(Conflict):
            self.service.reconcile(task["id"], 1, self.config.owner)
        self.github.current["merged"] = True
        self.assertEqual(self.service.reconcile(task["id"], 1, self.config.owner)["state"], "done")

    def test_publication_recovery_validates_marker(self):
        task = self.submit("plan")
        self.service.run_once()
        self.service.store.reserve_publication(task["id"])
        record = {"id": 1, "number": 1, "user": {"login": self.config.bot}, "body": "unrelated"}
        with patch.object(self.github, "request", return_value=record):
            with self.assertRaises(Conflict):
                self.service.resolve_publication(task["id"], 1, self.config.owner)
            record["body"] = f"<!-- mikasa-task:{task['id']} -->"
            self.assertEqual(self.service.resolve_publication(task["id"], 1, self.config.owner)["number"], 1)
        with self.assertRaises(Conflict):
            self.service.publish(task["id"], self.config.owner)

    def test_checks_default_to_isolation(self):
        with self.assertRaisesRegex(MikasaError, "check_image"):
            check_command([sys.executable, "-c", "pass"], {}, self.path, 2, lambda: False)

    def test_config_rejects_bad_runtime_inputs(self):
        for field, value in (("owner", "imposter"), ("repositories", []), ("worker", {"timeout": -1}),
                             ("server", {"tokens": {"unknown": "TOKEN"}}), ("schedules", {"audit_interval_seconds": 1})):
            with self.subTest(field=field):
                bad = dict(self.data)
                bad[field] = value
                self.config_path.write_text(json.dumps(bad))
                with self.assertRaises(MikasaError):
                    Config.load(self.config_path)

    def test_worker_rejects_untrusted_metadata(self):
        self.data["worker"]["command"] = [sys.executable, "-c", "import json; print(json.dumps({'version':1,'runtime':{'backend':'fixture'},'result':{'summary':'x','changes':[],'workspace':'/tmp/escape'}}))"]
        self.write_config()
        task = self.submit()
        with self.assertRaisesRegex(MikasaError, "output_contract"):
            Worker(self.config).execute(task, {}, lambda: False)

    def test_model_process_cancellation(self):
        from mikasa.process import run
        with self.assertRaisesRegex(MikasaError, "取消"):
            run([sys.executable, "-c", "import time; time.sleep(30)"], cwd=self.path, cancelled=lambda: True)

    def test_validation_cannot_change_index(self):
        self.data["repositories"][REPO]["checks"] = [[sys.executable, "-c", "import subprocess; subprocess.run(['git','reset','HEAD'], check=True)"]]
        self.write_config()
        self.service = Service(self.config, github=self.github)
        self.submit()
        task = self.service.run_once()
        self.assertEqual(task["state"], "failed")
        self.assertIn("索引", task["error"])
