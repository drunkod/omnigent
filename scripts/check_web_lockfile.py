#!/usr/bin/env python3
"""Fail when ``web/package.json`` and ``web/package-lock.json`` drift apart.

``npm ci`` is the final authority, but it is intentionally networked and too heavy for
an every-commit hook. This checker covers the deterministic failure mode that previously
reached CI: direct dependency declarations were restored out of the lockfile while the
manifest still required them.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

DEPENDENCY_FIELDS = (
    "dependencies",
    "devDependencies",
    "optionalDependencies",
    "peerDependencies",
)


def _mapping(value: object) -> dict[str, Any]:
    """Return *value* as a string-keyed mapping, or an empty mapping."""
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}


def dependency_errors(
    package_json: dict[str, Any],
    package_lock: dict[str, Any],
) -> list[str]:
    """Return human-readable direct-dependency consistency errors."""
    packages = _mapping(package_lock.get("packages"))
    lock_root = _mapping(packages.get(""))
    errors: list[str] = []
    direct_names: set[str] = set()

    for field in DEPENDENCY_FIELDS:
        manifest_values = _mapping(package_json.get(field))
        lock_values = _mapping(lock_root.get(field))
        direct_names.update(manifest_values)

        missing = sorted(manifest_values.keys() - lock_values.keys())
        extra = sorted(lock_values.keys() - manifest_values.keys())
        mismatched = sorted(
            name
            for name in manifest_values.keys() & lock_values.keys()
            if manifest_values[name] != lock_values[name]
        )
        if missing:
            errors.append(f"{field}: missing from package-lock root: {', '.join(missing)}")
        if extra:
            errors.append(f"{field}: stale package-lock root entries: {', '.join(extra)}")
        for name in mismatched:
            errors.append(
                f"{field}: {name!r} spec differs "
                f"(package.json={manifest_values[name]!r}, package-lock.json={lock_values[name]!r})"
            )

    unresolved = sorted(
        name for name in direct_names if f"node_modules/{name}" not in packages
    )
    if unresolved:
        errors.append(
            "direct dependencies without a package-lock resolution: " + ", ".join(unresolved)
        )
    return errors


def check_files(package_path: Path, lock_path: Path) -> list[str]:
    """Load and compare one npm manifest/lock pair."""
    try:
        package_json = json.loads(package_path.read_text(encoding="utf-8"))
        package_lock = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [str(exc)]
    if not isinstance(package_json, dict) or not isinstance(package_lock, dict):
        return ["package.json and package-lock.json must contain JSON objects"]
    return dependency_errors(package_json, package_lock)


def main() -> int:
    """Check the repository's web lockfile and print an actionable failure."""
    root = Path(__file__).resolve().parents[1]
    package_path = root / "web" / "package.json"
    lock_path = root / "web" / "package-lock.json"
    errors = check_files(package_path, lock_path)
    if not errors:
        return 0

    print("web/package-lock.json is inconsistent with web/package.json:", file=sys.stderr)
    for error in errors:
        print(f"  - {error}", file=sys.stderr)
    print(
        "Regenerate it with: cd web && npm install --package-lock-only",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
