"""Risk classification for local runner actions.

Pure functions: given an action request, decide allow / ask / block.
Approval UX and policy presets live server-side; this module is the
runner's last line of defense and must fail closed.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

__all__ = [
    "Decision",
    "PolicyMode",
    "Verdict",
    "classify_action",
    "classify_path",
    "classify_shell",
    "is_sensitive_path",
]


class PolicyMode(str, Enum):
    """Local-action policy mode for runner-side classification.

    :cvar MANUAL: Ask for every side effect. Reads remain free once
        workspace containment passes.
    :cvar ASSISTED: Reads free; writes and shell ask.
    :cvar AUTO: In-workspace writes and plain shell allowed; risky shell asks.
    """

    MANUAL = "manual"
    ASSISTED = "assisted"
    AUTO = "auto"


class Decision(str, Enum):
    """Runner-local gateway decision."""

    ALLOW = "allow"
    ASK = "ask"
    BLOCK = "block"


@dataclass(frozen=True)
class Verdict:
    """Classification verdict for one local action.

    :param decision: Whether to allow, ask, or block.
    :param risk_flags: Machine-readable reasons used for audit/UI.
    :param reason: Human-readable explanation.
    """

    decision: Decision
    risk_flags: tuple[str, ...]
    reason: str


# Read-only action kinds allowed without approval in every mode once
# WorkspaceRegistry containment has passed.
_READ_KINDS = frozenset({"read_file", "list_dir", "search_files", "git_status", "git_diff"})
_WRITE_KINDS = frozenset({"write_file", "apply_patch"})

# Patterns blocked in every mode unless a later deployment deliberately
# overrides them. Keep each flag stable: audit events and UI recovery copy key
# off these names.
_BLOCKED_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("privilege_escalation", re.compile(r"^\s*(sudo|doas|su)\b", re.IGNORECASE)),
    (
        "root_delete",
        re.compile(
            r"\brm\s+(-[a-zA-Z]*r[a-zA-Z]*f|-[a-zA-Z]*f[a-zA-Z]*r)[a-zA-Z]*\s+(/|~|\$HOME)(\s|$)",
            re.IGNORECASE,
        ),
    ),
    ("chown_global", re.compile(r"\bchown\b.*\s(/|/etc|/usr)(\s|$)", re.IGNORECASE)),
    (
        "shell_profile",
        re.compile(r">>?\s*(~|\$HOME)/\.(bashrc|zshrc|profile|bash_profile)\b", re.IGNORECASE),
    ),
    ("git_global_config", re.compile(r"\bgit\s+config\s+--global\b", re.IGNORECASE)),
    ("reverse_shell", re.compile(r"\b(nc|ncat|socat)\b.*(?:\s-e(?:\s|$)|\bexec:)", re.IGNORECASE)),
    ("curl_pipe_sh", re.compile(r"\b(curl|wget)\b[^|;&]*\|\s*(ba)?sh\b", re.IGNORECASE)),
)

# Sensitive path names/segments that must never be readable/writable even via
# shell. This is defense in depth beyond workspace containment.
_SENSITIVE_SEGMENTS = frozenset({".ssh", ".aws", ".gnupg", ".password-store"})
_SENSITIVE_BASENAMES = frozenset(
    {
        ".env",
        ".env.local",
        ".env.production",
        ".env.development",
        ".netrc",
        ".npmrc",
        ".pypirc",
        "id_rsa",
        "id_ed25519",
    }
)
_SENSITIVE_PATH_PATTERNS: tuple[tuple[str, ...], ...] = (
    (".config", "gcloud"),
    (".kube", "config"),
)

_ASK_ALWAYS_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "package_install",
        re.compile(r"\b(pip|pip3|npm|pnpm|yarn|uv|cargo|gem|brew|apt(?:-get)?)\s+(install|add)\b", re.IGNORECASE),
    ),
    (
        "git_destructive",
        re.compile(r"\bgit\s+(reset\s+--hard|rebase|push\s+--force|clean\s+-[a-zA-Z]*f[a-zA-Z]*)", re.IGNORECASE),
    ),
    ("file_removal", re.compile(r"\b(rm|unlink|rmdir)\b", re.IGNORECASE)),
)


def is_sensitive_path(path: str) -> bool:
    """Return whether *path* names an obviously secret-bearing location.

    :param path: Path-like string from a local action request or shell token.
    :returns: ``True`` for credential-ish paths such as ``.env`` or ``.ssh``.
    """

    normalized = path.strip().replace("\\", "/")
    parts = [part.lower() for part in Path(normalized).parts if part not in {"", "."}]
    if not parts:
        return False
    if any(part in _SENSITIVE_SEGMENTS for part in parts):
        return True
    if parts[-1] in _SENSITIVE_BASENAMES:
        return True
    return any(
        tuple(parts[index : index + len(pattern)]) == pattern
        for pattern in _SENSITIVE_PATH_PATTERNS
        for index in range(len(parts) - len(pattern) + 1)
    )


def classify_path(kind: str, path: str, *, mode: PolicyMode) -> Verdict:
    """Classify a file-oriented action against sensitive-path policy.

    :param kind: Action kind, e.g. ``"read_file"`` or ``"write_file"``.
    :param path: Workspace-relative path requested by the action.
    :param mode: Local-action policy mode.
    :returns: Classification verdict.
    """

    if is_sensitive_path(path):
        return Verdict(
            Decision.BLOCK,
            (kind, "sensitive_path"),
            f"references sensitive path: {path}",
        )
    return classify_action(kind, mode=mode)


def classify_shell(command: str, *, mode: PolicyMode, cwd: str | None = None) -> Verdict:
    """Classify one shell command string.

    Fail closed: block known-dangerous patterns before mode checks; ask on
    unparseable command strings.

    :param command: Shell command string.
    :param mode: Local-action policy mode.
    :param cwd: Workspace-relative cwd, if supplied.
    :returns: Classification verdict.
    """

    flags: list[str] = ["shell"]
    stripped = command.strip()

    if cwd is not None and is_sensitive_path(cwd):
        return Verdict(
            Decision.BLOCK,
            ("shell", "sensitive_path"),
            f"references sensitive cwd: {cwd}",
        )

    for flag, pattern in _BLOCKED_PATTERNS:
        if pattern.search(stripped):
            return Verdict(Decision.BLOCK, ("shell", flag), f"blocked pattern: {flag}")

    for token in re.findall(r"[^\s\"']+", stripped):
        if is_sensitive_path(token):
            return Verdict(
                Decision.BLOCK,
                ("shell", "sensitive_path"),
                f"references sensitive path: {token}",
            )

    for flag, pattern in _ASK_ALWAYS_PATTERNS:
        if pattern.search(stripped):
            flags.append(flag)

    try:
        shlex.split(stripped)
    except ValueError:
        return Verdict(Decision.ASK, tuple(flags) + ("unparseable",), "unparseable command")

    if mode is PolicyMode.AUTO and len(flags) == 1:
        return Verdict(Decision.ALLOW, tuple(flags), "auto mode: in-workspace shell")
    return Verdict(Decision.ASK, tuple(flags), f"{mode.value} mode: shell requires approval")


def classify_action(
    kind: str,
    *,
    mode: PolicyMode,
    command: str | None = None,
    cwd: str | None = None,
) -> Verdict:
    """Classify a local action by kind.

    :param kind: Gateway action kind, e.g. ``"read_file"``.
    :param mode: Local-action policy mode.
    :param command: Shell command, required for ``run_shell``.
    :param cwd: Shell cwd, optional for ``run_shell``.
    :returns: Classification verdict.
    """

    if kind in _READ_KINDS:
        return Verdict(Decision.ALLOW, ("read",), "read-only inside workspace")
    if kind in _WRITE_KINDS:
        if mode is PolicyMode.AUTO:
            return Verdict(Decision.ALLOW, ("writes_files",), "auto mode: in-workspace write")
        return Verdict(Decision.ASK, ("writes_files",), f"{mode.value} mode: write requires approval")
    if kind == "run_shell":
        return classify_shell(command or "", mode=mode, cwd=cwd)
    return Verdict(Decision.BLOCK, ("unknown_kind",), f"unknown action kind: {kind!r}")
