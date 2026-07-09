# 06 — Architecture Diagrams

Mermaid diagrams for the remote/local runner MVP. Component names map 1:1 to the task
specs in `tasks/` (T01–T08) and to real repository modules. Planning artifact only.

## 1. Full system architecture

```mermaid
flowchart TB
    subgraph client["User devices — web / desktop UI"]
        UI["Session UI<br/>chat · files · events<br/><i>web/src</i>"]
        PICKER["Runner status badge +<br/>workspace picker<br/><i>T07</i>"]
        XTERM["xterm.js terminal panel<br/><i>TerminalSession.ts</i><br/>transport=control | pty"]
        CARD["Approval / diff cards<br/><i>T07</i>"]
    end

    subgraph server["Remote Omnigent server — omnigent/server"]
        SESS["sessions routes<br/>create + bind validation<br/><i>routes/sessions.py · T04</i>"]
        ATTACH["terminal attach proxy<br/>close codes 4503/4404/4405/4406<br/><i>routes/terminal_attach.py · T06</i>"]
        TUNEP["runner tunnel endpoint<br/>WS /v1/runners/:id/tunnel<br/><i>routes/runner_tunnel.py</i>"]
        TREG["TunnelRegistry<br/>RunnerSession · hello capabilities<br/><i>ws_tunnel/registry.py · T01</i>"]
        RTR["RunnerRouter<br/>httpx over WSTunnelTransport<br/><i>runner/routing.py</i>"]
        PRESET["Policy presets<br/>manual | assisted | auto<br/><i>policies/builtins · T08</i>"]
        SAN["Audit relay +<br/>recursive sanitizer<br/><i>T08</i>"]
        CSTORE[("conversation_store<br/>runner_id column + labels:<br/>workspace_id · workspace_label ·<br/>execution_mode")]
        PSTORE[("permission_store<br/>owner / read grants")]
    end

    subgraph local["Local machine — paired runner (omnigent/runner)"]
        CLI["omnigent host CLI<br/>--workspace pairing · daemon record<br/><i>T03</i>"]
        HELLO["Hello builder<br/>capability detection:<br/>platform · tmux · flags<br/><i>T01</i>"]
        RAPP["Runner ASGI app<br/>tunneled routes<br/><i>runner/app.py</i>"]
        WREG["WorkspaceRegistry<br/>canonical roots · stable ws ids ·<br/>escape blocking<br/><i>runner/workspaces.py · T02</i>"]
        GATE["LocalActionGateway<br/>read / write / patch / shell / git<br/><i>runner/local_actions.py · T05</i>"]
        WPOL["workspace_policy<br/>allow | ask | block ·<br/>sensitive-path guard<br/><i>T05</i>"]
        PEND["pending_approvals<br/>ask-gate bridge"]
        SRES["SessionResourceRegistry<br/>terminal lifecycles · reconcile<br/><i>T06</i>"]
        TMUX["tmux sessions<br/>control_bridge (tmux -C) ·<br/>ws_bridge (tmux attach)"]
        HARN["Native harness CLIs<br/>codex · claude · cursor · ..."]
        FS[("Approved workspace roots<br/>~/projects/...")]
    end

    %% Client ↔ server
    UI -->|"REST + SSE"| SESS
    PICKER -->|"GET /v1/runners"| TUNEP
    XTERM <-->|"WS attach"| ATTACH
    CARD -->|"approve / deny (owner-only)"| SESS

    %% Server internals
    SESS --> CSTORE
    SESS --> PSTORE
    SESS -->|"validate: online · owner ·<br/>harness · workspace"| TREG
    SESS --> PRESET
    ATTACH -->|"ws.open / ws.frame"| TREG
    RTR --> TREG
    SESS -.->|"session snapshot + events"| UI
    SAN --> CSTORE

    %% Tunnel (single persistent outbound WebSocket)
    RAPP ==>|"outbound WS tunnel<br/>hello · request/response · ws.*"| TUNEP
    TUNEP === TREG

    %% Runner internals
    CLI -->|"spawn + env<br/>OMNIGENT_RUNNER_WORKSPACES"| RAPP
    RAPP --> HELLO
    RAPP --> GATE
    RAPP --> SRES
    GATE --> WPOL
    GATE -->|"resolve_in_workspace"| WREG
    GATE -->|"ask verdict"| PEND
    PEND -.->|"approval events via tunnel"| SESS
    GATE -->|"execute (locked, env-allowlisted)"| FS
    SRES --> TMUX
    TMUX --> HARN
    HARN -->|"cwd = bound workspace root"| FS
    WREG --- FS
```

Key boundary (T02/T05): the server coordinates, authorizes, and persists; **only the
runner resolves and enforces paths**. `workspace_label` on the server is display-only.

## 2. Pairing, session create, and terminal mirroring

```mermaid
sequenceDiagram
    autonumber
    actor Dev as User
    participant UI as Web UI
    participant SRV as Omnigent server
    participant TR as TunnelRegistry
    participant RN as Local runner
    participant TM as tmux + native harness

    rect rgb(235, 244, 255)
    Note over Dev,TR: Pairing — T03 / T01
    Dev->>RN: omnigent host --server URL --workspace ~/project
    RN->>SRV: WS connect /v1/runners/:id/tunnel (binding token)
    RN->>SRV: hello — harnesses, workspace_roots, terminal_transports, mode
    SRV->>TR: register(runner_id, hello, owner)
    end

    rect rgb(236, 253, 240)
    Note over Dev,TM: Session create — T04
    Dev->>UI: New session (agent + runner + workspace)
    UI->>SRV: POST /v1/sessions {runner_id, workspace_id}
    SRV->>TR: validate — online · owner · canonical harness · advertised workspace
    alt validation fails
        SRV-->>UI: 409 runner_unavailable / workspace_not_found / capability_mismatch
    else valid
        SRV->>SRV: persist runner_id + labels (workspace_id, execution_mode)
        SRV->>RN: POST /v1/sessions via tunnel {workspace_id}
        RN->>RN: WorkspaceRegistry.get(workspace_id) → canonical root
        RN->>TM: launch native terminal, cwd = workspace root
        RN-->>SRV: terminal resource event
        SRV-->>UI: 201 session snapshot + resources
    end
    end

    rect rgb(255, 247, 235)
    Note over Dev,TM: Terminal mirroring — T06 / T07
    UI->>SRV: WS attach ?transport=control (owner) or read_only=true
    SRV->>SRV: _authorize_terminal_attach (owner / read)
    SRV->>TR: ws.open channel → tunneled attach
    TR->>RN: dispatch runner ASGI attach route
    RN->>TM: control bridge — capture-pane seed, then %output stream
    TM-->>RN: raw pane bytes / %output
    RN-->>TR: ws.frame over tunnel
    TR-->>SRV: proxied WS frame
    SRV-->>UI: binary terminal frame
    UI-->>SRV: binary input / resize
    SRV-->>TR: ws.frame
    TR-->>RN: tunneled input
    RN-->>TM: send-keys -H / resize
    end
```

## 3. Local action with approval gate

```mermaid
sequenceDiagram
    autonumber
    participant AG as Agent turn
    participant SRV as Server workflow
    participant GW as LocalActionGateway (T05)
    participant WP as workspace_policy
    participant PA as pending_approvals
    participant FS as Workspace filesystem
    actor Own as Session owner

    AG->>SRV: tool call — write_file("src/app.py", ...)
    SRV->>SRV: policy preset → policy_mode (T08)
    SRV->>GW: POST /v1/runner/local-actions via tunnel
    GW->>WP: classify_path("write_file", path) / classify_shell(cmd, cwd)

    alt BLOCK — sensitive path, escape, blocked pattern
        WP-->>GW: Verdict BLOCK
        GW-->>SRV: local_action_blocked_by_policy + audit(blocked)
        SRV-->>AG: structured error
    else ASK — manual / assisted, or risky in auto
        WP-->>GW: Verdict ASK
        GW->>GW: compute diff preview (before approval)
        GW->>PA: create approval request
        PA-->>SRV: approval event via tunnel
        SRV-->>Own: approval card (diff, command, cwd)
        Own-->>SRV: approve / deny (owner-only, T08)
        SRV-->>PA: decision
        PA-->>GW: resolved decision
        alt approved
            GW->>FS: resolve_in_workspace → write under per-workspace lock
            GW-->>SRV: audit(completed) — status, duration, exit code
            SRV-->>AG: tool result
        else denied
            GW-->>SRV: audit(denied) — no disk change
            SRV-->>AG: local_action_requires_approval
        end
    else ALLOW — reads, git status/diff, plain shell in auto
        WP-->>GW: Verdict ALLOW
        GW->>FS: execute (bounded output, env allowlist)
        GW-->>SRV: audit(completed) + result
        SRV-->>AG: tool result
    end
```

## 4. Terminal / runner lifecycle states (T06)

```mermaid
stateDiagram-v2
    [*] --> terminal_unknown
    terminal_unknown --> terminal_starting: session create
    terminal_starting --> terminal_running: launch ok
    terminal_starting --> terminal_failed: launch error
    terminal_starting --> runner_offline: tunnel drop

    terminal_running --> terminal_detached: browser detaches (tmux alive)
    terminal_detached --> terminal_running: re-attach
    terminal_running --> terminal_exited: process ends

    terminal_running --> runner_offline: tunnel drop (attach close 4503)
    terminal_detached --> runner_offline: tunnel drop
    runner_offline --> runner_reconnected: tunnel re-register (newest wins)

    runner_reconnected --> terminal_running: terminal alive → reattach
    runner_reconnected --> terminal_exited: dead + auxiliary lifecycle
    runner_reconnected --> terminal_relaunching: dead + required lifecycle
    terminal_relaunching --> terminal_running: relaunch ok
    terminal_relaunching --> terminal_failed: relaunch error
    terminal_relaunching --> runner_offline: tunnel drop

    terminal_exited --> [*]
    terminal_failed --> [*]

    note right of runner_offline
        UI shows reconnect banner;
        session binding is preserved,
        never silently rebound (T04)
    end note
```

## 5. Tunnel frame protocol (context)

```mermaid
flowchart LR
    subgraph frames["ws_tunnel frames (frames.py)"]
        direction TB
        H["hello<br/>+ optional capabilities (T01)"]
        RQ["request / response.head /<br/>response.body / response.end"]
        WS["ws.open / ws.frame / ws.close<br/>(terminal attach channels)"]
        PP["ping / pong keepalive"]
    end
    SRVX["Server<br/>TunnelRegistry"] <-->|"one outbound WebSocket<br/>text JSON frames"| RNX["Runner<br/>ASGI adapter"]
    frames -. describes .- SRVX
```
