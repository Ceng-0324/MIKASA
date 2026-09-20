#!/usr/bin/env python3
"""Exercise the installed Hermes command components without model credentials."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mikasa.config import Config
from mikasa.worker import Worker


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    worker = Worker(Config.load(args.config))
    cases = [
        ("/model", "status", None),
        ("/MODEL vendor/model:variant —session", "switch", "vendor/model:variant"),
        ("/model claude-opus-4-6 --session", "switch", "claude-opus-4-6"),
        ("/model default", "reset", None),
        ("/model x --global", "help", None),
        ("/model x --once --global", "help", None),
        ("/model x --provider foreign", "help", None),
        ("/model x --reasoning wrong", "help", None),
        ("/model --refresh", "help", None),
        ("/model x --unknown", "help", None),
        ("/new", "new", None), ("/reset", "new", None),
        ("/new extra", "help", None), ("/init", "deferred_command", None),
        ("/help", "help", None), ("/v", "version", None),
        ("/unknown value", "unsupported_command", None),
    ]
    checks = []
    for text, kind, target in cases:
        result = worker.command(text, lambda: False)
        passed = result["kind"] == kind and result["target"] == target
        if kind == "version":
            passed = passed and bool(result["reply"]) and "Hermes" in result["reply"]
        checks.append({"command": text, "passed": passed})
    report = {"passed": all(c["passed"] for c in checks), "checks": checks}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
