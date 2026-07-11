# Remaining work — dependency tracks

Status as of `7b045066` (T01–T07 landed on `mvp-v0`). Three independent
tracks run in parallel; steps inside a track are sequential. The
"anytime" pool has no dependencies except P12, which lands last.

## Track diagram

```mermaid
flowchart LR
    subgraph track1 ["Track 1 · Permissions (critical path)"]
        direction LR
        A1["apply_patch gap<br/>implement or un-advertise<br/>(capabilities.py vs local_actions.py)"]
        A2["T08 / P8<br/>policy presets +<br/>security test suite"]
        A3["Approval cards<br/>Deferred C + diff preview UI"]
        A4["e2e approval flow<br/>deny → file unchanged"]
        A1 --> A2 --> A3 --> A4
    end

    subgraph track2 ["Track 2 · Runner UX"]
        direction LR
        B1["Runner list fetch<br/>Deferred A, hosts API types"]
        B2["Workspace picker<br/>Deferred B + execution-mode badge"]
        B3["Capability dashboard<br/>Deferred D"]
        B1 --> B2 --> B3
    end

    subgraph track3 ["Track 3 · Lifecycle polish"]
        direction LR
        C1["T06 snapshot-on-connect<br/>runner state replay for<br/>fresh page loads"]
        C2["Refresh-while-offline UI<br/>preserved-session copy<br/>on cold mount"]
        C1 --> C2
    end

    subgraph pool ["Anytime, in parallel"]
        direction LR
        D1["P0 planning PR"]
        D2["P1 design docs"]
        D3["P10 parity tests<br/>resize / paste / Ctrl-C"]
        D4["Playwright fixture"]
        D5["P11 observability"]
    end

    P12["P12 docs + rollout (last)"]

    track1 --> P12
    track2 --> P12
    track3 --> P12
    pool --> P12
```

## Sequencing rationale

- **Track 1 is strictly sequential.** Approval/diff cards consume T08's
  approval event model, and T08 should not start until the `apply_patch`
  decision is made: the hello frame advertises `apply_patch` in
  `DEFAULT_TOOL_CAPABILITIES` but no runner-side implementation exists,
  so presets would be built on a moving gateway surface.
- **Track 2 is unblocked today.** The hosts API already lists runners
  (`omnigent/server/routes/hosts.py`), so Deferred A needs only web
  types + fetch before the picker can start.
- **Track 3 is server-side and independent** of both UI tracks; the
  refresh-while-offline copy depends on the snapshot frame existing.
- **Playwright fixture early pays off**: e2e items in all three tracks
  queue behind it.
- **P12 last**: user/admin/security/troubleshooting docs describe the
  end state, so they wait for the tracks to converge.

## Solo order (recommended)

1. `apply_patch` decision (Track 1, step 1)
2. T06 snapshot-on-connect (Track 3 — small, improves refresh UX early)
3. T08 policies + security tests
4. Deferred A/B in parallel with T08's test-writing tail
5. Approval cards, then dashboard
6. P12 docs + rollout
