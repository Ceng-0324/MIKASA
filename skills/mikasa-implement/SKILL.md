---
name: mikasa-implement
description: Produce verifiable code changes and repair failed checks in Mikasa's isolated implementation worker.
---

Adapted from mattpocock/skills `tdd` and `implement`; source and adaptation are recorded in [SOURCES.md](../SOURCES.md).

Use the public behavior and acceptance criteria as the test seam. Choose independent expected values from the requirement, not by recomputing the same implementation. Favor behavior tests that survive internal refactors; do not mock internal collaborators merely to mirror code structure. For low-impact prose changes, avoid adding tautological tests.

Return one complete vertical change through the supplied JSON `changes` contract. Include necessary regression tests with the implementation. The host executes checks; this generation step cannot claim a red/green run, a passing test, or a commit that it has not observed.

When `context.repair` is present, use its actual failed command, output and current diff to identify the failure before changing code. Preserve previous valid work and make the smallest complete correction. Missing context is a limitation to report, not permission to invent files or APIs.

The host owns filesystem validation, test execution, repair limits, commit and PR publication. Never write approval rules, credentials or tool configuration, and never claim independent approval of your own output.
