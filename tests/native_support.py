"""Stateful native API double for business-boundary tests; live probe tests Hermes."""
import uuid
from mikasa.errors import MikasaError


class Gateway:
    def __init__(self):
        self.sessions, self.runs, self.keys = {}, {}, {}
        self.fail = False
        self.before_wait = lambda: None
        self.calls = []

    def ensure_session(self, session, model):
        self.sessions.setdefault(session, {"model": model, "messages": []})

    def session(self, session):
        return {"model": self.sessions[session]["model"]}

    def messages(self, session):
        return {"session_id": session, "data": self.sessions[session]["messages"], "pagination": {"limit": 500}}

    def set_model(self, session, model):
        self.sessions[session]["model"] = model

    def start(self, session, message, model, key):
        if key in self.keys:
            return {"run_id": self.keys[key]}
        self.calls.append({"session": session, "model": model, "message": message})
        run = uuid.uuid4().hex
        self.keys[key] = run
        self.runs[run] = {"output": "Mikasa 回复", "runtime": {"model": model, "provider": "custom"}}
        self.sessions[session]["messages"].extend([{"role": "user", "content": message}, {"role": "assistant", "content": "Mikasa 回复"}])
        return {"run_id": run}

    def wait(self, run, cancelled=lambda: False):
        self.before_wait()
        if self.fail or cancelled():
            raise MikasaError("private provider diagnostic")
        return self.runs[run]


class Gateways:
    def __init__(self, *args):
        self.instances = {}
        self.closed = False

    def for_actor(self, actor):
        return self.instances.setdefault(actor, Gateway())

    def close(self):
        self.closed = True
