# T11 — Local-action approval UI and E2E

## Status

Active planning. The implementation is split into three strict slices so the
wire contract, rendering, and side-effect proof do not redesign one another:

1. [`T11-approval-ui/step-01-typed-approval-payload.md`](T11-approval-ui/step-01-typed-approval-payload.md)
2. [`T11-approval-ui/step-02-shell-write-cards.md`](T11-approval-ui/step-02-shell-write-cards.md)
3. [`T11-approval-ui/step-03-resolution-side-effect-e2e.md`](T11-approval-ui/step-03-resolution-side-effect-e2e.md)

T11 is a Stage 2 product track. It starts after T10 step 02 freezes shell behavior and
T10 step 03 freezes the live/persisted audit schemas. It can run in parallel with T09
runner UX and T12 terminal parity.

## Goal

An owner can understand a pending local action, approve or deny it once, and see the
result without exposing secrets. Collaborators may observe the prompt but cannot
resolve it. Denial must leave local state unchanged.

## Contract prerequisites

The live approval event must have a typed, bounded shape separate from the persisted
audit record. It may contain the minimum transient detail required for informed
consent, for example:

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

Do not reuse the open-ended audit entity as the UI contract. Do not persist command or
diff previews merely because the card renders them. `apply_patch` is deliberately
absent until its backend action and race guarantees exist.

## Step 01 — Approval payload and state adapter

Detailed contract: [`step-01-typed-approval-payload.md`](T11-approval-ui/step-01-typed-approval-payload.md).

- Emit one nested, versioned, bounded `local_action` payload.
- Normalize live and pending-snapshot events into one store keyed by
  `elicitationId`, with `actionId` as a consistency check.
- Deduplicate replayed snapshot and live events.
- Resolve/remove the card on approved, denied, cancelled, expired, runner-offline, or
  terminal-resolved events.
- Keep the action pending while a collaborator receives 403.
- Reconstruct pending cards after refresh only from the safe typed detail.

Tests:

- duplicate event produces one card;
- wrong-session event is ignored;
- collaborator failure does not clear the card;
- terminal-side resolution clears it;
- refresh does not resurrect a completed prompt;
- malformed/oversized fields cannot recover raw producer content.

## Step 02 — Cards and safe previews

Detailed UI contract: [`step-02-shell-write-cards.md`](T11-approval-ui/step-02-shell-write-cards.md).

### Shell card

Show:

- runner/workspace display label;
- policy mode and risk flags;
- bounded redacted command preview only when T10 permits it;
- the selected shell guarantee:
  - strict workspace sandbox; or
  - trusted-machine user-level shell access.

Never claim that approval confines an unrestricted shell command.

### Write card

Show:

- relative path summary;
- created/modified state when available;
- bounded unified diff preview;
- truncation indicator;
- warning that a changed file causes conflict and fresh review.

### Apply-patch card

Do not render or advertise this action until the backend action exists and has the same
preview/race guarantees. Reuse the write card only after that contract lands.

Accessibility:

- semantic heading and action description;
- keyboard-reachable approve/deny;
- focus remains predictable when a card resolves;
- color is not the only risk signal;
- long previews use accessible scrolling and copy controls.

## Step 03 — Resolution flow and E2E

Detailed side-effect suite: [`step-03-resolution-side-effect-e2e.md`](T11-approval-ui/step-03-resolution-side-effect-e2e.md).

Use the existing session-scoped approval endpoint/event path. The server remains
authoritative for ownership and action state.

Required E2E cases with a real/fake runner capable of asserting side effects:

1. owner approves write → reviewed content is written once;
2. owner denies write → file is unchanged;
3. collaborator attempts approval → 403 and action remains pending;
4. owner denies shell → command never starts;
5. target changes while approval is pending → conflict, no stale write;
6. runner disconnects while pending → documented unavailable/retry behavior;
7. secret-bearing command/diff fixture → UI and persisted history follow T10 secrecy
   rules;
8. double-click/replayed approval → action executes at most once.

## First implementation commit scope

Keep the initial code change narrow and reviewable:

- runner producer: `omnigent/runner/app.py`, `omnigent/runner/local_actions.py`;
- server wire/snapshot validation: `omnigent/server/schemas.py` and the sessions
  elicitation path;
- web adapter: `web/src/lib/sse.ts`, `events.ts`, `blocks.ts`,
  `blockStream.ts`, and `renderItems.ts`;
- focused parser/reducer/schema tests.

Do not include visual card work in that first commit. Step 02 starts only after the
payload tests prove the live/snapshot shape and secrecy boundary.

## Done when

- the card renders only typed bounded fields;
- owner/collaborator behavior is verified end to end;
- denial and conflict prove no side effect occurred;
- live previews are not copied into persisted history;
- shell copy matches T10 step 02 exactly;
- replay/double-click proves at-most-once execution; and
- `apply_patch` remains absent until its backend contract is real.
