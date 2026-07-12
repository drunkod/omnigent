# Remote AI Terminal Runner with Local Machine Mirroring — MVP Planning

Status: implementation in progress. Originally a planning-only branch; it now
carries runtime changes across runner, server (including a DB migration),
policies, CLI, web UI, and tests. Review accordingly. The checklist in
`05-implementation-checklist.md` is the source of truth for per-item status.

## Purpose

This MVP turns Omnigent into a split-execution product for lawful self-hosted remote/local development workflows:

- The AI terminal or native coding harness runs in a supported remote/server environment.
- The user's chosen project workspace and OS tools can remain on a trusted local machine through a permissioned runner.
- The browser/desktop UI shows one coherent terminal/chat/files experience.
- The terminal display must preserve native behavior as closely as possible, instead of approximating a fake terminal.

This plan intentionally avoids designing for restriction evasion or provider-policy circumvention. Product language, docs, telemetry, and defaults should describe legitimate use cases: remote development, device mobility, self-hosting, enterprise network boundaries, local hardware reuse, cloud/local switching, compliance controls, and session continuity.

## Research summary

The user research describes two product modes:

1. **Local-hardware mode** — keep the codebase and command execution on the user's machine while the remote server coordinates AI terminal sessions and UI streaming.
2. **Cloud-execution mode** — later provision managed sandboxes/VMs for users who want server-side compute instead of using local hardware.

For the MVP, prioritize local-hardware mode because it should reuse Omnigent's existing runner tunnel, session binding, resource registry, terminal bridge, and permission systems.

## Existing Omnigent fit

Omnigent is already close to this architecture:

- It is a meta-harness over Claude Code, Codex, Cursor, OpenCode, Hermes, Pi, and custom agents.
- It already has device-synced sessions and real-time collaboration concepts.
- It already supports cloud sandboxes and managed hosts.
- It already has policy-driven governance and approval flows.
- It already includes a runner, WebSocket tunnel transport, runner routing, terminal registry, tmux PTY bridge, tmux control-mode bridge, and web terminal attach routes.

The MVP should therefore be implemented as a focused productization layer around the existing server/runner/terminal/resource machinery, not as a new parallel runtime.

## MVP success criteria

The MVP is successful when a user can:

- Register/connect a local runner to a remote Omnigent server.
- Select a local workspace exposed by that runner.
- Start a supported native AI terminal session bound to that runner and workspace.
- See terminal output in the web/desktop UI in real time.
- Send input through the UI and preserve native terminal behavior.
- Let the agent read/edit files and run commands only inside allowed workspace boundaries.
- Review diffs, shell commands, and risky actions before they execute.
- Reconnect after network loss without losing the session's runner binding or terminal attachability.

## Non-goals for the first implementation PRs

Do not implement these in the MVP branch unless a later planning review explicitly expands scope:

- Full enterprise billing.
- Multi-tenant sandbox marketplace.
- Mobile-specific UI.
- New LLM provider routing system.
- New terminal emulator protocol.
- Full cloud IDE replacement.
- Bypassing provider geofencing, sanctions, account enforcement, or terms of service.

## Planning files in this directory

- `01-codebase-map.md` — existing files/modules that should be touched or reused.
- `02-server-runner-work-plan.md` — backend, runner, host, session, workspace, and tunnel tasks.
- `03-terminal-mirroring-ui-plan.md` — terminal parity, xterm attach, session UI, reconnect, and diff UI tasks.
- `04-permissions-security-tests.md` — approval model, safety boundaries, tests, telemetry, and rollout gates.
- `05-implementation-checklist.md` — execution checklist and suggested PR sequence.
- `06-architecture-diagrams.md` — mermaid diagrams: full system architecture, pairing /
  session-create / mirroring sequences, local-action approval flow, terminal lifecycle
  states, tunnel frame protocol.
- `07-ui-ux-codebase-files.md` — mermaid mapping of every MVP UX surface (picker, badge,
  terminal panel, approval cards) to its frontend/server/runner implementation files.
- `08-ui-terminal-runtime-diagrams.md` — mermaid diagrams of the terminal UI runtime:
  attach transport selection, lifecycle store, overlay precedence.
- `09-remaining-work-tracks.md` — post-T07 remaining work as three parallel tracks
  (permissions, runner UX, lifecycle polish) with dependency ordering and solo order.

## Detailed task specs with example code

The `tasks/` directory turns the plans above into implementation-ready specs. Each file
is grounded in the actual code (verified module paths, class/function signatures, and
existing error codes) and carries full example code plus test suites.

Important: the embedded code blocks are **implementation sketches**, not copy-paste
patches. Before landing production code, re-verify current signatures, routing helpers,
and security assumptions against the live branch:

- `tasks/T01-hello-capabilities.md` — optional `HelloFrame` capability fields, lenient
  decode, capability exposure on `/v1/runners`, version-skew tests. (Checklist P2; first PR.)
- `tasks/T02-runner-workspaces.md` — `omnigent/runner/workspaces.py`: approved roots,
  stable ids, symlink/traversal escape blocking, list/validate endpoints. (P4.)
- `tasks/T03-cli-pairing.md` — extend `omnigent host` with `--workspace`,
  `add-workspace`/`remove-workspace`, status readiness output. (P3.)
- `tasks/T04-session-binding.md` — `runner_id`/`workspace_id` on session create,
  ownership/capability validation, structured error codes, fork/resume rules. (P5.)
- `tasks/T05-local-actions-gateway.md` — `workspace_policy.py` risk classification +
  `local_actions.py` gateway with approvals, diff previews, audit records. (P7.)
- `tasks/T06-reconnect-lifecycle.md` — `TerminalUiState` vocabulary, runner
  connect/disconnect fan-out, attach close-code contract, terminal reconciliation. (P10 states.)
- `tasks/T07-terminal-mirroring-ui.md` — runner badge, workspace picker, transport
  default + reconnect overlay on the existing `TerminalSession.ts`, approval cards. (P9.)
- `tasks/T08-permissions-policies-tests.md` — policy presets, owner-only approvals,
  audit persistence/redaction, telemetry names, permission test suite, rollout gates. (P8/P11.)
- `tasks/T10-canonical-contract/` — sequential blockers for the public runner/workspace
  contract, shell security guarantee, audit schema, and capability truthfulness.

Implementation order is now: T01 → T02+T03 → T04 → T06 → T05 → T08 → T10 (steps
01–04) → T11/T09/T12 parallel tracks → release docs and CI gates.

## Suggested implementation shape

Use a sequence of small PRs after this planning branch:

1. Add product flags/config models for remote-local mode.
2. Add runner registration and workspace advertisement UX/API.
3. Add session creation flow that binds a native terminal session to a selected runner/workspace.
4. Harden local file/shell dispatch behind permission policies.
5. Add terminal parity/reconnect tests.
6. Add UI settings, status panels, and acceptance test coverage.
