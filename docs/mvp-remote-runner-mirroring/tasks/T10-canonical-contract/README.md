# T10 — Stage 1 blockers: canonical contracts

Outcome of the full-branch security review at `8b1c9493`. These four steps
are **sequential** and gate all remaining UI/E2E work — every later track
builds on the contracts frozen here.

Verified ground truth (do not re-derive):

- `SessionCreateRequest` (schemas.py ~L1311) speaks `host_id` + raw
  `workspace` path + `local_runner_policy`. No `runner_id`/`workspace_id`.
- `omnigent/server/session_binding.py` already implements and unit-tests
  `validate_local_runner_binding`, `merge_local_runner_labels`,
  `advertised_workspace_ids/label` — with **zero production callers**.
- `run_shell` (local_actions.py ~L322) resolves only `cwd`; the approved
  command runs via `create_subprocess_shell` with full user-level access.
- `AuditRecord.command_summary = command[:400]` persists through a
  `ConfigDict(extra="allow")` entity; the sanitizer drops only five exact
  keys (`content`, `diff_preview`, `stdout`, `stderr`, `token`).
- `DEFAULT_TOOL_CAPABILITIES` advertises `search_files`/`git_status`/
  `git_diff`, which are served by the environment-filesystem routes, not
  the audited `LocalActionGateway`.

## Steps (strict order)

1. `step-01-canonical-session-binding.md` — wire `runner_id +
   workspace_id` through the public session API using the existing
   helpers. Everything downstream keys on this contract.
2. `step-02-shell-security-contract.md` — decide and implement the shell
   containment story (or rename the guarantee).
3. `step-03-audit-schema-freeze.md` — allowlisted audit entity,
   secret-safe summaries, TOCTOU re-resolve, write limits.
4. `step-04-capability-truthfulness.md` — gateway-served search/git or a
   trimmed advertisement.

## Explicitly out of scope here

- Multi-replica approval state: the whole elicitation registry is
  process-local by existing design. Add a single-replica support
  statement to the rollout docs (P12) instead of re-architecting now.
- Terminal parity E2E (T12) and approval UI (T11) — Stage 2, after this.
