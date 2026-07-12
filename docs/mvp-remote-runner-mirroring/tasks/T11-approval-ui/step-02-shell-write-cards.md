# T11 Step 02 — Shell and write approval cards

## Goal

Render informed, accessible approval cards for runner-local shell and write
actions using only the typed payload frozen in step 01.

The card must explain what the owner is approving without implying a stronger
security guarantee than the runner actually provides.

## Prerequisite

Complete `step-01-typed-approval-payload.md`. Do not parse local-action detail
from `content_preview`, audit history, or free-form messages.

## Shared card requirements

Show:

- action title and semantic description;
- runner/workspace display label when present;
- policy mode;
- risk flags as text, not color alone;
- the bounded action-specific preview;
- Approve and Reject buttons using the existing session-scoped resolution path.

Do not show:

- absolute runner filesystem paths;
- raw transport JSON;
- unbounded command/file content;
- persisted audit entities;
- `apply_patch`.

A missing optional field must degrade to a conservative generic explanation,
not a guessed value.

## Shell card

### Content

Show:

- workspace label;
- workspace-relative cwd when supplied;
- bounded redacted command preview when supplied;
- policy mode and risk flags;
- one explicit isolation statement derived from `shellGuarantee`.

### Required guarantee copy

For `strict_workspace`:

> Strict workspace sandbox: only the selected workspace is writable and the
> runner denies network and additional mounts by default.

For `trusted_machine`:

> Trusted-machine shell: the selected workspace sets the starting directory,
> but an approved command runs with the runner user's normal machine access.

For a missing or unknown guarantee, use the conservative fallback:

> Shell isolation was not reported. Treat this approval as trusted-machine
> access and review the command before continuing.

Never say that approval itself confines the command to the workspace.

### Preview behavior

- Render `commandPreview` in an accessible horizontally/vertically scrollable
  code region.
- Do not synthesize a preview from `message`, `command_summary` history, or raw
  `contentPreview`.
- Show a visible “preview unavailable” note when the runner omitted it.
- Include a copy control only for the already-bounded/redacted preview.

## Write card

### Content

Show:

- one or more workspace-relative path summaries;
- created/modified state when the typed payload provides it;
- bounded unified diff preview;
- an explicit truncation indicator when `diffTruncated=true`;
- the stale-review warning below.

### Required stale-review copy

> The write is checked again immediately before execution. If the target
> changes while this approval is pending, the write will fail and require a new
> review.

The warning describes the server/runner conflict contract. It must not imply
that the browser performs the race check.

### Diff behavior

- Use a monospace, accessible scrolling region.
- Preserve unified-diff whitespace.
- Never execute, highlight as HTML, or otherwise interpret diff contents.
- Show “Diff preview unavailable” when omitted.
- Do not fetch the current file from the browser to reconstruct a missing diff.

## Apply-patch boundary

`apply_patch` must remain absent from:

- the typed UI union;
- SSE parsing;
- card title maps;
- action discovery;
- component fixtures.

Add it only after the backend action has bounded preview, conflict detection,
owner-only resolution, and at-most-once execution.

## Accessibility

- Use a semantic heading for the action.
- Keep Approve and Reject keyboard reachable in predictable order.
- Associate guarantee/risk text with the card description.
- Preserve focus after resolution; do not move focus to a removed card without
  a stable fallback target.
- Do not use color as the only risk or status signal.
- Give long preview regions an accessible label.

## Component structure

Prefer a small adapter and dedicated renderers rather than expanding every
branch in `ApprovalCard.tsx`:

- `LocalActionApprovalCard` chooses by typed kind;
- `ShellApprovalDetails` renders shell fields and guarantee;
- `WriteApprovalDetails` renders path/diff/conflict warning;
- generic `ApprovalCard` continues to own submission/responded state.

This keeps the existing AskUserQuestion, ExitPlanMode, and Codex command paths
isolated from runner-local action changes.

## Tests

- strict shell renders the strict guarantee and never trusted copy;
- trusted shell renders the user-level access warning;
- unknown guarantee renders the conservative fallback;
- secret text absent from the typed preview never appears via message or raw
  content preview;
- write renders relative paths, unified diff, and stale-review warning;
- truncated diff renders a visible truncation indicator;
- missing previews render conservative placeholders;
- `apply_patch` produces no specialized local-action card;
- buttons remain keyboard reachable and call the existing submit handler once.

## Done when

- shell and write cards use only step-01 fields;
- guarantee copy matches T10 exactly;
- no raw local paths or unbounded producer content render;
- `apply_patch` remains hidden; and
- component/accessibility tests cover every guarantee and preview state.
