# Remote AI Terminal Runner with Local Machine Mirroring — MVP Planning

Status: implementation in progress. This branch now contains runtime changes across
runner, server, policies, CLI, web UI, tests, and a DB migration. Review it as an
implementation branch, not as planning-only documentation.

`05-implementation-checklist.md` is the status source of truth. The detailed task
files contain implementation sketches and must not override the checklist when they
drift from current code.

## Purpose

This MVP productizes Omnigent's existing server/runner/terminal stack for lawful
remote/local development workflows:

- the AI harness may run remotely;
- an approved project workspace and OS tools may remain on a trusted local machine;
- the browser presents one coherent chat, terminal, and files experience;
- terminal behavior should remain native rather than being approximated by a fake
  command console;
- every local side effect follows an explicit, documented permission boundary.

The project does not target restriction evasion, geofencing bypass, sanctions
avoidance, account-policy circumvention, or provider ToS bypass.

## MVP success criteria

The MVP is successful when a user can:

- connect a local runner to a remote Omnigent server;
- select an opaque runner/workspace binding without sending a local absolute path to
  the server;
- start a supported native session bound to that runner and workspace;
- see and control the terminal through the existing attach path;
- review local writes and shell actions before execution when policy requires it;
- understand the shell security guarantee selected in T10 step 02;
- reconnect without losing the persisted runner/workspace binding;
- inspect a bounded, secret-safe audit history;
- complete the supported flow with the feature flag off by default and CI/manual QA
  gates documented.

## Current architectural decision point

Two contracts currently coexist:

1. the existing host-launch API uses `host_id` plus a raw `workspace` path; and
2. the new local-runner helpers use opaque `runner_id` plus `workspace_id`.

The local-runner product must use the second contract. T10 step 01 freezes the public
create and discovery APIs and keeps the existing host-launch path separate.

Shell approval is not equivalent to filesystem containment. T10 step 02 must either
introduce a real OS sandbox for strict workspace mode or explicitly document a
trusted-machine shell mode. No later UI or rollout task may claim stronger isolation
than the selected implementation provides.

## Planning files

- `01-codebase-map.md` — existing modules and reuse points.
- `02-server-runner-work-plan.md` — backend, runner, host, workspace, and tunnel work.
- `03-terminal-mirroring-ui-plan.md` — terminal parity and UI surfaces.
- `04-permissions-security-tests.md` — permission boundaries, tests, telemetry, and
  rollout gates.
- `05-implementation-checklist.md` — reviewed status and remaining order.
- `06-architecture-diagrams.md` — system and sequence diagrams.
- `07-ui-ux-codebase-files.md` — UX-to-code mapping.
- `08-ui-terminal-runtime-diagrams.md` — terminal runtime diagrams.
- `09-remaining-work-tracks.md` — dependency graph for work still open.

## Task packs

Implemented or substantially landed:

- `tasks/T01-hello-capabilities.md`
- `tasks/T02-runner-workspaces.md`
- `tasks/T03-cli-pairing.md`
- `tasks/T04-session-binding.md` — helper layer landed; public route wiring reopened
  under T10.
- `tasks/T05-local-actions-gateway.md` — core gateway landed; shell/audit/capability
  hardening reopened under T10.
- `tasks/T06-reconnect-lifecycle.md`
- `tasks/T06b-lifecycle-polish/`
- `tasks/T07/`
- `tasks/T08/` — presets, owner gate, persistence mechanics, and two permission
  metrics landed; audit secrecy and broader rollout gates remain open.

Remaining task packs:

- `tasks/T10-canonical-contract/` — **sequential critical path**:
  1. canonical runner/workspace discovery and session binding;
  2. shell security contract;
  3. allowlisted secret-safe audit schema;
  4. capability truthfulness and gateway convergence.
- `tasks/T09-runner-ux/` — runner/workspace picker and capability UI, after T10 step
  01 and step 04 freeze the API.
- `tasks/T11-approval-ui.md` — approval cards, diff presentation, and approval-flow
  E2E, after T10 steps 02–03.
- `tasks/T12-terminal-parity-e2e.md` — real terminal fixture and byte/lifecycle parity
  coverage; may start after T10 step 01 and run in parallel with T09/T11.

## Remaining implementation order

```text
T10-01 canonical discovery + session binding
  → T10-02 shell security decision/implementation
  → T10-03 audit schema freeze
  → T10-04 capability truthfulness
  → [T09 runner UX || T11 approval UI || T12 terminal parity E2E]
  → P11 observability completion
  → P1 final design records + P12 user/admin/security docs and CI rollout gates
```

T10 is sequential. After it is complete, T09, T11, and T12 can proceed in parallel.
Within each task pack, its listed steps remain sequential.

## Suggested remaining PR sequence

1. `feat(sessions): add canonical local-runner discovery and workspace binding`
2. `feat(runner): freeze shell security and local-action audit contracts`
3. `feat(runner): converge advertised search and git capabilities`
4. Parallel PRs for runner UX, approval UI, and terminal E2E coverage
5. `chore(observability): complete runner and terminal metrics`
6. `docs(remote-runner): add design records, operations guide, QA, and rollout gates`

Do not build the workspace picker against a raw path round-trip, and do not mark a
security item complete solely because an approval dialog exists.