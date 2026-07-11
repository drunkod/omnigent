# T07 — Terminal lifecycle UI + attach/reconnect UX

> Split into step files: see **[T07/README.md](T07/README.md)**.
>
> Scope was re-cut to be the UI/UX consumption layer for T06's lifecycle work
> (runner offline/reconnect, terminal relaunch/exit/fail, attach close codes).
> Workspace picker (UI-2) and local-action approval/diff cards (UI-5) moved to
> [T07/step-06-deferred-scope.md](T07/step-06-deferred-scope.md).

| Step | Slice |
| --- | --- |
| [step-01](T07/step-01-terminal-lifecycle-store.md) | Terminal lifecycle store + event plumbing (`session.runner_state` / `session.terminal_state`) |
| [step-02](T07/step-02-attach-close-code-mapping.md) | Attach close-code mapping (4503/4404/4405/4406), advertised-transport selection + PTY fallback |
| [step-03](T07/step-03-reconnect-aware-terminal-panel.md) | Reconnect-aware terminal panel: buffer stability, auto-reattach, per-state overlays |
| [step-04](T07/step-04-runner-status-banner.md) | Minimal runner/session status banner |
| [step-05](T07/step-05-tests-and-manual-qa.md) | Test matrix + manual QA gate |
| [step-06](T07/step-06-deferred-scope.md) | Deferred: workspace picker, approval/diff cards, runner dashboard |

## Acceptance checklist

- [x] Lifecycle events update a per-conversation store; cross-conversation frames ignored (step-01).
- [x] Attach uses `transport=control` when advertised; `pty` fallback + one 4406 retry (step-02).
- [x] 4503/4404/4405 map to offline/exited/detached UI states, not generic failure (step-02).
- [x] Offline/reconnect keeps xterm buffer; input gated; refresh-while-offline reattaches after `terminal_running` (step-03).
- [x] Runner badge with "session is preserved" recovery copy; never implies loss (step-04).
- [x] SSE parser + store + attach-client + component tests and documented live offline/reconnect QA; Playwright deferred explicitly (step-05).
