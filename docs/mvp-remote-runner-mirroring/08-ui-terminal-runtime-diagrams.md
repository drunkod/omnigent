# 08 — Reconnect-Safe Terminal Runtime Diagrams

Status reviewed on 2026-07-17 against PR #3,
`feat/mvp-terminal-mirroring`, stacked on PR #2. These diagrams describe the
implemented browser, server, runner-tunnel, and tmux paths. They replace the
older planned T07 module map.

## 1. Runtime ownership

```mermaid
flowchart TB
    subgraph surfaces["User-visible terminal surfaces"]
        MAIN["MainTerminalView.tsx<br/>terminal-first main surface"]
        RAIL["TerminalsPanel.tsx<br/>Shells rail"]
        BADGE["RunnerStatusBadge.tsx<br/>online / offline / reconnecting"]
    end

    subgraph selection["Inventory and selection"]
        TERMS["useTerminals<br/>HTTP inventory + query cache"]
        SPLIT["useTerminalSplit<br/>rail inventory and selection"]
        PERSIST["usePersistentActiveKey<br/>sessionStorage per conversation + surface"]
        RETAIN["useRetainedActiveTerminal<br/>selected exited-terminal tombstone"]
        STATUS["useTerminalStatuses<br/>resource + live bridge status"]
    end

    subgraph lifecycle["SSE lifecycle state"]
        SSE["session event stream<br/>runner_state + terminal_state"]
        STORE["terminalLifecycleStore<br/>runner state + terminal state by id<br/>30 s browser settle watchdog"]
    end

    subgraph bridge["Selected terminal bridge"]
        VIEW["TerminalView.tsx<br/>React lifecycle, retry policy,<br/>one control-to-PTY fallback"]
        SESSION["TerminalSession.ts<br/>xterm + WebSocket + binary I/O"]
        XTERM["@xterm/xterm<br/>FitAddon · WebLinksAddon · WebGL fallback"]
    end

    subgraph server["Remote server"]
        SNAPSHOT["runner-state snapshot replay<br/>stable offline, bounded reconnect"]
        STATE_REG["_runner_state_registry.py<br/>26 s server settle marker"]
        ATTACH["terminal_attach.py<br/>authorization + runner proxy"]
        TUNNEL["_runner_ws_tunnel.py<br/>multiplexed ws.* channels"]
        REG["TunnelRegistry<br/>newest runner generation"]
    end

    subgraph runner["Local runner"]
        RUNNER_ATTACH["resource-addressed attach route"]
        TREG["TerminalRegistry"]
        TMUX["tmux control / PTY bridge"]
    end

    MAIN --> PERSIST
    RAIL --> SPLIT
    SPLIT --> PERSIST
    SPLIT --> TERMS
    SPLIT --> RETAIN
    SPLIT --> STATUS
    MAIN --> RETAIN

    SSE --> STORE
    SNAPSHOT --> SSE
    STATE_REG --> SNAPSHOT
    STORE --> BADGE
    STORE --> VIEW
    RETAIN --> MAIN
    RETAIN --> RAIL

    MAIN --> VIEW
    RAIL --> VIEW
    VIEW --> SESSION
    SESSION --> XTERM
    SESSION <-->|"binary frames + resize JSON"| ATTACH
    ATTACH <-->|"multiplexed WebSocket channel"| TUNNEL
    TUNNEL --> REG
    REG <-->|"current runner generation"| RUNNER_ATTACH
    RUNNER_ATTACH --> TREG
    TREG --> TMUX
```

Only the selected terminal opens a live attach WebSocket. Unselected terminal
rows derive status from resource/lifecycle state instead of creating fan-out
tmux attaches.

## 2. Public attach and byte path

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant Surface as Main / Shells rail
    participant View as TerminalView
    participant Bridge as TerminalSession
    participant Server as Public attach route
    participant Tunnel as Runner tunnel
    participant Runner as Runner attach route
    participant Tmux as tmux pane

    Surface->>View: sessionId, terminalId, transport, readOnly
    View->>Bridge: construct one xterm/WebSocket bridge
    Bridge->>Server: WS /v1/sessions/:id/resources/terminals/:terminal_id/attach
    Server->>Server: require owner for interactive attach<br/>or read access for read_only
    Server->>Tunnel: ws.open + selected transport
    Tunnel->>Runner: resource-addressed attach
    Runner->>Tmux: control bridge or PTY attach

    Tmux-->>Runner: terminal bytes
    Runner-->>Tunnel: ws.frame
    Tunnel-->>Server: proxied binary frame
    Server-->>Bridge: binary frame
    Bridge->>Bridge: xterm.write(Uint8Array)

    User->>Bridge: keyboard / paste
    Bridge->>Server: raw binary input
    Server->>Runner: tunneled binary input
    Runner->>Tmux: send input

    Bridge->>Server: JSON resize {cols, rows}
    Server->>Runner: tunneled control frame
    Runner->>Tmux: resize pane
```

Control transport seeds the xterm buffer from tmux capture and then streams
output. PTY remains a fallback path; product-level PTY parity is still an open
decision.

## 3. Runner loss and bounded reconciliation

```mermaid
sequenceDiagram
    autonumber
    participant Tmux
    participant Runner
    participant Registry as TunnelRegistry
    participant State as Server runner-state registry
    participant SSE as Session stream
    participant Store as Browser lifecycle store
    participant View as TerminalView

    Note over Tmux,View: Stable connected terminal
    Tmux-->>View: terminal I/O through runner tunnel

    Runner-xRegistry: tunnel generation disconnects
    Registry->>State: record runner_offline
    State->>SSE: session.runner_state runner_offline
    Registry-->>View: attach closes as 4503
    SSE-->>Store: runner_offline
    Store->>View: disable input; preserve terminal/session selection

    Runner->>Registry: reconnect same runner_id with new generation
    Registry->>State: record runner_reconnected
    State->>State: schedule 26 s bounded completion
    State->>SSE: session.runner_state runner_reconnected
    SSE-->>Store: clear stale per-terminal lifecycle map<br/>start 30 s browser watchdog
    Store->>View: force one fresh-generation reattach

    Registry->>Runner: reconcile terminal resources (bounded server path)
    alt live terminals re-emitted
        Runner-->>SSE: session.terminal_state terminal_running
        SSE-->>Store: terminal state ends reconciliation
        View->>Registry: fresh attach opens
        View->>Store: confirmRunnerAttached
    else zero terminals
        Registry->>State: complete_reconciliation(terminal_count=0)
        State->>SSE: compatibility terminal_unknown marker
        SSE-->>Store: end reconciliation
    else reconcile event is lost / fails / times out
        State->>SSE: 26 s terminal_unknown completion marker
        SSE-->>Store: end reconciliation
        opt server marker also missed
            Store->>Store: 30 s settleReconciliation
        end
    end

    Note over State,Store: Every completion path rechecks current state.<br/>A newer runner_offline edge is not overwritten.
```

`runner_offline` is stable and replayable. `runner_reconnected` is a transient
edge: server replay expires after 30 seconds and both server and browser have
bounded ways to leave reconciliation.

## 4. Browser and server lifecycle state model

```mermaid
stateDiagram-v2
    [*] --> online

    online --> runner_offline: runner tunnel lost / attach 4503
    runner_offline --> runner_reconnected: same runner_id registers new generation
    runner_reconnected --> online: terminal_state event
    runner_reconnected --> online: fresh attach confirmed
    runner_reconnected --> online: zero-terminal completion marker
    runner_reconnected --> online: server/browser settle deadline
    runner_reconnected --> runner_offline: newer tunnel loss

    state terminal_lifecycle {
        [*] --> terminal_unknown
        terminal_unknown --> terminal_starting
        terminal_starting --> terminal_running
        terminal_starting --> terminal_failed
        terminal_running --> terminal_detached
        terminal_detached --> terminal_running
        terminal_running --> terminal_exited
        terminal_running --> terminal_relaunching
        terminal_relaunching --> terminal_running
        terminal_relaunching --> terminal_failed
    }

    note right of runner_offline
        Session binding, xterm buffer,
        and persisted active keys survive.
        Input and New shell remain disabled.
    end note

    note right of runner_reconnected
        One fresh attach is required before
        a connected bridge confirms recovery.
    end note
```

Runner state and individual terminal state are separate. A runner outage does
not rewrite every terminal as exited, and a terminal exit does not imply the
runner is offline.

## 5. Attach close-code and retry behavior

```mermaid
flowchart TB
    CLOSE["attach closes"] --> CODE{"close code / close class"}

    CODE -->|"4503"| OFFLINE["runner_offline<br/>preserve session + wait for runner"]
    CODE -->|"4404"| EXITED["terminal_exited<br/>retain selected tombstone"]
    CODE -->|"4405"| DETACHED["terminal_detached<br/>manual attach/resume allowed"]
    CODE -->|"4406 while control"| FALLBACK["retry once with PTY"]
    FALLBACK -->|"second unsupported close"| STOP["closed overlay; no fallback loop"]
    CODE -->|"unexpected 1001/1006/1012/1013"| BACKOFF["automatic redial<br/>0.5, 1, 2, 4, 8 s"]
    BACKOFF -->|"visible tab or timer"| REDIAL["dispose old bridge + fresh attach"]
    CODE -->|"other deliberate/app close"| CLOSED["closed/resume overlay"]
```

The retry budget resets only after a connection remains stable for 30 seconds,
which prevents both permanent exhaustion across unrelated outages and an
infinite connect/drop loop.

## 6. Independent selection and exited-terminal retention

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant Main as MainTerminalView
    participant Rail as TerminalsPanel
    participant Storage as sessionStorage
    participant Inventory as useTerminals
    participant Retain as useRetainedActiveTerminal
    participant Lifecycle as terminalLifecycleStore

    User->>Main: select terminal A
    Main->>Storage: set omnigent.activeTerminalKey.&lt;conversation&gt;.main = A

    User->>Rail: select terminal B
    Rail->>Storage: set omnigent.activeTerminalKey.&lt;conversation&gt;.rail = B
    Note over Main,Rail: Main and rail selections do not overwrite each other

    Inventory-->>Rail: transient empty inventory while runner offline
    Rail->>Storage: keep B because runner state is not authoritative online

    Lifecycle-->>Retain: terminal B = terminal_exited
    Inventory-->>Retain: B removed from runnable inventory
    Retain-->>Rail: last selected B retained as exited tombstone
    Note over Rail: Other live terminal rows remain selectable and usable

    Inventory-->>Rail: authoritative online inventory excludes stale key
    alt no exited tombstone
        Rail->>Storage: prune stale selection
    else exited tombstone
        Rail->>Storage: retain key long enough to show terminal-exited state
    end
```

Persistence is best-effort and scoped to the browser session, conversation, and
surface. It is not server-side terminal ownership.

## 7. Executable acceptance boundary

```mermaid
flowchart LR
    CLIENT["authenticated WebSocket client"] --> PUBLIC["public terminal attach route"]
    PUBLIC --> MUX["server-to-runner multiplexed tunnel"]
    MUX --> RUNNER["runner attach route"]
    RUNNER --> TMUX["real tmux pane"]

    TESTS["tests/terminal_e2e"] -. validates .-> CLIENT
    TESTS -. "input, resize, UTF-8, control bytes,<br/>Ctrl-C, alternate screen, rapid output" .-> TMUX
    TESTS -. "offline vs exit, reconnect,<br/>stale generation, permissions" .-> MUX
    CI["Terminal E2E workflow"] --> TESTS
```

Still outside the live boundary:

- a literal browser page reload with SSE bootstrap while offline, followed by
  automatic recovery;
- PTY byte-parity CI, only if PTY remains a supported product contract;
- final human evidence for current-head automatic reconnect and the distinct
  exited-terminal presentation.
