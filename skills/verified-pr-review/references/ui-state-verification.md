# UI state verification

## 1. Map acceptance to reachable states

Read the changed component, its mount point, the shared Result/API contract, production handler registration, and browser mock defaults. Trace what the current application actually returns: a missing Main handler returning NOT_IMPLEMENTED is an integration state, not hypothetical failure injection. Do not require a UI-only task to implement the entire capture backend; require honest unavailable/error presentation at that boundary.

Search the tests for the new component and its public behavior before citing suite totals as evidence. List granted-with-devices, empty devices, denied/not-determined, initial query failure, save failure, and recovery transitions when relevant. A fixed-granted mock plus host-dependent enumerateDevices does not establish deterministic permission-state coverage.

## 2. Reproduce through the real component

Start dev:web from the pinned isolated snapshot and verify readiness before opening it. Use the actual component, not a rewritten rendering model. In browser context, supply controlled API Result values and enumerateDevices results; mount a fresh component instance per scenario so initial effects run again. Keep these overrides confined to the test page, without changing shared source.

For Vite browser probes, fetch the transformed entry source and extract its actual import URLs before dynamically importing React and ReactDOM. Preserve optimizer query hashes and use the same loaded React instance as the component; hard-coded dependency URLs can become stale after a snapshot update. Import the component from its served source path and mount via createRoot. Report this as a controlled browser probe, not a test shipped by the PR or real-device validation.

## 3. Test errors and recovery, not just first render

- Return a resolved failure Result from settings or permissions and verify loading ends with safe, actionable feedback; handling only the success branch otherwise leaves completed requests looking pending forever. Separately test rejected promises where the boundary permits them.
- Fail a settings save and verify the control does not silently imply persistence; check feedback and the retained confirmed value.
- Start with no devices, then change enumeration output and dispatch devicechange or invoke the provided refresh action. Count enumeration calls and inspect rendered options to prove recovery actually occurs.
- Remove the selected device and verify stale persisted IDs are handled. Do not accept a claim that an unavailable microphone will fall back to a default unless that default's availability is established.
- Inspect permission changes and refresh/retry affordances. Suggest explicit state transitions and regression assertions, not cosmetic wording alone when the behavior remains stuck.
- For audio capture, end a real synthetic MediaStream track during awaited Worklet initialization and verify the component leaves recording state; an ended event emitted before listener installation is not replayed. Then trigger a post-start capture failure and invoke cancel using a native AudioContext: repeated close can reject, so always-successful close mocks can hide skipped Main-side discard. Synthetic sources prove browser lifecycle behavior, not OS/device capture.

## 4. Separate evidence and scope

Capture input conditions, observed DOM, event/call counts, affected revision and source lines. Distinguish static implementation tracing, real browser component execution with injected fixtures, repository tests, and OS/device testing. A browser API override cannot prove macOS/Windows permissions or successful capture. Keep missing acceptance evidence separate from reproduced behavioral defects, and avoid converting every untested platform into a blocker when the task explicitly allows mock-first UI delivery.
