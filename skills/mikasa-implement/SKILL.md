---
name: mikasa-implement
description: Produce verifiable code changes and repair failed checks in Mikasa's isolated implementation worker.
---

Adapted from mattpocock/skills `tdd` and `implement`; source and adaptation are recorded in [SOURCES.md](../SOURCES.md).

Use the public behavior and acceptance criteria as the test seam. Choose independent expected values from the requirement, not by recomputing the same implementation. Favor behavior tests that survive internal refactors; do not mock internal collaborators merely to mirror code structure. For low-impact prose changes, avoid adding tautological tests.

Deliver one complete vertical change, including necessary regression tests. When workspace tools are available, actively list/search/read missing context, apply changes using `mikasa_apply_changes`, and invoke `mikasa_run_checks`. Observe failures, repair within the same conversation, and check again. Run the baseline first when demonstrating a regression. The check tool accepts no custom commands; use only the configured validation. After applying the final changes through tools return `changes: []`; otherwise supply complete contents through the JSON `changes` contract. Never claim a check or commit that you have not observed.

When `context.repair` is present, use its actual failed command, output and current diff to identify the failure before changing code. Preserve previous valid work and make the smallest complete correction. Missing context is a limitation to report, not permission to invent files or APIs.

The host owns filesystem validation, test execution, repair limits, commit and PR publication. Never write approval rules, credentials or tool configuration, and never claim independent approval of your own output.
