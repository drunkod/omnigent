# T10 Step 04 — Capability truthfulness and gateway convergence

Blocker #4. `DEFAULT_TOOL_CAPABILITIES` advertises `search_files`,
`git_status`, and `git_diff`, while those operations currently run through the
environment-filesystem routes rather than the `LocalActionGateway` tool path.
That creates two policy/audit surfaces and makes the capability list ambiguous.

## 1. Choose one contract

Preferred: expose search and git reads through the same gateway interface used
for `read_file`, `list_dir`, `write_file`, and `run_shell`. Every operation
must receive a workspace id, resolve paths through `WorkspaceRegistry`, apply
the policy classifier, and emit a bounded audit event.

Alternative: remove the three names from `DEFAULT_TOOL_CAPABILITIES` and keep
the environment-filesystem API as a separately documented read-only protocol.
Do not implement them by translating to unrestricted `run_shell`.

## 2. Gateway interface example

```python
async def search_files(self, *, session_id, workspace_id, query, path=".", mode):
    record = self._new_record(
        session_id=session_id, workspace_id=workspace_id, kind="search_files", mode=mode
    )
    await self._gate(record, classify_action("search_files", mode=mode, path=path))
    root = self._resolve_or_audit(record, path)
    result = await asyncio.to_thread(
        self.workspace_registry.search, workspace_id, root, query
    )
    record.status = "completed"
    self._publish_audit(record)
    return {"matches": summarize_matches(result)}


async def git_status(self, *, session_id, workspace_id, mode):
    return await self._git_read("git_status", session_id, workspace_id, mode)
```

Add `git_diff` through the same fixed-argv helper. Results must be bounded and
must exclude file contents, secrets, absolute paths, and unrestricted command
output. Do not assemble git commands as shell strings from user input.

## 3. Capability and dispatch tests

```python
@pytest.mark.parametrize("kind", ["search_files", "git_status", "git_diff"])
async def test_advertised_read_operation_uses_gateway(kind, gateway, monkeypatch):
    called = []
    monkeypatch.setattr(gateway, kind, lambda **kwargs: called.append(kwargs))
    await dispatch_read_operation(
        kind, session_id="conv", workspace_id="ws", mode=PolicyMode.MANUAL
    )
    assert called and called[0]["workspace_id"] == "ws"
```

If the alternative contract is selected, invert the test: the three names
must be absent from the gateway/tool capability advertisement and the
read-only route must have explicit authorization and audit tests.

## Done when

- Every advertised operation has one documented dispatch and policy path.
- Search/git tests prove workspace scoping, bounded output, and audit behavior.
- `apply_patch` remains unadvertised until implemented and tested.
- P7 search/git rows and the capability dashboard are updated from test
  evidence, not from the static capability constant alone.

