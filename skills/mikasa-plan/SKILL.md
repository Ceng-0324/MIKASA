---
name: mikasa-plan
description: Clarify engineering requirements and split authorized work into independently verifiable tasks with real dependencies.
---

Adapted from mattpocock/skills `to-tickets`; source and adaptation are recorded in [SOURCES.md](../SOURCES.md).

Start from the supplied acceptance criteria, code snapshot and project rules. Each task should deliver one complete observable behavior across its necessary layers and include an independently checkable acceptance condition. Avoid separate “all database”, “all backend”, “all frontend” tasks that cannot demonstrate a working behavior.

Declare only real blocking dependencies. Tasks without dependencies can start independently. Internal migrations should update affected callers together when that is the smallest complete change; do not introduce compatibility layers solely to force a split.

Discuss the plan in natural language unless the execution entry supplies a structured output contract. Record missing product decisions without inventing an answer. Distinguish a proposed plan from tasks actually created or assigned; do not claim an external action without its result.

When repository tools are available, inspect relevant project context before planning. Report unavailable evidence only when it affects the recommendation; a design discussion can proceed without pretending to have read a repository.
