"""Use the pinned adapter's credential probe without forwarding SDK diagnostics."""
import contextlib
import io
import json
import logging
import os
import sys

sys.path.insert(0, os.environ["MIKASA_HERMES_SOURCE"])

if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            from plugins.platforms.feishu.adapter import probe_bot
            result = probe_bot(os.environ["FEISHU_APP_ID"], os.environ["FEISHU_APP_SECRET"], os.environ["FEISHU_DOMAIN"])
        if not result or not result.get("bot_open_id"):
            raise ValueError("missing bot identity")
    except Exception:
        print(json.dumps({"connection": "failed"}))
        raise SystemExit(1) from None
    print(json.dumps({"connection": "passed", "bot_identity": "passed"}))
