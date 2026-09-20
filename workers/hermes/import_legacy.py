"""One-time non-destructive transcript import using the pinned Hermes SessionDB."""
import json
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, os.environ["MIKASA_HERMES_SOURCE"])


def import_chats(database, actor):
    from hermes_state import SessionDB
    source = Path(database)
    if not source.exists():
        return
    legacy = sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)
    native = SessionDB()
    try:
        for session, model in legacy.execute("SELECT id,model FROM chats WHERE actor=?", (actor,)):
            done = native.get_session_model_config_value(session, "mikasa_legacy_import", False)
            if done:
                continue
            messages = []
            for message, receipt, created in legacy.execute(
                    "SELECT message,response,created FROM chat_turns WHERE chat_id=? ORDER BY seq", (session,)):
                response = json.loads(receipt)
                if response["kind"] == "chat":
                    messages.extend([{"role": "user", "content": message, "timestamp": created},
                                     {"role": "assistant", "content": response["reply"], "timestamp": created}])
            if native.get_session(session) is None:
                native.create_session(session, "mikasa_legacy", model=model)
            existing = native.get_messages(session)
            if existing:
                pairs = lambda rows: [(m["role"], m["content"]) for m in rows]
                if pairs(existing[:len(messages)]) != pairs(messages):
                    raise RuntimeError("legacy import conflicts with an existing native transcript")
            elif messages:
                native.append_messages_batch(session, messages)
            native.patch_session_model_config(session, {"mikasa_legacy_import": True})
    finally:
        native.close()
        legacy.close()


if __name__ == "__main__":
    import_chats(sys.argv[1], sys.argv[2])
