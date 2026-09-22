---
name: mikasa-implement
description: Implement engineering changes and repair failures using observed repository behavior and meaningful verification.
---

Adapted from mattpocock/skills `tdd` and `implement`; source and adaptation are recorded in [SOURCES.md](../SOURCES.md).

Use the public behavior and acceptance criteria as the test seam. Choose independent expected values from the requirement, not by recomputing the same implementation. Favor behavior tests that survive internal refactors; do not mock internal collaborators merely to mirror code structure. For low-impact prose changes, avoid adding tautological tests.

Deliver one complete vertical change, including necessary regression tests. Read the relevant implementation before editing. Use available native tools to inspect, change and verify it; repair failures within the same conversation. Run the baseline first when demonstrating a regression. Never claim a check, commit or publication that you have not observed. If the current entry cannot execute code, discuss the implementation without pretending to have performed it.

For a repair, use the actual failed command, output and current diff to identify the cause. Preserve previous valid work and make the smallest complete correction. Missing context is a limitation to report, not permission to invent files or APIs.

Respect the current execution entry's workspace, tools and output contract. Follow confirmed collaboration arrangements from the conversation and persistent memory. Explain results in natural language unless that entry supplies a structured protocol.
