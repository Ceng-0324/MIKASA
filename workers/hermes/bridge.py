#!/usr/bin/env python3
"""Run with the pinned Hermes venv; stdin/stdout implement worker protocol v1."""

import contextlib
import hashlib
import importlib.metadata
import json
import os
import re
import sys
import tempfile
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
    home = Path(os.environ["HERMES_HOME"]).resolve()
    if home == Path.home().resolve() or home == (Path.home() / ".hermes").resolve():
        raise ValueError("refusing a personal Hermes home")
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    source = os.environ.get("MIKASA_HERMES_SOURCE")
    if source:
        source = Path(source).resolve()
        if not (source / "run_agent.py").is_file():
            raise ValueError("Hermes source is incomplete")
        sys.path.insert(0, str(source))
    mode = os.environ.get("MIKASA_MODEL_API_MODE", "chat_completions")
    if mode not in {"chat_completions", "codex_responses"}:
        raise ValueError("unsupported model API mode")
    skills = request.get("skills", [])
    for skill in skills:
        if hashlib.sha256(skill["content"].encode()).hexdigest() != skill["sha256"]:
            raise ValueError("skill digest mismatch")
    system_message = request["rules"] + "\n\n" + request.get("instruction", "")
    for skill in skills:
        system_message += f"\n\n<project-skill name=\"{skill['name']}\">\n{skill['content']}\n</project-skill>"
    system_message += "\n仅按 output_contract 返回 JSON，不附代码围栏。"
    # Discard SDK console diagnostics; dedicated SDK home logs are checked separately.
    with tempfile.TemporaryFile(mode="w+") as diagnostics, contextlib.redirect_stdout(diagnostics), contextlib.redirect_stderr(diagnostics):
        from run_agent import AIAgent
        from hermes_cli.plugins import PluginContext, PluginManifest, get_plugin_manager

        observed_models = []

        def observe_response(**fields):
            model = fields.get("response_model")
            if isinstance(model, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,199}", model):
                observed_models.append(model)

        # Public lifecycle registration, scoped to this one-shot worker process.
        observer = PluginContext(PluginManifest(name="mikasa-runtime"), get_plugin_manager())
        observer.register_hook("post_api_request", observe_response)

        agent = AIAgent(
            model=os.environ["MIKASA_MODEL"], base_url=os.environ["MIKASA_MODEL_BASE_URL"],
            api_key=os.environ["MIKASA_MODEL_API_KEY"], provider="custom", api_mode=mode,
            enabled_toolsets=[], max_iterations=2, quiet_mode=True,
            skip_context_files=True, skip_memory=True, skip_background_review=True,
            save_trajectories=False, load_soul_identity=False,
            max_tokens=4096, run_budget_seconds=120,
        )
        if getattr(agent, "tools", None):
            raise RuntimeError("Hermes unexpectedly enabled tools")
        result = agent.run_conversation(
            user_message=json.dumps({k: v for k, v in request.items() if k not in {"rules", "skills", "instruction"}}, ensure_ascii=False),
            system_message=system_message,
        )
        if result.get("failed") or result.get("interrupted"):
            raise RuntimeError("Hermes conversation did not complete")
        output = json.loads(result["final_response"])
    try:
        version = importlib.metadata.version("hermes-agent")
    except importlib.metadata.PackageNotFoundError:
        version = "source-checkout"
    runtime = {"backend": "hermes", "version": version, "requested_model": os.environ["MIKASA_MODEL"],
               "api_mode": mode, "tool_count": len(agent.tools or []),
               "reported_model": observed_models[-1] if observed_models else None,
               "rules_sha256": hashlib.sha256(request["rules"].encode()).hexdigest(),
               "system_sha256": hashlib.sha256(system_message.encode()).hexdigest(),
               "skills": [{k: s[k] for k in ("name", "sha256", "source")} for s in skills]}
    print(json.dumps({"version": 1, "result": output, "runtime": runtime}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # SDK exceptions may embed authorization headers or endpoint credentials.
        print(f"Hermes bridge failed: {type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1)
