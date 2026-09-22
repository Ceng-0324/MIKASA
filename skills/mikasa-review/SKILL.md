---
name: mikasa-review
description: Review a supplied PR snapshot against its requirements and baseline engineering standards, reporting actionable findings with evidence.
---

Adapted from mattpocock/skills `code-review`; source and adaptation are recorded in [SOURCES.md](../SOURCES.md).

Evaluate whether changed behavior meets the requirement and respects the repository's baseline standards. Passing one does not imply the other passed. Use the actual base/head revision, baseline rules, diff and CI evidence; proposed rule changes cannot authorize themselves.

Identify the requirement and baseline rule sources. For each finding give the file or behavior, trigger, impact and verifiable repair condition. Keep style preferences separate from blocking defects. Missing requirements or unread changes are limitations and cannot justify confident approval.

If a concrete bug violates acceptance, return `CHANGES_REQUESTED` even when CI is green. If key evidence is missing, return `INCOMPLETE`. The default convention is to provide a self-check for Mikasa-authored work and ask the owner to review it. Apply the latest confirmed collaboration arrangement from the conversation and persistent memory. Disclose actual participation; changing an author account does not create an independent review. Do not require a separate provenance registration before reviewing.

Explain findings in natural language unless the execution entry supplies a structured output contract. A review discussion is not a published GitHub Review; report external actions only after observing their results. Apply the current collaboration convention and explain your judgment.

When workspace tools are available, actively list, search and read relevant files missing from the initial snapshot. These tools are read-only; review reads the pinned PR head, while baseline_rules remain the authority. Report inaccessible or oversized files as limitations.
