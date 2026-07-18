from __future__ import annotations

from scripts.check_web_lockfile import dependency_errors


def _lock(root: dict[str, object], *resolved: str) -> dict[str, object]:
    packages: dict[str, object] = {"": root}
    packages.update({f"node_modules/{name}": {"version": "1.0.0"} for name in resolved})
    return {"lockfileVersion": 3, "packages": packages}


def test_matching_direct_dependencies_are_accepted() -> None:
    package = {
        "dependencies": {"@scope/icon": "^1.0.0"},
        "devDependencies": {"vitest": "^4.0.0"},
    }
    lock = _lock(
        {
            "dependencies": {"@scope/icon": "^1.0.0"},
            "devDependencies": {"vitest": "^4.0.0"},
        },
        "@scope/icon",
        "vitest",
    )

    assert dependency_errors(package, lock) == []


def test_missing_root_dependency_is_reported() -> None:
    package = {"dependencies": {"@scope/icon": "^1.0.0"}}
    lock = _lock({"dependencies": {}}, "@scope/icon")

    assert dependency_errors(package, lock) == [
        "dependencies: missing from package-lock root: @scope/icon"
    ]


def test_changed_dependency_spec_is_reported() -> None:
    package = {"dependencies": {"react": "^18.2.0"}}
    lock = _lock({"dependencies": {"react": "^17.0.0"}}, "react")

    assert dependency_errors(package, lock) == [
        "dependencies: 'react' spec differs (package.json='^18.2.0', package-lock.json='^17.0.0')"
    ]


def test_direct_dependency_without_resolution_is_reported() -> None:
    package = {"devDependencies": {"vitest": "^4.0.0"}}
    lock = _lock({"devDependencies": {"vitest": "^4.0.0"}})

    assert dependency_errors(package, lock) == [
        "direct dependencies without a package-lock resolution: vitest"
    ]


def test_stale_lock_root_entry_is_reported() -> None:
    package = {"dependencies": {}}
    lock = _lock({"dependencies": {"removed-package": "^1.0.0"}}, "removed-package")

    assert dependency_errors(package, lock) == [
        "dependencies: stale package-lock root entries: removed-package"
    ]
