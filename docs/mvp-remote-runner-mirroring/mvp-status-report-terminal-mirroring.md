# MVP status report — omnigent, branch `feat/mvp-terminal-mirroring` @ `a8a696bc`

Every claim below was re-verified directly against the code at the current PR #3
head (`a8a696bc`, which contains PR #2). File and line references are from that
tree. This supersedes the earlier gap analysis, which over-trusted
`docs/mvp-remote-runner-mirroring/05-implementation-checklist.md` — a document
that tracks `feat/mvp-remaining-tracks` and is now stale relative to the stacked
PR branches.

## Executive summary

The MVP's critical-path contracts (T10-01 through T10-04) are **substantially
implemented on this branch**, not open as previously reported. What remains for
the final MVP is narrower: file-write race hardening, freezing and documenting
the shell-security contract, one live browser-reload acceptance test, Stage 3
observability/documentation, and the manual evidence needed to promote PRs #2
and #3. The single most useful housekeeping task is updating the checklist
documents, which are now actively producing wrong status reports.

## Verified as delivered (with evidence)

**Canonical runner discovery — T10-01, delivered.**
`GET /v1/runners` exists and is owner-scoped
(`omnigent/server/routes/runner_tunnel.py:221`). It returns `runner_id`, online
state, harnesses, `terminal_transports`, `tool_capabilities`, and workspaces as
opaque `workspace_id` + display metadata only — the raw local root is
deliberately not copied into the response (the projection loop copies only
`display_name`, `path_label`, `capabilities`). Per-runner status hides other
users' runners as offline to prevent enumeration
(`runner_tunnel.py`, `runner_status`).

**Canonical session binding — T10-01, delivered.**
The public session routes call `validate_local_runner_binding` at two call
sites (`omnigent/server/routes/sessions.py:12389` and `:14535` — the create and
multipart-bundle paths). The earlier claim that "nothing public calls the
helper" was true of an older tree and is false at `a8a696bc`.

**Runner/workspace picker — T09 core, delivered.**
`web/src/lib/remoteRunner.ts` defines `fetchLocalRunners()` against
`/v1/runners` with typed `LocalRunnerSummary`/`RunnerWorkspace` (opaque IDs
only), consumed by the session-creation UI, which submits
`runner_id + workspace_id + local_runner_policy`. Readiness/degraded-state
richness remains open (see below), but the core canonical journey exists.

**Shell security modes — T10-02 implementation, delivered.**
`strict_shell_argv` (`omnigent/runner/local_actions.py:135`) builds a real
Bubblewrap sandbox: `--unshare-net`, read-only `/usr` `/bin` `/lib` `/lib64`,
only the resolved workspace bind-mounted writable at `/workspace`, `HOME`
pinned inside it. The approval payload truthfully reports
`shell_guarantee: "strict_workspace" | "trusted_machine"`
(`local_actions.py:434`). "Approval is the only boundary" is no longer accurate.
The remaining T10-02 work is the *decision and documentation*, not the
mechanism.

**Audit schema — T10-03, substantially delivered.**
`omnigent/server/audit_sanitizer.py` implements an explicit history allowlist
(`_HISTORY_KEYS`), value-level secret redaction (`_SECRET_RE` over bearer
tokens, `token=`/`password=`/`api_key=` shapes), forbidden payload keys
(`content`, `diff_preview`, `stdout`, `stderr`, `token`), bounded strings and
lists, and absolute-path rejection (`_is_relative_path`). Notably,
`command_summary` is persisted as **only the first token** (binary name),
redacted and capped at 80 chars — so the checklist's "remove raw command
summaries" requirement is effectively met. Wired at
`routes/sessions.py:9634` and `:10088`.

**Capability truthfulness — T10-04, substantially delivered.**
The gateway implements and advertises exactly `read_file`, `list_dir`,
`write_file`, `run_shell` (`local_actions.py`). `search_files`, `git_status`,
`git_diff`, and `apply_patch` are not on the gateway capability contract. No
"remove from advertisement" PR is needed.

**Terminal parity E2E — T12, substantially delivered on this branch.**
`tests/terminal_e2e/` spins up a real tmux pane plus runner and attaches through
the public WebSocket route. `test_control_attach.py` covers initial capture +
input round-trip, read-only collaborator authorization (observe but not drive;
interactive attach rejected), resize propagation, multiline UTF-8 paste,
byte-exact control sequences (ESC/arrows/tab/backspace), Ctrl-C interrupt,
alternate-screen enter/exit, and rapid ordered bounded output.
`test_lifecycle.py` covers close-code mapping, reconnection, duplicate-I/O
prevention, and stale-generation rejection. These run as CI gates and are green
on `a8a696bc`. The earlier claim that only unit/route-level lifecycle coverage
existed was wrong for this branch.

## Corrections to the rebuttal report

Two points in the rebuttal itself need fixing before it's circulated:

1. **`feat/mvp-remaining-tracks` does exist**, locally and on origin
   (`origin/feat/mvp-remaining-tracks`, tip `900b936a`). The rebuttal "could not
   find" it. Its T12-flavored commits (transport capability gates, acceptance
   evidence promotion) overlap PR #3's — before any new work there, reconcile or
   retire that branch explicitly so it stops feeding stale status.
2. **Command-summary handling is already stronger than "argument suppression
   remains".** The history projection keeps only the redacted first token; no
   arguments are persisted. The genuinely open audit items are the log-capture
   secrecy tests and the single-replica approval statement, not the schema.

## What genuinely remains for the final MVP

**1. File-write race hardening (top technical priority).**
Verified gap in `local_actions.py` `write_file` (~L362-410): the path is
resolved via `resolve_in_workspace` *before* the approval wait; after approval,
staleness is checked under a workspace write-lock, but the write goes through
the **previously resolved pathname** using `resolved.parent.mkdir(...)` +
`resolved.write_text(...)`. There is no final re-resolution, no `O_NOFOLLOW`
open, no dir-FD traversal, and no atomic write/rename — a symlink swapped into a
path component during the approval window can redirect the write. Also
confirmed: read/output/diff/command previews are bounded
(`_MAX_READ_BYTES`, `_MAX_OUTPUT_BYTES`, `_MAX_DIFF_PREVIEW_CHARS`,
`_MAX_COMMAND_PREVIEW_CHARS`) but **there is no maximum write-content or
request size**, and `list_dir` results are unbounded.

**2. Shell-contract freeze (decision + copy, not code).**
Pick the supported MVP default (strict-workspace where `bwrap` is available vs.
trusted-machine), document platform availability and fail-fast behavior, align
preset descriptions and approval-card copy with the actual `shell_guarantee`,
and state whether trusted-machine mode is acceptable for alpha.

**3. Browser-reload acceptance.**
The one live T12 gap per the acceptance ledger: a literal browser page reload
with SSE bootstrap while the runner is offline, then recovery — exercising the
persisted main/rail selections (now split per surface in `a8a696bc`) and the
bounded reconnect settle end-to-end. PTY-transport parity stays pending its
product decision.

**4. Stage 3 — observability and release docs (correctly reported as open).**
Structured runner connect/disconnect/reconnect logs; terminal attach transport
and close-code metrics; workspace-validation and capability-mismatch metrics; a
diagnostics projection; log-capture tests enforcing audit secrecy;
`designs/REMOTE_LOCAL_RUNNER.md` and `designs/LOCAL_RUNner_PERMISSIONS.md`
(`designs/TERMINAL_MIRRORING_ACCEPTANCE.md` already exists); user/admin/security
docs, troubleshooting, manual QA script, and CI gate mapping. Partial credit
already earned: two permission metrics, terminal E2E CI gates, and the feature
flag off by default in `/v1/info`.

**5. Remaining UX depth (T09 tail, P3/P4).**
Bounded project metadata (git summary, shells, harness readiness), the unified
readiness view, and degraded-state presentation in the picker.

**6. PR promotion (process, not code).**
Browser evidence for PR #2 (typed shell approval accepted once; typed write
approval rejected with file absent), refreshed reconnect captures on
`a8a696bc`, stale PR descriptions updated, then the agreed sequence: promote and
merge PR #2, retarget PR #3 to `mvp-v0`, re-verify the 28-file diff, promote.

**7. Harness breadth honesty.**
Codex-native plus at least one other harness have workspace-launch coverage.
There is no Gemini-native path in the tree — scope MVP claims to harnesses with
launch + reconnect coverage on the canonical binding.

## Recommended next PR

Not `feat(sessions): add canonical local-runner discovery and workspace
binding` — that would duplicate PR #2. Instead:

```
fix(local-actions): harden race-safe bounded workspace writes
```

Scope: bounded write-content/request size and `list_dir` result cap; final
re-resolution immediately before write; `O_NOFOLLOW` / dir-FD open; atomic
temp-file + rename; symlink-swap and approval-wait race regression tests; the
log-capture secrecy assertions that close the audit track.

Precede it with a documentation commit updating
`05-implementation-checklist.md` and `09-remaining-work-tracks.md` to the
post-PR-#2/#3 reality — the stale checklist is the reason two consecutive status
reports disagreed about facts that are unambiguous in the code.
