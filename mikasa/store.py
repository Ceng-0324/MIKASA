import json
import sqlite3
import time
import uuid
from contextlib import contextmanager

from .errors import Conflict, NotFound, MikasaError


class Store:
    def __init__(self, runtime):
        runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = runtime / "mikasa.sqlite3"
        with self.connect() as db:
            if db.execute("PRAGMA user_version").fetchone()[0] not in {0, 1}:
                raise MikasaError("数据库版本不兼容；需要明确迁移后才能运行")
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL,
                    payload TEXT NOT NULL, actor TEXT NOT NULL,
                    assignee TEXT NOT NULL, state TEXT NOT NULL,
                    result TEXT, error TEXT, run_token TEXT,
                    updated REAL NOT NULL, created REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT,
                    kind TEXT NOT NULL, actor TEXT NOT NULL, data TEXT NOT NULL,
                    created REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS deliveries (id TEXT PRIMARY KEY, received REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS reviews (
                    repo TEXT NOT NULL, number INTEGER NOT NULL, head TEXT NOT NULL,
                    provenance TEXT NOT NULL, actor TEXT NOT NULL, updated REAL NOT NULL,
                    PRIMARY KEY(repo, number)
                );
                CREATE TABLE IF NOT EXISTS publications (
                    task_id TEXT PRIMARY KEY, state TEXT NOT NULL, result TEXT, updated REAL NOT NULL
                );
                PRAGMA user_version=1;
            """)
        self.path.chmod(0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def event(db, task, kind, actor, data):
        db.execute("INSERT INTO events(task_id,kind,actor,data,created) VALUES(?,?,?,?,?)",
                   (task, kind, actor, json.dumps(data, ensure_ascii=False), time.time()))

    @staticmethod
    def decode(row):
        if row is None:
            raise NotFound("任务不存在")
        result = dict(row)
        for key in ("payload", "result"):
            if result[key] is not None:
                result[key] = json.loads(result[key])
        result.pop("run_token", None)
        return result

    def create(self, payload, actor, assignee, key):
        if not isinstance(key, str) or not 1 <= len(key) <= 200:
            raise MikasaError("request_key 必须为 1–200 字符")
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT * FROM tasks WHERE request_key=?", (key,)).fetchone()
            if existing:
                if existing["payload"] != encoded or existing["actor"] != actor:
                    raise Conflict("幂等键已用于另一请求")
                return self.decode(existing)
            for dep in payload.get("depends_on", []):
                if not db.execute("SELECT 1 FROM tasks WHERE id=?", (dep,)).fetchone():
                    raise MikasaError("依赖任务不存在")
            task = uuid.uuid4().hex
            now = time.time()
            db.execute("INSERT INTO tasks VALUES(?,?,?,?,?,?,NULL,NULL,NULL,?,?)",
                       (task, key, encoded, actor, assignee, "queued", now, now))
            self.event(db, task, "created", actor, payload)
            return self.decode(db.execute("SELECT * FROM tasks WHERE id=?", (task,)).fetchone())

    def get(self, task):
        with self.connect() as db:
            return self.decode(db.execute("SELECT * FROM tasks WHERE id=?", (task,)).fetchone())

    def list(self):
        with self.connect() as db:
            return [self.decode(r) for r in db.execute("SELECT * FROM tasks ORDER BY created DESC LIMIT 500")]

    def events(self, task):
        self.get(task)
        with self.connect() as db:
            return [{**dict(r), "data": json.loads(r["data"])} for r in
                    db.execute("SELECT * FROM events WHERE task_id=? ORDER BY seq", (task,))]

    def paused(self):
        with self.connect() as db:
            row = db.execute("SELECT value FROM settings WHERE key='paused'").fetchone()
            return row is not None and row[0] == "true"

    def pause(self, paused, actor):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO settings VALUES('paused',?)", (json.dumps(paused),))
            self.event(db, None, "pause", actor, {"paused": paused})

    def claim(self, bot):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            paused = db.execute("SELECT value FROM settings WHERE key='paused'").fetchone()
            if paused and paused[0] == "true":
                return None
            for row in db.execute("SELECT * FROM tasks WHERE state='queued' AND assignee=? ORDER BY created", (bot,)).fetchall():
                task = self.decode(row)
                deps = task["payload"].get("depends_on", [])
                if any(db.execute("SELECT state FROM tasks WHERE id=?", (d,)).fetchone()[0] != "done" for d in deps):
                    continue
                token = uuid.uuid4().hex
                db.execute("UPDATE tasks SET state='running',run_token=?,updated=? WHERE id=?",
                           (token, time.time(), task["id"]))
                self.event(db, task["id"], "started", bot, {})
                task["state"] = "running"
                return task, token
            return None

    def finish(self, task, token, state, result=None, error=None):
        if state not in {"done", "failed", "awaiting_review", "blocked"}:
            raise MikasaError("非法执行结束状态")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            changed = db.execute("UPDATE tasks SET state=?,result=?,error=?,run_token=NULL,updated=? WHERE id=? AND state='running' AND run_token=?",
                                 (state, json.dumps(result, ensure_ascii=False), error, time.time(), task, token)).rowcount
            if not changed:
                raise Conflict("任务已取消或执行令牌失效，结果未提交")
            self.event(db, task, state, "runtime", {"error": error})

    def transition(self, task, action, actor, *, assignee=None, evidence=None):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM tasks WHERE id=?", (task,)).fetchone()
            current = self.decode(row)
            state = current["state"]
            target = state
            if action == "cancel" and state not in {"done", "cancelled"}:
                target = "cancelled"
            elif action == "retry" and state in {"failed", "blocked", "cancelled"}:
                target = "queued"
            elif action == "assign" and state in {"queued", "blocked"} and assignee:
                target = "queued"
            elif action == "complete" and state in {"queued", "awaiting_review", "blocked"} and evidence:
                target = "done"
            else:
                raise Conflict("当前状态不允许此操作，或缺少交付证据")
            db.execute("UPDATE tasks SET state=?,assignee=?,run_token=NULL,updated=? WHERE id=?",
                       (target, assignee or row["assignee"], time.time(), task))
            self.event(db, task, action, actor, {"assignee": assignee, "evidence": evidence})
        return self.get(task)

    def recover(self, actor):
        """Only call under the runner's exclusive process lock."""
        with self.connect() as db:
            rows = db.execute("SELECT id FROM tasks WHERE state='running'").fetchall()
            for row in rows:
                db.execute("UPDATE tasks SET state='failed',run_token=NULL,error=?,updated=? WHERE id=?",
                           ("执行进程中断；检查保留的工作区后显式重试", time.time(), row[0]))
                self.event(db, row[0], "interrupted", actor, {})
            return len(rows)

    def delivery(self, delivery_id, data):
        with self.connect() as db:
            inserted = db.execute("INSERT OR IGNORE INTO deliveries VALUES(?,?)", (delivery_id, time.time())).rowcount
            if inserted:
                self.event(db, None, "github_event", "github", data)
            return bool(inserted)

    def provenance(self, repo, number, head, value, actor):
        if value not in {"human", "mikasa"}:
            raise MikasaError("产出归属只能为 human 或 mikasa")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT provenance FROM reviews WHERE repo=? AND number=?", (repo, number)).fetchone()
            if previous and previous[0] == "mikasa" and value != "mikasa":
                raise Conflict("已经由 Mikasa 参与实现的 PR 不能重新归类为纯人类产出")
            db.execute("INSERT OR REPLACE INTO reviews VALUES(?,?,?,?,?,?)", (repo, number, head, value, actor, time.time()))
            self.event(db, None, "provenance", actor, {"repo": repo, "number": number, "head": head, "value": value})

    def get_provenance(self, repo, number, head):
        with self.connect() as db:
            row = db.execute("SELECT provenance,head FROM reviews WHERE repo=? AND number=?", (repo, number)).fetchone()
            return row[0] if row and (row[0] == "mikasa" or row[1] == head) else "unknown"

    def reserve_publication(self, task):
        with self.connect() as db:
            try:
                db.execute("INSERT INTO publications VALUES(?,'pending',NULL,?)", (task, time.time()))
            except sqlite3.IntegrityError as exc:
                raise Conflict("该任务已经发布或发布状态待核对；拒绝重复外部写入") from exc

    def publication(self, task, state, result):
        with self.connect() as db:
            db.execute("UPDATE publications SET state=?,result=?,updated=? WHERE task_id=?",
                       (state, json.dumps(result, ensure_ascii=False), time.time(), task))
            self.event(db, task, "publication", "runtime", {"state": state, "result": result})
