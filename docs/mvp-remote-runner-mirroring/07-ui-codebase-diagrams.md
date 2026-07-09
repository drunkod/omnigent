# 07 — UI Codebase Mermaid Diagrams

Planning artifact only. This file maps the remote/local runner MVP onto the current web UI codebase and the planned T07 additions. It intentionally documents code ownership and integration seams; it does not change runtime code.

## 1. Current terminal UI code ownership

The existing terminal UI already has a clean split between shell surfaces, terminal-resource data, terminal status derivation, and the low-level xterm/WebSocket bridge.

```mermaid
flowchart TB
    subgraph surfaces["Terminal surfaces"]
        PANEL["web/src/shell/TerminalsPanel.tsx<br/>right-side Shells panel<br/>list + selected xterm"]
        MAIN["web/src/shell/MainTerminalView.tsx<br/>terminal-first main column<br/>agent terminal or rail-opened shell"]
    end

    subgraph terminal_data["Terminal data + status hooks"]
        UTERMS["web/src/hooks/useTerminals.ts<br/>HTTP seed + SSE-driven query cache<br/>TerminalInfo mapping"]
        USPLIT["web/src/shell/useTerminalSplit.ts<br/>inventory filter + active terminal selection"]
        USTAT["web/src/shell/useTerminalStatuses.ts<br/>connection state + recent activity"]
        TSTATUS["web/src/shell/terminalStatus.tsx<br/>deriveTerminalStatus + TerminalStatusBadge"]
        ACTIVITY["web/src/store/terminalActivity<br/>session.terminal.activity pulses"]
        RUNNERHEALTH["web/src/hooks/RunnerHealthProvider<br/>runner-online edge correction"]
    end

    subgraph bridge["xterm attach bridge"]
        TVIEW["web/src/components/blocks/TerminalView.tsx<br/>React shell, reconnect overlay,<br/>buildAttachPath/buildAttachUrl"]
        TSESSION["web/src/components/blocks/TerminalSession.ts<br/>plain TS bridge: xterm + WebSocket<br/>binary PTY bytes, resize JSON, input hot path"]
        XTERM["@xterm/xterm + addons<br/>FitAddon · WebLinksAddon · WebglAddon"]
    end

    subgraph server_api["Existing server API contracts"]
        TERMSAPI["GET /v1/sessions/:id/resources/terminals<br/>authoritative terminal resources"]
        CREATEAPI["POST /v1/sessions/:id/resources/terminals<br/>launch declared terminal"]
        ATTACHAPI["WS /v1/sessions/:id/resources/terminals/:terminal_id/attach<br/>?transport=control|pty&read_only=true"]
        SSE["Session SSE events<br/>session.resource.created/deleted<br/>session.terminal.activity"]
    end

    PANEL --> USPLIT
    USPLIT --> UTERMS
    USPLIT --> USTAT
    USPLIT --> TSTATUS
    USTAT --> ACTIVITY
    USTAT --> TSTATUS
    PANEL --> TVIEW

    MAIN --> UTERMS
    MAIN --> USTAT
    MAIN --> TSTATUS
    MAIN --> TVIEW

    TVIEW --> TSESSION
    TSESSION --> XTERM

    UTERMS --> TERMSAPI
    UTERMS --> CREATEAPI
    UTERMS -. "cache patched by" .- SSE
    UTERMS --> RUNNERHEALTH
    TSESSION <-->|"binary frames + resize JSON"| ATTACHAPI
```

## 2. Existing attach lifecycle inside the UI

`TerminalView` owns React state and reconnect policy. `TerminalSession` owns xterm, WebSocket listeners, binary input/output, resize, copy behavior, and cleanup.

```mermaid
sequenceDiagram
    autonumber
    participant Surface as TerminalsPanel / MainTerminalView
    participant Hook as useTerminals + useTerminalStatuses
    participant View as TerminalView.tsx
    participant Session as TerminalSession.ts
    participant WS as terminal attach WebSocket
    participant API as Omnigent server attach route

    Surface->>Hook: read TerminalInfo[] and status helpers
    Hook-->>Surface: active terminal + getStatus + setConnectionState
    Surface->>View: sessionId, terminalId, readOnly, transport, callbacks
    View->>View: buildAttachPath(..., transport)
    View->>View: resolveWebSocketUrl(path)
    View->>Session: new TerminalSession(container, wsUrl, callbacks, controlMode)
    Session->>Session: create xterm, FitAddon, WebLinksAddon, WebGL fallback
    Session->>WS: open ws(s)://.../attach
    WS->>API: WebSocket handshake
    API-->>WS: binary terminal stream
    WS-->>Session: ArrayBuffer terminal bytes
    Session->>Session: writeOutput(bytes), sync echo fast path when eligible
    Session-->>View: onActivity / onState
    View-->>Hook: setTerminalConnectionState / markTerminalActive
    Session->>WS: user input as binary bytes
    Session->>WS: resize as JSON {type, cols, rows}

    alt transport-shaped close
        WS-->>View: closed 1001/1006/1012/1013
        View->>View: schedule reconnect with backoff
        View->>Session: dispose old bridge
        View->>Session: construct fresh bridge
    else app close
        WS-->>View: closed 4xxx app code
        View->>Surface: render closed / resume overlay
    end
```

## 3. Planned remote/local runner UI additions

T07 should extend the current UI rather than replacing it. New files are mostly thin state, picker, badge, and approval-card layers around existing terminal primitives.

```mermaid
flowchart TB
    subgraph planned["New planned UI modules — T07"]
        REMOTE_LIB["web/src/lib/remoteRunner.ts<br/>RunnerInfo, RunnerWorkspace,<br/>TerminalUiState, fetchRunners,<br/>close-code mapping"]
        RUNNER_STATE["web/src/hooks/useRunnerState.ts<br/>listen to session.runner_state<br/>runner_offline / runner_reconnected"]
        RUNNER_BADGE["web/src/shell/RunnerStatusBadge.tsx<br/>local runner online/offline chip<br/>preserved-session recovery copy"]
        PICKER["web/src/components/NewSessionRunnerPicker.tsx<br/>owned online local runners<br/>workspace picker + harness warning"]
        LOCAL_APPROVAL["web/src/components/blocks/LocalActionApprovalCard.tsx<br/>diff preview / command approval<br/>owner approve/deny"]
    end

    subgraph existing_surfaces["Existing surfaces to integrate"]
        NEW_SESSION["new session flow<br/>agent + execution mode selection"]
        PANEL["TerminalsPanel.tsx"]
        MAIN["MainTerminalView.tsx"]
        TVIEW["TerminalView.tsx"]
        TSESSION["TerminalSession.ts"]
        APPROVAL_FLOW["existing approval-card/event flow"]
    end

    subgraph server_contracts["New/extended server contracts"]
        RUNNERS_API["GET /v1/runners<br/>runner capabilities + workspaces"]
        SESSION_CREATE["POST /v1/sessions<br/>{runner_id, workspace_id}"]
        RUNNER_EVENTS["SSE: session.runner_state<br/>session.terminal_state<br/>session.local_action"]
        ATTACH_CODES["WS close codes<br/>4503 runner_offline<br/>4404/4405/4406 terminal states"]
        APPROVAL_API["approval resolution endpoint<br/>owner-only local actions"]
    end

    REMOTE_LIB --> RUNNERS_API
    REMOTE_LIB --> ATTACH_CODES
    RUNNER_STATE --> RUNNER_EVENTS

    PICKER --> REMOTE_LIB
    PICKER --> NEW_SESSION
    NEW_SESSION --> SESSION_CREATE

    RUNNER_BADGE --> RUNNER_STATE
    RUNNER_BADGE --> REMOTE_LIB
    RUNNER_BADGE --> PANEL
    RUNNER_BADGE --> MAIN

    LOCAL_APPROVAL --> APPROVAL_FLOW
    LOCAL_APPROVAL --> APPROVAL_API
    LOCAL_APPROVAL --> RUNNER_EVENTS

    TVIEW --> REMOTE_LIB
    TVIEW --> ATTACH_CODES
    TVIEW --> TSESSION
    PANEL --> TVIEW
    MAIN --> TVIEW
```

## 4. Remote/local runner UI data flow

This is the target user-facing flow after T01–T08 are implemented.

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant Picker as NewSessionRunnerPicker
    participant RemoteLib as remoteRunner.ts
    participant Server as Omnigent server
    participant SessionUI as Session UI / shell surfaces
    participant Badge as RunnerStatusBadge + useRunnerState
    participant Terminals as useTerminals / TerminalView
    participant Approval as LocalActionApprovalCard

    User->>Picker: open new session flow
    Picker->>RemoteLib: fetchRunners()
    RemoteLib->>Server: GET /v1/runners
    Server-->>RemoteLib: RunnerInfo[] with workspaces + transports
    Picker-->>User: choose local runner + workspace
    User->>Picker: create session
    Picker->>Server: POST /v1/sessions {runner_id, workspace_id}
    Server-->>SessionUI: session snapshot labels<br/>execution_mode=local_runner<br/>workspace_id / workspace_label

    SessionUI->>Badge: render local runner state
    Badge->>Server: subscribe to session event stream
    Server-->>Badge: session.runner_state / session.terminal_state

    SessionUI->>Terminals: render terminal resources
    Terminals->>Server: GET /v1/sessions/:id/resources/terminals
    Server-->>Terminals: terminal resources with terminal_transport
    User->>Terminals: open terminal
    Terminals->>Server: WS attach ?transport=control|pty&read_only=...
    Server-->>Terminals: terminal bytes or app close code

    alt runner offline
        Server-->>Badge: session.runner_state runner_offline
        Server-->>Terminals: WS close 4503
        Badge-->>User: local runner offline, session preserved
        Terminals-->>User: offline/reconnect overlay, keep xterm buffer
    else local action asks
        Server-->>Approval: approval event with diff_preview / command / risk flags
        Approval-->>User: approve or deny
        User->>Approval: decision
        Approval->>Server: approval resolution
        Server-->>SessionUI: session.local_action audit trail
    end
```

## 5. Implementation order for UI PRs

```mermaid
flowchart LR
    A["UI-0: shared types<br/>remoteRunner.ts"] --> B["UI-1: runner picker<br/>NewSessionRunnerPicker"]
    B --> C["UI-2: session labels consumed<br/>execution_mode + workspace_label"]
    C --> D["UI-3: runner badge<br/>useRunnerState + RunnerStatusBadge"]
    D --> E["UI-4: attach close-code mapping<br/>TerminalView overlay states"]
    E --> F["UI-5: local action approvals<br/>LocalActionApprovalCard"]
    F --> G["UI-6: e2e + visual tests<br/>picker, badge, terminal offline, diff card"]
```

Suggested PR boundaries:

1. `remoteRunner.ts` types and tests, no visible UI.
2. New-session runner/workspace picker behind `remote_local_runner` feature flag.
3. Runner badge and offline/reconnect event handling.
4. Terminal close-code mapping and transport fallback behavior.
5. Local action approval card and audit-event rendering.

## Notes for implementers

- Keep the existing `TerminalView` / `TerminalSession` split. `TerminalSession` should stay a plain TypeScript bridge outside React render cycles.
- Do not open WebSocket attaches for every terminal just to compute status. The current `useTerminalSplit` / `useTerminalStatuses` design intentionally avoids fan-out attaches.
- Prefer control transport when advertised by the runner, but keep PTY fallback and debug override.
- Runner offline must read as recoverable: the session binding is preserved and should not be silently rebound.
- Approval cards must show local diffs/commands before the owner decides; audit events must stay payload-free.
