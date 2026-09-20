---
name: mikasa-plan
description: Break an authorized requirement into independently verifiable vertical tasks with explicit dependency indices for Mikasa's plan worker.
---

Adapted from mattpocock/skills `to-tickets`; source and adaptation are recorded in [SOURCES.md](../SOURCES.md).

Start from the supplied acceptance criteria, code snapshot and project rules. Each task should deliver one complete observable behavior across its necessary layers and include an independently checkable acceptance condition. Avoid separate “all database”, “all backend”, “all frontend” tasks that cannot demonstrate a working behavior.

Declare only real blocking edges. `depends_on` contains zero-based indices of earlier tasks, not ticket numbers, strings or guessed external IDs. Tasks without dependencies can start independently. Internal migrations should update affected callers together when that is the smallest complete change; do not introduce compatibility layers solely to force a split.

Return the worker's JSON `output_contract`. Record missing product decisions in `summary`; do not invent an answer. This worker drafts a plan; the host owns confirmation, dispatch and tracker publication. Do not call another skill, create an Issue, or claim a task was assigned.
