# Remote AI Terminal Runner with Local Machine Mirroring — MVP

Status: implementation and acceptance in progress.

The active implementation is split across two stacked draft pull requests:

- PR #2: canonical local-runner binding, runner/workspace UX, local actions,
  permissions, approvals, and audit persistence;
- PR #3: terminal transport parity, lifecycle, reconnect, and terminal selection state.

`05-implementation-checklist.md` is the current status source of truth for this active
stack. `09-remaining-work-tracks.md` defines the remaining dependency order. Detailed
task files are historical plans and must not override current production evidence.

The branch `feat/mvp-remaining-tracks` still exists, but it has diverged from the active
stack and is no longer the status authority. Do not merge it wholesale. Review unique
commits, cherry-pick intentional survivors, then archive or delete it.

## Purpose

This MVP productizes Omnigent's existing server/runner/terminal stack for lawful
remote/local development workflows:

- the AI harness may run remotely;
- an approved project workspace and OS tools may remain on a trusted local machine;
- the browser presents one coherent chat, terminal, and files experience;
- terminal behavior remains native rather than becoming a fake command console;
- every local side effect follows an explicit, documented permission boundary.

The project does not target restriction evasion, geofencing bypass, sanctions
avoidance, account-policy circumvention, or provider ToS bypass.

## Current delivered baseline

The active stack substantially delivers:

- owner-scoped `GET /v1/runners` discovery with opaque workspaces;
- public session creation using `runner_id + workspace_id` without a raw path;
- ownership, workspace, harness, feature-flag, and mixed-contract validation;
- persisted runner affinity and opaque execution/workspace/policy labels;
- a runner/workspace picker that submits the canonical contract;
- local read/list/write/shell actions with policy evaluation and owner approval;
- typed shell/write approval cards and exact-`action_id` outcome persistence;
- allowlisted, bounded, value-redacted audit history with no command arguments,
  file contents, output, or absolute home paths;
- strict Bubblewrap shell execution plus truthful trusted-machine labeling;
- truthful gateway capability advertisement;
- authenticated terminal attachment through the multiplexed runner tunnel;
- real tmux acceptance for resize, paste, UTF-8, control keys, Ctrl-C,
  alternate-screen behavior, rapid output, permissions, reconnect, and lifecycle;
- bounded reconnect settlement, stale-generation rejection, persisted independent
  terminal selections, and retained terminal-exited state;
- local-action and terminal E2E CI gates.

## Remaining MVP closure

The remaining work is narrower than the original T10/T09/T11/T12 plan:

1. Finish current-head browser evidence and merge PR #2, then PR #3.
2. Harden workspace writes against approval-window path races and oversized requests.
3. Freeze and document the supported/default shell guarantee and replica limitation.
4. Add log-capture secrecy tests.
5. Add a literal browser reload/SSE-bootstrap acceptance case while offline and after
   recovery.
6. Add bounded project/readiness metadata and richer degraded-state UX.
7. Complete structured reconnect/attach observability, diagnostics, design records,
   user/admin/security documentation, manual QA, and rollout gates.
8. Reconcile and retire the legacy `feat/mvp-remaining-tracks` branch.

## MVP success criteria

The MVP is successful when a user can:

- connect a local runner to a remote Omnigent server;
- select an opaque runner/workspace binding without sending a local absolute path to
  the server;
- start a supported native session bound to that runner and workspace;
- see and control the terminal through the authenticated attach path;
- review local writes and shell actions before execution when policy requires it;
- understand whether shell execution is strict-workspace or trusted-machine;
- reconnect and reload without losing the persisted binding or intended terminal;
- inspect bounded, secret-safe audit history;
- complete the supported flow with the feature flag off by default and named CI/manual
  QA gates documented.

## Planning and status files

- `01-codebase-map.md` — existing modules and reuse points.
- `02-server-runner-work-plan.md` — backend and runner plan.
- `03-terminal-mirroring-ui-plan.md` — terminal and UI surfaces.
- `04-permissions-security-tests.md` — permission boundaries and rollout gates.
- `05-implementation-checklist.md` — current evidence-backed status.
- `06-architecture-diagrams.md` — system and sequence diagrams.
- `07-ui-ux-codebase-files.md` — UX-to-code mapping.
- `08-ui-terminal-runtime-diagrams.md` — terminal runtime diagrams.
- `09-remaining-work-tracks.md` — actual remaining dependency order.
- `mvp-status-report-terminal-mirroring.md` — verified narrative status for PR #3.

## Immediate next technical PR

After the current stack is promoted and merged:

```text
fix(local-actions): harden race-safe bounded workspace writes
```

It should add write/request and directory-list limits, final secure re-resolution,
no-follow traversal/opening, atomic replacement, and symlink/approval-window race
regressions before additional local write capabilities are advertised.
