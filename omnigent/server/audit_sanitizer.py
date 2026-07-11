"""Defense-in-depth redaction for local-action audit payloads."""

from __future__ import annotations

_AUDIT_FORBIDDEN_KEYS = frozenset({"content", "diff_preview", "stdout", "stderr", "token"})


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
