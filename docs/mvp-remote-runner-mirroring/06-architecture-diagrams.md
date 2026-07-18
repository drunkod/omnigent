# 06 — Implemented Architecture Diagrams

Status reviewed on 2026-07-17 against PR #2,
`feat/mvp-runner-binding-approvals`. These diagrams describe production paths
that exist on the branch; they are no longer planning-only sketches. PR #3
extends the terminal lifecycle and reconnect parts of this architecture.

## 1. Runtime system architecture

```mermaid
flowchart TB
    subgraph browser["Browser / desktop UI"]
        INFO_UI["feature probe<br/><code>GET /v1/info</code>"]
        PICKER["NewChatLandingScreen<br/>useLocalRunners + remoteRunner.ts<br/>runner/workspace selection"]
        CAP_UI["HostCapabilityPanel + RunnerStatusBadge<br/>capabilities, policy, online state"]
        APPROVAL_UI["LocalActionApprovalCard<br/>typed shell/write approval"]
        TERMINAL_UI["TerminalView + TerminalSession<br/>xterm.js WebSocket attach"]
    end

    subgraph server["Remote Omnigent server"]
        INFO_API["server info<br/><code>remote_local_runner</code> flag"]
        RUNNER_API["owner-scoped discovery<br/><code>GET /v1/runners</code>"]
        TUNNEL_API["runner tunnel<br/><code>WS /v1/runners/{runner_id}/tunnel</code>"]
        TUNNEL_REG["TunnelRegistry<br/>owner + HelloFrame capabilities"]
        CREATE_API["session creation<br/>JSON + multipart bundle routes"]
        BIND["validate_local_runner_binding<br/>online · owner · harness · workspace"]
        CONV[("conversation_store<br/>runner_id + opaque labels")]
        PERM[("permission_store<br/>owner/read grants")]
        APPROVAL_GATE["owner-only approval gate<br/>exact action_id · at-most-once"]
        AUDIT["audit sanitizer + history projection<br/>allowlist · bounds · value redaction"]
        SESSION_STREAM["session event stream<br/>runner / terminal / local-action events"]
        ATTACH["terminal attach proxy<br/>owner write · collaborator read-only"]
    end

    subgraph runner["Paired local runner"]
        HOST["omnigent host<br/>identity, pairing, approved workspace config"]
        HELLO["HelloFrame capability builder<br/>harnesses · transports · tools · workspaces"]
        WORKSPACES["WorkspaceRegistry<br/>canonical roots · opaque workspace_id<br/>relative-path containment"]
        GATEWAY["LocalActionGateway<br/>read_file · list_dir · write_file · run_shell"]
        POLICY["workspace policy<br/>ALLOW · ASK · BLOCK"]
        STRICT["strict shell<br/>Bubblewrap + no network<br/>single writable workspace"]
        TRUSTED["trusted-machine shell<br/>explicitly labelled, not sandboxed"]
        TERMINALS["TerminalRegistry + tmux<br/>native harness and user shells"]
        ROOTS[("Approved local workspace roots")]
    end

    INFO_UI --> INFO_API
    PICKER -->|"fetch typed summaries"| RUNNER_API
    RUNNER_API --> TUNNEL_REG
    CAP_UI --> RUNNER_API

    HOST --> WORKSPACES
    HOST --> HELLO
    HELLO -->|"outbound hello over one persistent tunnel"| TUNNEL_API
    TUNNEL_API === TUNNEL_REG

    PICKER -->|"POST runner_id + workspace_id + policy"| CREATE_API
    CREATE_API --> BIND
    BIND --> TUNNEL_REG
    BIND -->|"persist runner affinity + display labels"| CONV
    CREATE_API --> PERM
    CREATE_API -->|"runner notification carries opaque binding"| TUNNEL_REG
    TUNNEL_REG -->|"request/response frames"| HELLO
    HELLO --> TERMINALS
    TERMINALS -->|"resolve workspace_id locally"| WORKSPACES
    WORKSPACES --- ROOTS

    APPROVAL_UI <-->|"owner decision"| APPROVAL_GATE
    APPROVAL_GATE <-->|"approval events / verdict"| TUNNEL_REG
    TUNNEL_REG <-->|"local-action request + result"| GATEWAY
    GATEWAY --> POLICY
    GATEWAY --> WORKSPACES
    GATEWAY -->|"strict_workspace"| STRICT
    GATEWAY -->|"trusted_machine"| TRUSTED
    STRICT --> ROOTS
    TRUSTED --> ROOTS
    GATEWAY -->|"audit lifecycle event"| TUNNEL_REG
    TUNNEL_REG --> SESSION_STREAM
    SESSION_STREAM --> AUDIT
    AUDIT --> CONV
    SESSION_STREAM --> APPROVAL_UI

    TERMINAL_UI <-->|"binary I/O + resize JSON"| ATTACH
    ATTACH --> PERM
    ATTACH <-->|"multiplexed ws.* channel"| TUNNEL_REG
    TUNNEL_REG <-->|"runner attach route"| TERMINALS
```

### Authority boundaries

- The browser binds sessions with `runner_id + workspace_id`; the raw local
  root is never part of the create payload.
- The server validates the binding against the live tunnel registry and stores
  `runner_id` plus opaque/display labels.
- Only `WorkspaceRegistry` resolves `workspace_id` and workspace-relative paths
  to canonical local filesystem paths.
- `WorkspaceRoot.advertise()` omits the canonical `root` field. It does include
  `path_label` as display metadata; for roots outside the user's home directory
  that label can currently be absolute. It must remain display-only. A stricter
  “no absolute display path” product promise requires a separate sanitization
  change.
- Full shell commands, write contents, diffs, and process output may exist in
  transient request/result flows, but the persisted local-action history
  excludes them.

## 2. Runner discovery and canonical session binding

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant UI as New session UI
    participant API as Server routes
    participant REG as TunnelRegistry
    participant RN as Local runner
    participant WS as WorkspaceRegistry
    participant DB as Conversation store

    RN->>WS: load approved canonical roots
    RN->>REG: open tunnel + HelloFrame
    Note over RN,REG: hello advertises workspace_id, display_name,<br/>path_label, capabilities; not the root field

    UI->>API: GET /v1/info
    API-->>UI: remote_local_runner=true
    UI->>API: GET /v1/runners
    API->>REG: list live runners owned by caller
    REG-->>API: live hello metadata
    API-->>UI: typed runner summaries + opaque workspaces

    User->>UI: select runner, workspace, harness, policy
    UI->>API: POST /v1/sessions<br/>{runner_id, workspace_id, local_runner_policy}

    API->>API: schema rejects runner_id mixed with host_id/raw workspace
    API->>REG: validate online, owner, harness, advertised workspace
    alt invalid binding
        REG-->>API: unavailable / forbidden / capability mismatch / workspace missing
        API-->>UI: fail before conversation creation
    else valid binding
        API->>DB: persist runner_id
        API->>DB: persist execution_mode, workspace_id,<br/>workspace_label, policy labels
        API->>RN: notify session creation with opaque binding
        RN->>WS: resolve workspace_id to canonical local root
        RN->>RN: launch supported session/harness in resolved root
        API-->>UI: session snapshot
    end
```

The JSON and multipart-bundle creation paths apply the same validation and
persistence rules.

## 3. Local action, approval, execution, and audit

```mermaid
sequenceDiagram
    autonumber
    participant Agent
    participant Server
    participant Tunnel
    participant GW as LocalActionGateway
    participant Policy as workspace_policy
    participant Owner
    participant FS as Workspace filesystem
    participant Audit as Sanitized history

    Agent->>Server: local action request
    Server->>Tunnel: route to bound runner
    Tunnel->>GW: workspace_id + relative path / shell request
    GW->>Policy: classify action under manual/assisted/auto

    alt BLOCK
        Policy-->>GW: blocked + risk flags
        GW-->>Server: blocked audit event + structured error
    else ASK
        Policy-->>GW: approval required
        opt write_file
            GW->>GW: read current file + create bounded diff preview
        end
        opt run_shell
            GW->>GW: derive executable-only preview<br/>attach strict_workspace or trusted_machine guarantee
        end
        GW-->>Server: requested event with action_id
        Server-->>Owner: typed approval card
        Owner-->>Server: approve or deny
        Server-->>GW: exact action_id verdict
        alt denied
            GW-->>Server: denied event; no execution
        else approved
            GW->>GW: publish approved edge
            GW->>FS: execute inside selected workspace
            Note over GW,FS: write_file rechecks stale content under a workspace lock;<br/>secure final re-resolution/no-follow atomic replace remains follow-up work
            GW-->>Server: completed/failed event + bounded result
        end
    else ALLOW
        Policy-->>GW: allowed
        GW->>FS: execute immediately
        GW-->>Server: completed/failed event + bounded result
    end

    Server->>Audit: allowlist fields, redact values,<br/>drop content/diff/stdout/stderr/tokens
    Audit-->>Server: upsert terminal outcome by action_id
    Server-->>Agent: result or structured error
```

Implemented gateway actions are exactly `read_file`, `list_dir`, `write_file`,
and `run_shell`. `search_files`, `git_status`, `git_diff`, and `apply_patch`
are not advertised as gateway actions.

## 4. Shell execution guarantees

```mermaid
flowchart LR
    REQUEST["run_shell request<br/>workspace_id + relative cwd"] --> POLICY{"policy verdict"}
    POLICY -->|BLOCK| STOP["reject + blocked audit"]
    POLICY -->|ASK| OWNER["owner approval"]
    OWNER -->|deny| DENIED["deny + no process"]
    OWNER -->|approve| MODE{"configured shell mode"}
    POLICY -->|ALLOW| MODE

    MODE -->|strict_shell=true| BWRAP["Bubblewrap<br/>unshare network<br/>read-only system dirs<br/>workspace bound at /workspace"]
    MODE -->|strict_shell=false| TRUSTED["trusted-machine shell<br/>workspace cwd<br/>no containment claim"]

    BWRAP --> ENV["allowlisted child environment<br/>runner auth stripped"]
    TRUSTED --> ENV
    ENV --> LIMITS["600 s timeout<br/>256 KiB stdout/stderr bounds"]
    LIMITS --> RESULT["result returned<br/>payload-free audit persisted"]
```

The mechanism supports both modes. The supported/default alpha contract and
platform copy are still release decisions.

## 5. Data retained by the server

```mermaid
flowchart TB
    subgraph transient["Transient request / approval / result data"]
        COMMAND["full shell command"]
        CONTENT["write content"]
        DIFF["bounded approval diff"]
        OUTPUT["bounded stdout/stderr result"]
    end

    subgraph persisted["Persisted conversation and local-action history"]
        BINDING["runner_id + execution_mode<br/>workspace_id + display label + policy"]
        ACTION["action_id · runner_id · workspace_id<br/>kind · status · relative paths<br/>executable token · timing · exit code"]
    end

    COMMAND -. "not copied to history" .-> ACTION
    CONTENT -. "not copied to history" .-> ACTION
    DIFF -. "not copied to history" .-> ACTION
    OUTPUT -. "not copied to history" .-> ACTION
    BINDING --> ACTION
```

Open security work is intentionally outside these delivered diagrams:
bounded write/request and directory-list sizes, secure post-approval path
re-resolution, no-follow traversal/opening, atomic replacement, log-capture
secrecy tests, and the single-replica approval support statement.
