# T10 Step 02 — Shell security contract

Blocker #2. Direct file operations are workspace-contained, but shell execution
is not. `LocalActionGateway.run_shell` resolves only the requested `cwd` and
then passes the original command to `asyncio.create_subprocess_shell`. Approval
is consent, not a filesystem sandbox.

## 1. Make the product decision before implementation

Choose one explicit mode:

- **Strict workspace mode (recommended for an untrusted or shared server):**
  run shell actions inside an OS/container sandbox with only the selected
  workspace mounted, and deny network/extra mounts by default.
- **Trusted machine mode:** allow normal user-level shell access after owner
  approval, rename the guarantee from “workspace containment” to
  “workspace-scoped cwd and approval,” and update P8/P7 docs accordingly.

Do not use regexes to infer safety from arbitrary shell syntax. Commands can
escape through absolute paths, variables, redirections, interpreters,
subprocesses, symlinks, and `cd`.

## 2. Strict-mode implementation shape

Keep policy classification and approval in `LocalActionGateway`, but make the
process launcher an explicit boundary:

```python
async def run_shell(...):
    record = self._new_record(...)
    verdict = classify_action("run_shell", mode=mode, command=command, cwd=cwd)
    await self._gate(record, verdict)
    workspace = self.workspace_registry.resolve_workspace(workspace_id)
    argv = [
        "bwrap", "--die-with-parent", "--unshare-net",
        "--ro-bind", "/usr", "/usr", "--ro-bind", "/bin", "/bin",
        "--proc", "/proc", "--dev", "/dev",
        "--bind", str(workspace.root), "/workspace",
        "--chdir", "/workspace", "--", "/bin/sh", "-lc", command,
    ]
    proc = await asyncio.create_subprocess_exec(*argv, ...)
```

The exact sandbox tool is platform-dependent. Verify availability at startup,
fail closed when strict mode is requested but unavailable, and never silently
fall back to unrestricted shell. Use a launcher abstraction so Linux, macOS,
and development mode can have separate implementations.

## 3. Limits and race handling

- Bound command length and stdout/stderr capture before launching.
- Re-resolve `cwd` under the same execution policy immediately before launch.
- For writes, re-resolve the target and parent under the write lock; use
  no-follow/atomic primitives where the platform supports them.
- Preserve bounded audit summaries; never log the full command or resolved
  absolute workspace path.

## 4. Tests

```python
async def test_strict_shell_cannot_read_outside_workspace(gateway, workspace):
    result = await gateway.run_shell(
        session_id="conv_1", workspace_id=workspace.id,
        command="cat /etc/passwd", cwd=".", mode=PolicyMode.AUTO,
    )
    assert result["exit_code"] != 0


async def test_strict_mode_fails_closed_without_sandbox(monkeypatch):
    monkeypatch.setattr("omnigent.runner.shell_sandbox.available", lambda: False)
    with pytest.raises(OmnigentError, match="sandbox"):
        create_gateway(strict_shell=True)
```

## Done when

- The chosen guarantee is stated in the security plan and user/admin docs.
- Strict mode has a real OS boundary, or trusted mode no longer claims shell
  workspace containment.
- Outside-read/write, sandbox-unavailable, command-limit, and TOCTOU tests are
  green; P8's workspace-escape row is updated to match the evidence.

