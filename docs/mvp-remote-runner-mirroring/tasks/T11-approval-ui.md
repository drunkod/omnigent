# T11 — Local-action approval UI and E2E

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
  elicitationId: string;
  sessionId: string;
  actionId: string;
  kind: "write_file" | "run_shell" | "apply_patch";
  policyMode: "manual" | "assisted" | "auto";
  workspaceLabel: string;
  pathSummary?: string[];
  commandCategory?: string;
  commandPreview?: string; // bounded/redacted; live only
  diffPreview?: string;    // bounded; live only
  riskFlags: string[];
  expiresAt?: number;
}
```

Do not reuse the open-ended audit entity as the UI contract. Do not persist command or
diff previews merely because the card renders them.

## Step 01 — Approval state adapter

- Normalize `mcp_elicitation`/local-action events into one store keyed by
  `elicitationId` and `actionId`.
- Deduplicate replayed snapshot and live events.
- Resolve/remove the card on approved, denied, cancelled, expired, runner-offline, or
  terminal-resolved events.
- Keep the action pending while a collaborator receives 403.
- Reconstruct pending cards after refresh from the existing pending-elicitations
  snapshot only when the server includes the safe typed detail.

Tests:

- duplicate event produces one card;
- wrong-session event is ignored;
- collaborator failure does not clear the card;
- terminal-side resolution clears it;
- refresh does not resurrect a completed prompt.

## Step 02 — Cards and safe previews

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
- created/modified state;
- bounded unified diff preview;
- truncation indicator;
- warning when the file changed and the server will require a fresh approval.

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

Use the existing session-scoped approval endpoint/event path. The server remains
authoritative for ownership and action state.

Required E2E cases with a real/fake runner capable of asserting side effects:

1. owner approves write → reviewed content is written once;
2. owner denies write → file is unchanged;
3. collaborator attempts approval → 403 and action remains pending;
4. owner denies shell → command never starts;
5. target changes while approval is pending → conflict, no stale write;
6. runner disconnects while pending → card becomes unavailable/retryable according to
   the documented contract;
7. secret-bearing command/diff fixture → UI and persisted history follow T10 secrecy
   rules;
8. double-click/replayed approval → action executes at most once.

## Done when

- the card renders only typed bounded fields;
- owner/collaborator behavior is verified end to end;
- denial and conflict prove no side effect occurred;
- live previews are not copied into persisted history;
- shell copy matches T10 step 02 exactly; and
- `apply_patch` remains absent until its backend contract is real.
