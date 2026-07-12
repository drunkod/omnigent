# T11 Step 01 — Typed local-action approval payload

## Goal

Carry the minimum bounded, redacted, transient detail needed for an informed
owner decision from the runner to the web UI without widening the persisted
audit schema.

This step is the prerequisite for the shell/write cards in step 02 and the
side-effect E2E suite in step 03.

## Verified starting state

- `omnigent/runner/local_actions.py` already computes:
  - `action_id` on the in-memory `AuditRecord`;
  - `kind`, `policy_mode`, `cwd`, `path_summary`, and `risk_flags`;
  - a bounded `command_summary` for shell actions;
  - a bounded unified `diff_preview` for writes.
- `omnigent/runner/app.py::_request_local_action_approval` sends the safe
  summary fields and approval-only payload on the transient
  `mcp_elicitation` event.
- `web/src/lib/sse.ts` currently retains only `kind + policyMode` and drops
  the other typed fields before rendering.
- Persisted local-action audit records must remain preview-free.

## Wire contract

Introduce one versioned UI payload. Keep snake_case on the Python wire and
camelCase after web parsing.

```typescript
interface LocalActionApproval {
  version: 1;
  actionId?: string;
  kind: "write_file" | "run_shell";
  policyMode: "manual" | "assisted" | "auto";
  workspaceLabel?: string;
  cwd?: string;
  pathSummary: string[];
  commandPreview?: string;
  diffPreview?: string;
  diffTruncated: boolean;
  riskFlags: string[];
  shellGuarantee?: "strict_workspace" | "trusted_machine";
  expiresAt?: number;
}
```

`read_file` and `list_dir` may keep using the generic binary card until they
need extra consent detail. Do not accept or render `apply_patch`; its backend
action and race contract do not exist yet.

## Bounds and validation

Fail closed to the generic binary card when `kind` or `policyMode` is invalid.
Drop malformed optional fields independently.

- `actionId`: non-empty, at most 128 characters.
- `workspaceLabel`: at most 256 characters.
- `cwd`: workspace-relative display text, at most 512 characters.
- `pathSummary`: at most 16 strings, each at most 512 characters.
- `commandPreview`: redacted, at most 2,000 characters.
- `diffPreview`: at most 64 KiB.
- `riskFlags`: at most 16 strings, each at most 128 characters.
- `expiresAt`: finite positive epoch seconds.

The runner is authoritative for redaction and truncation. The browser validates
bounds again but must not attempt to recover dropped raw values from
`content_preview`.

## Producer changes

1. In the runner approval callback, emit a nested `local_action` object rather
   than adding more open-ended top-level extras.
2. Populate `action_id` from the in-memory record.
3. Resolve `workspace_label` from `WorkspaceRegistry` display metadata only;
   never send the absolute root.
4. Emit the selected shell guarantee explicitly from the gateway configuration.
5. Mark `diff_truncated=true` when the source preview exceeded the cap.
6. Keep command and diff previews transient. Do not copy them into
   `AuditRecord.to_event()`, conversation items, logs, or snapshot history.

## Server and web adapter changes

- Give the server SSE schema an explicit bounded `local_action` model.
- Preserve the typed object in pending-elicitation snapshots so refresh can
  reconstruct an unresolved card.
- Parse snake_case to camelCase in `web/src/lib/sse.ts`.
- Thread the same object through `events.ts`, `blocks.ts`, `blockStream.ts`, and
  `renderItems.ts` without reinterpretation.
- Deduplicate by `elicitationId`; use `actionId` as a consistency check when it
  is present.

## Tests

- valid write payload reaches the render item unchanged after normalization;
- valid shell payload carries the explicit guarantee;
- oversized arrays/strings are rejected or bounded deterministically;
- malformed optional fields are dropped without exposing `content_preview`;
- `apply_patch` is ignored;
- duplicate snapshot + live events produce one pending card;
- a secret-bearing command/diff fixture is absent from persisted history and
  audit events.

## Done when

- the UI card consumes only `LocalActionApproval` fields;
- refresh reconstructs the same safe pending card;
- previews remain live-only;
- bounds are tested at runner, server, and browser boundaries; and
- `apply_patch` cannot appear in discovery, parsing, or rendering.
