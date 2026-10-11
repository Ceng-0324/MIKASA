# Runtime and mock verification

- Check elapsed process duration as well as test-runner results; leaked timers, sockets or children can keep a green suite alive and degrade CI.
- Run canonical fixtures through the implementation and compare independently specified expected behavior. Unused or stale fixtures cannot establish compatibility.
- Keep signal handlers in a CLI entry point, not importable server factories; verify repeated instance creation does not accumulate global handlers.
- Verify consumer integration when claimed. A mock self-test is not evidence that a real client supplies system context, handles errors or retries correctly.
- For request capture, compare exact messages/system context with original input; keyword-dependent responses cannot detect an omitted prompt. Require a usable capture/assertion path, not merely an exposed HTTP server.
- Split multibyte UTF-8 across real data events and require original captured content. Independent Buffer decoding may silently corrupt valid JSON; use stream-aware decoding or concatenate before decoding.
- Verify independent snapshots, instance isolation, order semantics and close/cleanup behavior where promised. Distinguish stopping a listener from clearing referenced in-memory data.
- Treat audio/stream startup, failure and teardown as lifecycle paths; use the UI reference for native browser races and non-idempotent close behavior.
- Pin each worktree before parallel checks; do not race branch switching against readers. Observe actual runtime and command status; separate missing dependencies/download failures from implementation failures.
