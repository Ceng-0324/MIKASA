# Review record

## Scope
- PR / current head / base / target branch:
- Implementation provenance / independent-review eligibility:
- Linked Issues / baseline rules / promised PR scope / explicit exclusions:
- Publication and merge authorization / draft or policy blockers:

## Acceptance map
| Issue criterion | PR scope or deferred boundary | Implementation and callers | Required evidence | Observed evidence + SHA/platform | Status / remaining work |
|---|---|---|---|---|---|

Status: verified, partial, unmet, evidence missing. Author declaration is labeled as such, not independent verification. For each gap state whether it blocks this PR, Issue closure, or only an optional follow-up.

## Findings
For each blocking item: severity; requirement; revision/path/lines; supported trigger; actual behavior; user/data impact; evidence or code proof; repair and regression condition. Label optional suggestions separately. State narrower real impact when a caller bypasses the defective API.

## Three decisions
- Code/acceptance verdict: APPROVED / CHANGES_REQUESTED / INCOMPLETE, with reason.
- Merge eligibility: eligible / blocked / not applicable, with exact reason.
- Each Issue: complete after merge / partial / unverified, with criteria-level reason.

## Validation
- Commands / exit codes / actual result / SHA / runtime/platform:
- Direct execution vs remote CI vs author records:
- Runner duration vs command wall-clock (only when measured):
- Unperformed checks, whether required, and their effect on the decision:

## Delivery checklist
- [ ] All requested PRs and linked Issues accounted for.
- [ ] Every acceptance criterion mapped; no mandatory gap hidden in limitations.
- [ ] All changed files accounted for; decisive delegated findings checked.
- [ ] Current head checked; new commits/base changes assessed before using evidence.
- [ ] Detailed comment created and exact target read back, or explicit task-local prohibition recorded.
- [ ] Correct formal Review read back with reviewed commit, or self-review/INCOMPLETE boundary explained.
- [ ] For merge: CI, required approvals, non-draft readiness, mergeability and all thread pages checked; head matched; no protection bypass.
- [ ] Merge result and target/commit read back, or concrete non-merge reason recorded.
- [ ] Every linked Issue evaluated after merge; acceptance record + correct open/closed state read back.
- [ ] Superseded work handled without duplicate merges or unauthorized closure.
- [ ] Final response contains verified URLs/states and does not imply unfinished work is complete.

Use this as a working checklist/report, not a new approval service or permanent status database. Not-applicable entries need a short reason, not a false checkmark.
