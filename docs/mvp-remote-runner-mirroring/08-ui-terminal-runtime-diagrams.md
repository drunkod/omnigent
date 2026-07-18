# 08 — Implemented UI and Terminal Runtime Diagrams

Status reviewed on 2026-07-17 against PR #2,
`feat/mvp-runner-binding-approvals`. This file maps the UI modules and server
contracts that are actually wired on the branch. PR #3 adds the reconnect-safe
terminal lifecycle, persisted terminal selection, and live terminal acceptance
details.

## 1. UI ownership on PR #2

```mermaid
flowchart TB
    subgraph create["New-session runner binding"]
        NEWCHAT["web/src/shell/NewChatDialog.tsx<br/>NewChatLandingScreen"]
        USE_RUNNERS["web/src/hooks/useLocalRunners.ts<br/>React Query polling"]
        REMOTE["web/src/lib/remoteRunner.ts<br/>typed runner/workspace projection"]
        INFO["useServerInfo<br/>remote_local_runner feature probe"]
    end

    subgraph capability["Runner state and capability presentation"]
        HOSTCAP["web/src/components/HostCapabilityPanel.tsx<br/>runner label + capabilities"]
        BADGE["web/src/shell/RunnerStatusBadge.tsx<br/>workspace/policy + online state"]
        HEALTH["RunnerHealthProvider<br/>session runner-online polling"]
    end

    subgraph approval["Typed local-action approval"]
        NORMALIZE["web/src/lib/localActionApproval.ts<br/>normalize typed action payload"]
        CARD["web/src/components/blocks/LocalActionApprovalCard.tsx<br/>shell/write review"]
        BLOCKS["ApprovalCard + BlockRenderer<br/>conversation item rendering"]
        INBOX["InboxPage<br/>owner decision flow"]
    end

    subgraph terminal["Existing terminal surfaces"]
        MAIN["MainTerminalView.tsx<br/>terminal-first main surface"]
        RAIL["TerminalsPanel.tsx<br/>Shells rail"]
        VIEW["TerminalView.tsx<br/>React attach shell"]
        SESSION["TerminalSession.ts<br/>xterm + WebSocket bridge"]
    end

    subgraph server["Server contracts"]
        INFO_API["GET /v1/info"]
        RUNNERS_API["GET /v1/runners"]
        CREATE_API["POST /v1/sessions<br/>JSON or multipart"]
        EVENTS["session SSE stream<br/>local-action and runner events"]
        APPROVE_API["approval resolution endpoint"]
        TERMINAL_API["terminal resources + attach WebSocket"]
    end

    INFO --> INFO_API
    NEWCHAT --> INFO
    NEWCHAT --> USE_RUNNERS
    USE_RUNNERS --> REMOTE
    REMOTE --> RUNNERS_API
    NEWCHAT -->|"runner_id + workspace_id + policy"| CREATE_API

    HOSTCAP --> USE_RUNNERS
    BADGE --> HEALTH
    BADGE --> EVENTS

    EVENTS --> NORMALIZE
    NORMALIZE --> CARD
    CARD --> BLOCKS
    CARD --> INBOX
    INBOX --> APPROVE_API

    MAIN --> VIEW
    RAIL --> VIEW
    VIEW --> SESSION
    SESSION <-->|"binary I/O + resize JSON"| TERMINAL_API
```

There is no separate `NewSessionRunnerPicker.tsx` or planned
`useRunnerState.ts` layer on this branch. The picker is integrated into
`NewChatLandingScreen`, while runner lifecycle state is consumed through the
existing terminal lifecycle store and runner-health provider.

## 2. Canonical new-session UI flow

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant Screen as NewChatLandingScreen
    participant Query as useLocalRunners
    participant Lib as remoteRunner.ts
    participant Server
    participant Session as Created session UI

    Screen->>Server: GET /v1/info
    Server-->>Screen: remote_local_runner flag

    alt feature disabled or still loading
        Screen-->>User: local runner option hidden / fails closed
    else enabled
        Screen->>Query: enable runner query
        Query->>Lib: fetchLocalRunners()
        Lib->>Server: GET /v1/runners
        Server-->>Lib: owner-scoped typed summaries
        Lib-->>Screen: runners + opaque workspaces + capabilities
        Screen-->>User: runner choices filtered by online state,<br/>workspace availability, and harness support
        User->>Screen: select runner and workspace
        User->>Screen: create session
        Screen->>Server: POST /v1/sessions<br/>{runner_id, workspace_id,<br/>execution_mode=local_runner,<br/>local_runner_policy}
        Server-->>Session: snapshot with runner/workspace/policy labels
    end
```

Selecting the local-runner path clears any host/raw-workspace selection, and
selecting a host or managed sandbox clears the local-runner selection. The
contracts remain mutually exclusive.

## 3. Typed approval rendering and decision flow

```mermaid
sequenceDiagram
    autonumber
    participant Runner
    participant Server
    participant SSE as Session event stream
    participant Normalize as localActionApproval.ts
    participant Card as LocalActionApprovalCard
    actor Owner

    Runner->>Server: local-action requested event<br/>action_id + kind + policy + safe preview
    Server->>SSE: publish approval/event state
    SSE->>Normalize: elicitation/local-action payload
    Normalize->>Normalize: require typed action_id contract<br/>ignore unrelated policy metadata
    Normalize-->>Card: normalized shell or write approval

    alt run_shell
        Card-->>Owner: executable-only preview,<br/>hidden arguments, shell guarantee, risk flags
    else write_file
        Card-->>Owner: relative path + bounded diff preview
    end

    Owner->>Card: approve or deny
    Card->>Server: resolve owning session/action
    Server-->>Runner: one verdict for exact action_id
    Server-->>SSE: terminal local-action outcome
    SSE-->>Card: completed / failed / denied audit state
```

The card never needs the canonical local workspace root. Relative paths and
display-only labels are sufficient for review.

## 4. Runner status presentation

```mermaid
stateDiagram-v2
    [*] --> hidden: execution_mode != local_runner
    [*] --> online: local-runner session

    online --> offline: runner lifecycle offline<br/>or online poll=false
    offline --> reconnecting: runner_reconnected event
    reconnecting --> online: terminal lifecycle/attach settles
    offline --> online: online poll recovers

    state online {
        [*] --> workspace_label
        workspace_label --> policy_tooltip
    }

    note right of offline
        Badge says the session is preserved.
        It does not imply that input remains available.
    end note
```

PR #2 supplies the runner status and approval surfaces. PR #3 makes the
terminal-side offline/reconnect behavior generation-safe and bounded.

## 5. Terminal bridge boundary inherited by PR #2

```mermaid
sequenceDiagram
    autonumber
    participant Surface as MainTerminalView / TerminalsPanel
    participant View as TerminalView
    participant Bridge as TerminalSession
    participant Server as terminal attach route
    participant Runner as runner attach route
    participant Tmux as tmux pane

    Surface->>View: sessionId + terminalId + transport + readOnly
    View->>Bridge: construct xterm/WebSocket bridge
    Bridge->>Server: WS attach with transport/read_only
    Server->>Server: authorize owner write or collaborator read
    Server->>Runner: multiplex ws.open over runner tunnel
    Runner->>Tmux: control or PTY attach
    Tmux-->>Bridge: binary terminal bytes through runner/server
    Bridge->>Tmux: binary input; resize JSON through runner/server
```

The detailed reconnect state machine, close-code handling, bounded settlement,
per-surface selection persistence, exited-terminal retention, and real tmux
acceptance boundary live in the PR #3 version of this document.
