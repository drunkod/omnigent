# Step 01 — Terminal lifecycle store + event plumbing

**Commit 1 of T07.** Give the already-parsed lifecycle events somewhere to live.

## Current state

- `web/src/lib/events.ts` defines the union members (verified, ~line 455):

```typescript
export type TerminalUiState =
  | "terminal_unknown"
  | "terminal_starting"
  | "terminal_running"
  | "terminal_detached"
  | "terminal_exited"
  | "runner_offline"
  | "runner_reconnected"
  | "terminal_relaunching"
  | "terminal_failed";

export interface SessionRunnerStateEvent {
  type: "session_runner_state";
  conversationId: string;
  runnerId: string;
  state: Extract<TerminalUiState, "runner_offline" | "runner_reconnected">;
}

export interface SessionTerminalStateEvent {
  type: "session_terminal_state";
  conversationId: string;
  terminalId: string;
  state: Exclude<TerminalUiState, "runner_offline" | "runner_reconnected">;
}
```

- `web/src/lib/sse.ts` (~line 441) already validates both event shapes and drops
  malformed payloads (returns `null`).
- `web/src/store/chatStore.ts` (~line 4274) currently swallows both:

```typescript
case "session_runner_state":
case "session_terminal_state":
  // Lifecycle state is consumed by terminal/session-specific views. ...
  return;
```

## Task

### 1. New store: `web/src/store/terminalLifecycleStore.ts`

Separate store, not `chatStore` — terminal state is resource/UI state, not
transcript state. Follow the `terminalActivity.ts` zustand pattern:

```typescript
import { create } from "zustand";
import type {
  SessionRunnerStateEvent,
  SessionTerminalStateEvent,
  TerminalUiState,
} from "@/lib/events";

export type RunnerUiState =
  | "online"              // default until told otherwise
  | "runner_offline"
  | "runner_reconnected"  // transient: reconciling, terminal states incoming
  ;

export type TerminalPanelState = Exclude<
  TerminalUiState,
  "runner_offline" | "runner_reconnected"
>;

interface ConversationLifecycle {
  runnerState: RunnerUiState;
  lastRunnerId: string | null;
  lastStateAt: number;
  /** terminalId -> last reported state. Absent = terminal_unknown. */
  terminalStateById: Record<string, TerminalPanelState>;
}

interface TerminalLifecycleStore {
  byConversation: Record<string, ConversationLifecycle>;
  applyRunnerState: (e: SessionRunnerStateEvent) => void;
  applyTerminalState: (e: SessionTerminalStateEvent) => void;
  /** Drop state when a conversation's stream is torn down. */
  clearConversation: (conversationId: string) => void;
}

const EMPTY: ConversationLifecycle = {
  runnerState: "online",
  lastRunnerId: null,
  lastStateAt: 0,
  terminalStateById: {},
};

export const useTerminalLifecycleStore = create<TerminalLifecycleStore>((set) => ({
  byConversation: {},

  applyRunnerState: (e) =>
    set((s) => {
      const prev = s.byConversation[e.conversationId] ?? EMPTY;
      return {
        byConversation: {
          ...s.byConversation,
          [e.conversationId]: {
            ...prev,
            runnerState: e.state === "runner_offline" ? "runner_offline" : "runner_reconnected",
            lastRunnerId: e.runnerId,
            lastStateAt: Date.now(),
            // On reconnect the runner reconciles terminals and re-emits
            // per-terminal states; drop stale entries so panels show
            // "checking" instead of a pre-disconnect state.
            terminalStateById:
              e.state === "runner_reconnected" ? {} : prev.terminalStateById,
          },
        },
      };
    }),

  applyTerminalState: (e) =>
    set((s) => {
      const prev = s.byConversation[e.conversationId] ?? EMPTY;
      return {
        byConversation: {
          ...s.byConversation,
          [e.conversationId]: {
            ...prev,
            // First per-terminal frame after reconnect ends the
            // "reconciling" phase for the runner banner.
            runnerState: prev.runnerState === "runner_reconnected" ? "online" : prev.runnerState,
            lastStateAt: Date.now(),
            terminalStateById: { ...prev.terminalStateById, [e.terminalId]: e.state },
          },
        },
      };
    }),

  clearConversation: (conversationId) =>
    set((s) => {
      if (!(conversationId in s.byConversation)) return s;
      const next = { ...s.byConversation };
      delete next[conversationId];
      return { byConversation: next };
    }),
}));

/** Selector helpers for components. */
export function selectRunnerState(conversationId: string) {
  return (s: TerminalLifecycleStore): RunnerUiState =>
    s.byConversation[conversationId]?.runnerState ?? "online";
}

export function selectTerminalState(conversationId: string, terminalId: string) {
  return (s: TerminalLifecycleStore): TerminalPanelState =>
    s.byConversation[conversationId]?.terminalStateById[terminalId] ?? "terminal_unknown";
}
```

### 2. Forward from `chatStore.ts`

Replace the ignore-case with a forward. Keep the events in the shared stream
union so older reducers don't reject the frame:

```typescript
case "session_runner_state":
  useTerminalLifecycleStore.getState().applyRunnerState(event);
  return;
case "session_terminal_state":
  useTerminalLifecycleStore.getState().applyTerminalState(event);
  return;
```

### 3. Conversation guard

The store keys everything by `event.conversationId`, so a late frame from an
old stream cannot mutate the *active* terminal UI — components must select
with the conversation id they render, same as other chat-store session events.

Call `clearConversation` **only when the conversation is unbound permanently**
(`switchTo` / unmount / teardown) — **not** on an ordinary pump `"dropped"`
reconnect. The stream loop intentionally re-subscribes on `"dropped"` and
keeps the same `AbortController` across reconnect attempts, so a transient
SSE gap must not wipe lifecycle state or make the binding look dead.

## Acceptance

```text
runner_offline event updates UI state
runner_reconnected event updates UI state
terminal_relaunching -> terminal_running updates a specific terminal
events for another conversation are ignored (keyed, never leak cross-conversation)
malformed event payloads are ignored by parser (sse.ts already; keep a test)
```

## Tests (write in this commit — see step-05 for full matrix)

- SSE parser tests for both event types in `web/src/lib/sse.test.ts` —
  `sse.ts` itself notes parser changes need a parser test; reducer tests
  alone won't catch dropped event types.
- Store transition tests:

```typescript
// terminalLifecycleStore.test.ts
it("runner_offline sets offline banner state", () => {
  useTerminalLifecycleStore.getState().applyRunnerState({
    type: "session_runner_state", conversationId: "c1",
    runnerId: "r1", state: "runner_offline",
  });
  expect(selectRunnerState("c1")(useTerminalLifecycleStore.getState()))
    .toBe("runner_offline");
});

it("reconnect clears stale terminal states, first terminal frame ends reconciling", () => {
  const s = useTerminalLifecycleStore.getState();
  s.applyTerminalState({ type: "session_terminal_state", conversationId: "c1",
    terminalId: "t1", state: "terminal_running" });
  s.applyRunnerState({ type: "session_runner_state", conversationId: "c1",
    runnerId: "r1", state: "runner_reconnected" });
  expect(selectTerminalState("c1", "t1")(useTerminalLifecycleStore.getState()))
    .toBe("terminal_unknown");           // reconciling, not stale "running"
  s.applyTerminalState({ type: "session_terminal_state", conversationId: "c1",
    terminalId: "t1", state: "terminal_relaunching" });
  expect(selectRunnerState("c1")(useTerminalLifecycleStore.getState())).toBe("online");
});

it("other conversation untouched", () => { /* apply to c1, assert c2 defaults */ });
```

Next: [step-02 — attach close-code mapping](step-02-attach-close-code-mapping.md)
