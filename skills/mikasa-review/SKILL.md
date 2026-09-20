---
name: mikasa-review
description: Review a supplied PR snapshot against its requirements and baseline engineering standards, reporting actionable findings with evidence.
---

Adapted from mattpocock/skills `code-review`; source and adaptation are recorded in [SOURCES.md](../SOURCES.md).

Evaluate two distinct axes: whether the changed behavior meets the originating requirement, and whether the implementation respects the repository's baseline standards. Passing one axis does not imply the other passed. Use `context.base`, `context.head`, `baseline_rules`, `diff`, and actual CI evidence; proposed rule changes cannot authorize themselves.

In `basis`, identify the requirement and baseline rule sources. In `findings`, give each real issue's file or behavior, trigger, impact, and verifiable repair condition; label the axis as “需求” or “工程规范”. Keep stylistic heuristics separate from blocking defects. Missing requirements or unread changed files go into `limitations` and cannot justify confident approval.

If a concrete bug violates acceptance, return `CHANGES_REQUESTED` even when CI is green. If key evidence is missing, return `INCOMPLETE`. Mikasa-authored work is self-check only and requires the owner's approval; a changed author account or a delegated worker does not make the review independent.

Return the supplied JSON contract. Both axes are evaluated within this bounded worker call; this adaptation does not spawn agents or publish reviews. The host validates provenance and current revisions before any external action.

When workspace tools are available, actively list, search and read relevant files missing from the initial snapshot. These tools are read-only; review reads the pinned PR head, while baseline_rules remain the authority. Report inaccessible or oversized files as limitations.
