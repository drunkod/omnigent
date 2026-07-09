# T03 — CLI pairing: connect a local runner + workspaces to a remote server

Implements plan `02-server-runner-work-plan.md` Task 1.3 and checklist P3.

Ground truth (verified against current code):

- `omnigent/cli.py` is a click CLI. A host pairing flow **already exists**:
  `@cli.group("host", ...)` with `--server`, plus `host status`, `host stop`,
  `host stop-session` subcommands and daemon-record helpers
  (`_selected_daemon_records`, `_daemon_status_payload`, `_resolve_host_server`).
- Runner identity/token binding exists in `omnigent/runner/identity.py`
  (`RUNNER_TUNNEL_TOKEN_HEADER`, `token_bound_runner_id`).

Decision (matches plan guidance): **extend `omnigent host`, do not add a new
top-level `runner` group.** The user-facing feature is "connect this machine",
which is exactly what `omnigent host` already means.

## 1. Add `--workspace` to the host group

```python
# omnigent/cli.py — extend the existing host group options
@cli.group("host", cls=_HostGroup, invoke_without_command=True)
@click.option("--server", default=None, help="Remote omnigent server URL.")
@click.option(
    "--workspace",
    "workspaces",
    multiple=True,
    type=click.Path(exists=True, file_okay=False),
    help=(
        "Approve a local directory the remote agent may work in. "
        "Repeatable. Paths are canonicalized; the runner refuses any "
        "file/shell action outside approved roots."
    ),
)
@click.option("--non-interactive", is_flag=True, ...)  # existing option unchanged
def host(
    ctx: click.Context,
    server: str | None,
    workspaces: tuple[str, ...],
    non_interactive: bool,
) -> None:
    """Register this machine as a host with a server."""
    ...
```

Where the host daemon spawns the runner process, pass approved roots through the env
var consumed by T02 (`WorkspaceRegistry.from_paths`):

```python
import os
from omnigent.runner.workspaces import canonicalize_root

def _workspace_env(workspaces: tuple[str, ...]) -> dict[str, str]:
    """Canonicalize approved roots and encode for the runner process."""
    canonical = [str(canonicalize_root(w)) for w in workspaces]
    return {"OMNIGENT_RUNNER_WORKSPACES": os.pathsep.join(canonical)} if canonical else {}

# in the daemon/runner spawn path:
spawn_env.update(_workspace_env(workspaces))
```

## 2. Persist pairing state under `~/.omnigent`

Follow the existing daemon-record pattern (the host group already keeps per-server
daemon records — reuse that store rather than inventing a new file). Add the approved
workspaces to the record so `host status` can show them and restarts re-apply them:

```python
# addition to the daemon record payload written at pairing time
record["workspaces"] = [str(canonicalize_root(w)) for w in workspaces]
record["runner_mode"] = "local"
```

Never store the tunnel binding token in plaintext logs; the record file must remain
`0600` (verify the existing record writer already does this — if not, fix it here).

## 3. Extend `host status` output

`_daemon_status_payload` gains workspace + readiness info. Readiness probes are the
same bounded checks as T02's `validate_workspace`:

```python
import shutil

def _local_readiness() -> dict[str, bool]:
    """Cheap tool availability probes shown by ``omnigent host status``."""
    return {
        "tmux": shutil.which("tmux") is not None,
        "git": shutil.which("git") is not None,
        "node": shutil.which("node") is not None,
    }

# in _daemon_status_payload(...):
payload["workspaces"] = record.get("workspaces", [])
payload["readiness"] = _local_readiness()
payload["runner_mode"] = record.get("runner_mode", "local")
```

Human-readable output example:

```text
$ omnigent host status
Server        https://omnigent.example.com   online
Runner        runner_0123456789abcdef        connected (v0.9.0, darwin/arm64)
Workspaces    ~/projects/omnigent            read,write,shell,git,terminal
Readiness     tmux ok · git ok · node ok
```

## 4. Add `omnigent host add-workspace` / `remove-workspace`

Lets the user grow the approved set without re-pairing. Local-only mutation +
**explicit daemon restart or an implemented live-reload path**. A network reconnect by
itself is not enough unless the daemon process actually re-reads the persisted record and
rebuilds the hello payload (T01):

```python
@host.command("add-workspace")
@click.argument("path", type=click.Path(exists=True, file_okay=False))
@click.option("--server", default=None, help="Target server record to update.")
@click.pass_context
def host_add_workspace(ctx: click.Context, path: str, server: str | None) -> None:
    """Approve an additional local workspace root for the paired runner."""
    if server is None:
        server = _host_group_option(ctx, "server")
    record = _require_daemon_record(server)  # reuse existing selection helpers
    canonical = str(canonicalize_root(path))
    roots = record.get("workspaces", [])
    if canonical in roots:
        click.echo(f"Already approved: {canonical}")
        return
    roots.append(canonical)
    record["workspaces"] = roots
    _write_daemon_record(record)
    click.echo(f"Approved workspace: {canonical}")
    click.echo("Restart the host daemon to advertise it, unless live reload is implemented.")


@host.command("remove-workspace")
@click.argument("path")
@click.option("--server", default=None)
@click.pass_context
def host_remove_workspace(ctx: click.Context, path: str, server: str | None) -> None:
    """Revoke an approved workspace root."""
    if server is None:
        server = _host_group_option(ctx, "server")
    record = _require_daemon_record(server)
    canonical = str(canonicalize_root(path))
    roots = [r for r in record.get("workspaces", []) if r != canonical]
    if len(roots) == len(record.get("workspaces", [])):
        raise click.ClickException(f"Not an approved workspace: {canonical}")
    record["workspaces"] = roots
    _write_daemon_record(record)
    click.echo(f"Revoked workspace: {canonical}")
```

(`_require_daemon_record` / `_write_daemon_record` = thin wrappers over the existing
daemon-record helpers; name them to match whatever those are actually called when
implementing.)

## 5. Clean shutdown

`host stop` already exists. Verify (and add a test) that stopping the daemon:

1. Terminates the runner subprocess (which closes the tunnel → server's
   `on_runner_disconnect` fires → sessions show `runner_offline`).
2. Kills runner-owned harness subprocesses via the existing
   `SessionResourceRegistry.cleanup_session` path.
3. Leaves no orphaned tmux sessions for required agent terminals unless the record
   opts into `preserve_terminals: true`.

## 6. Tests — `tests/cli/test_host_workspaces.py`

```python
"""CLI: workspace approval flags and record persistence."""

from pathlib import Path

from click.testing import CliRunner

from omnigent.cli import cli


def test_add_workspace_canonicalizes_and_persists(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))  # isolate ~/.omnigent
    project = tmp_path / "proj"
    project.mkdir()
    # ... seed a fake daemon record for the default server target ...
    runner = CliRunner()
    result = runner.invoke(cli, ["host", "add-workspace", str(project)])
    assert result.exit_code == 0
    assert "Approved workspace" in result.output


def test_remove_unknown_workspace_fails(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    project = tmp_path / "proj"
    project.mkdir()
    runner = CliRunner()
    result = runner.invoke(cli, ["host", "remove-workspace", str(project)])
    assert result.exit_code != 0


def test_workspace_env_uses_pathsep(tmp_path: Path) -> None:
    import os
    from omnigent.cli import _workspace_env

    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(); b.mkdir()
    env = _workspace_env((str(a), str(b)))
    assert env["OMNIGENT_RUNNER_WORKSPACES"].split(os.pathsep) == [
        str(a.resolve()), str(b.resolve())
    ]
```

## Acceptance checklist

- [ ] `omnigent host --server URL --workspace ~/project` pairs and advertises the root.
- [ ] Approved roots persist in the existing daemon record and survive daemon restart.
- [ ] `host status` shows runner id, online state, workspaces, and tmux/git/node readiness.
- [ ] `add-workspace`/`remove-workspace` mutate the approved set with canonicalization.
- [ ] Workspace mutations are advertised only after an explicit daemon restart or a real
      live-reload mechanism that re-reads the persisted record.
- [ ] `host stop` deregisters cleanly; no orphaned tmux agent sessions.
- [ ] Pairing token never printed or logged.
