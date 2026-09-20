---
name: mikasa-implement
description: Produce verifiable code changes and repair failed checks in Mikasa's isolated implementation worker.
---

Adapted from mattpocock/skills `tdd` and `implement`; source and adaptation are recorded in [SOURCES.md](../SOURCES.md).

Use the public behavior and acceptance criteria as the test seam. Choose independent expected values from the requirement, not by recomputing the same implementation. Favor behavior tests that survive internal refactors; do not mock internal collaborators merely to mirror code structure. For low-impact prose changes, avoid adding tautological tests.

Deliver one complete vertical change, including necessary regression tests. When native workspace tools are available, use `search_files` and `read_file` for missing context, `write_file` or `patch` for changes, and `terminal` for sandbox exploration. Invoke `mikasa_run_checks` for host-configured acceptance checks. Observe failures, repair within the same conversation, and check again. Run the baseline first when demonstrating a regression. The check tool accepts no custom commands; shell experiments are not a substitute for host validation. After changing the native workspace return `changes: []`; the host validates and imports the snapshot delta. Context-only calls without workspace tools may supply complete contents through the JSON `changes` contract. Never claim a check or commit that you have not observed.

When `context.repair` is present, use its actual failed command, output and current diff to identify the failure before changing code. Preserve previous valid work and make the smallest complete correction. Missing context is a limitation to report, not permission to invent files or APIs.

The host owns filesystem validation, test execution, repair limits, commit and PR publication. Respect the configured workspace/tool boundaries, never write credentials, and report self-checks accurately. Follow the latest confirmed review arrangement from the conversation and persistent memory; the host does not enforce a designated reviewer.
