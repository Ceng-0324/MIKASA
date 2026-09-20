#!/usr/bin/env python3
"""Run with the pinned Hermes venv; stdin/stdout implement worker protocol v1."""

import contextlib
import json
import os
import sys
from pathlib import Path


def main():
    request = json.loads(sys.stdin.read(2_000_001))
    if request.get("version") != 1:
        raise ValueError("unsupported worker protocol")
    for key in ("HERMES_HOME", "MIKASA_MODEL", "MIKASA_MODEL_BASE_URL", "MIKASA_MODEL_API_KEY"):
        if not os.environ.get(key):
            raise ValueError(f"missing {key}")
    if not Path(os.environ["HERMES_HOME"]).is_absolute():
        raise ValueError("HERMES_HOME must be an isolated absolute path")
    with contextlib.redirect_stdout(sys.stderr):
        from run_agent import AIAgent

        agent = AIAgent(
            model=os.environ["MIKASA_MODEL"], base_url=os.environ["MIKASA_MODEL_BASE_URL"],
            api_key=os.environ["MIKASA_MODEL_API_KEY"], provider="custom", api_mode="chat_completions",
            enabled_toolsets=[], max_iterations=2, quiet_mode=True,
            skip_context_files=True, skip_memory=True, skip_background_review=True,
            save_trajectories=False, load_soul_identity=False,
        )
        if getattr(agent, "tools", None):
            raise RuntimeError("Hermes unexpectedly enabled tools")
        result = agent.run_conversation(
            user_message=json.dumps({k: v for k, v in request.items() if k != "rules"}, ensure_ascii=False),
            system_message=request["rules"] + "\n仅按 output_contract 返回 JSON，不附代码围栏。",
        )
        if result.get("failed") or result.get("interrupted"):
            raise RuntimeError("Hermes conversation did not complete")
        output = json.loads(result["final_response"])
    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # SDK exceptions may embed authorization headers or endpoint credentials.
        print(f"Hermes bridge failed: {type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1)
