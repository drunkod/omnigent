"""Defense-in-depth redaction for local-action audit payloads."""

from __future__ import annotations

import re
from pathlib import PurePath

_AUDIT_FORBIDDEN_KEYS = frozenset({"content", "diff_preview", "stdout", "stderr", "token"})
_SECRET_RE = re.compile(
    r"(?i)(?:bearer\s+[A-Za-z0-9._~+/=-]+|(?:token|password|secret|api[_-]?key)=\S+)"
)
_HISTORY_KEYS = frozenset(
    {
        "action_id",
        "session_id",
        "runner_id",
        "workspace_id",
        "kind",
        "requested_by",
        "policy_mode",
        "status",
        "risk_flags",
        "approval_id",
        "cwd",
        "path_summary",
        "command_summary",
        "started_at",
        "finished_at",
        "exit_code",
        "output_truncated",
    }
)


def sanitize_audit_event(value: object) -> object:
    """Recursively remove payload-bearing keys from an audit event."""

    if isinstance(value, dict):
        return {
            key: sanitize_audit_event(item)
            for key, item in value.items()
            if key not in _AUDIT_FORBIDDEN_KEYS
        }
    if isinstance(value, list):
        return [sanitize_audit_event(item) for item in value]
    return value


def sanitize_local_action_history(event: dict[str, object]) -> dict[str, object]:
    """Project one local-action event into a secret-safe history shape."""
    result: dict[str, object] = {}
    for key, value in event.items():
        if key not in _HISTORY_KEYS or key in _AUDIT_FORBIDDEN_KEYS:
            continue
        if key == "command_summary":
            if isinstance(value, str):
                result[key] = _SECRET_RE.sub("[REDACTED]", value.split(maxsplit=1)[0])[:80]
            continue
        if key in {"cwd", "path_summary"}:
            paths = value if isinstance(value, list) else [value]
            safe_paths = [
                path for path in paths if isinstance(path, str) and _is_relative_path(path)
            ]
            result[key] = (
                safe_paths if key == "path_summary" else (safe_paths[0] if safe_paths else ".")
            )
            continue
        result[key] = _redact_strings(value)
    return result


def _is_relative_path(value: str) -> bool:
    """Accept workspace-relative display paths only."""
    return not value.startswith(("/", "~")) and ".." not in PurePath(value).parts


def _redact_strings(value: object) -> object:
    if isinstance(value, str):
        return _SECRET_RE.sub("[REDACTED]", value)[:120]
    if isinstance(value, list):
        return [_redact_strings(item) for item in value[:32]]
    if isinstance(value, dict):
        return {key: _redact_strings(item) for key, item in value.items()}
    return value
