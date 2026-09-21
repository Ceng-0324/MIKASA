import json
import sqlite3
import time
from contextlib import contextmanager

from .errors import Conflict, MikasaError
from .maintenance import runtime_lock


class Store:
    def __init__(self, runtime):
        runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = runtime / "mikasa.sqlite3"
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT,
                    kind TEXT NOT NULL, actor TEXT NOT NULL, data TEXT NOT NULL,
                    created REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS chats (
                    id TEXT PRIMARY KEY, actor TEXT NOT NULL, model TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS chat_turns (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, chat_id TEXT NOT NULL,
                    request_key TEXT NOT NULL, message TEXT NOT NULL, response TEXT NOT NULL,
                    created REAL NOT NULL, UNIQUE(chat_id, request_key)
                );
                CREATE TABLE IF NOT EXISTS chat_links (
                    id TEXT PRIMARY KEY, actor TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS chat_requests (
                    chat_id TEXT NOT NULL, request_key TEXT NOT NULL,
                    digest TEXT NOT NULL, kind TEXT NOT NULL, receipt TEXT,
                    request_model TEXT, request_revision INTEGER, active_run TEXT,
                    UNIQUE(chat_id, request_key)
                );
                CREATE TABLE IF NOT EXISTS deliveries (id TEXT PRIMARY KEY, received REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS publications (
                    task_id TEXT PRIMARY KEY, state TEXT NOT NULL, result TEXT, updated REAL NOT NULL
                );

            """)
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in {0, 1, 2}:
                raise MikasaError("数据库版本不兼容；需要明确迁移后才能运行")
            if version < 2:
                # Empty legacy schema is only a migration input, never a queue.
                db.execute("""CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL, payload TEXT NOT NULL,
                    actor TEXT NOT NULL, assignee TEXT NOT NULL, state TEXT NOT NULL,
                    result TEXT, error TEXT, run_token TEXT, updated REAL NOT NULL, created REAL NOT NULL)""")
                db.execute("PRAGMA user_version=1")
            # Old reviews tables and transcripts remain archives; no governance reads/writes.
            # Additive upgrade of the early native migration.
            columns = {r[1] for r in db.execute("PRAGMA table_info(chat_requests)")}
            for name, kind in (("request_model", "TEXT"), ("request_revision", "INTEGER"), ("active_run", "TEXT")):
                if name not in columns:
                    db.execute(f"ALTER TABLE chat_requests ADD COLUMN {name} {kind}")
        self.path.chmod(0o600)

    @contextmanager
    def connect(self):
        with runtime_lock(self.path.parent):
            with self._connect() as db:
                yield db

    @contextmanager
    def _connect(self):
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

    def paused(self):
        with self.connect() as db:
            row = db.execute("SELECT value FROM settings WHERE key='paused'").fetchone()
            return row is not None and row[0] == "true"

    def pause(self, paused, actor):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO settings VALUES('paused',?)", (json.dumps(paused),))
            self.event(db, None, "pause", actor, {"paused": paused})

    def delivery(self, delivery_id, data):
        with self.connect() as db:
            inserted = db.execute("INSERT OR IGNORE INTO deliveries VALUES(?,?)", (delivery_id, time.time())).rowcount
            if inserted:
                self.event(db, None, "github_event", "github", data)
            return bool(inserted)

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
