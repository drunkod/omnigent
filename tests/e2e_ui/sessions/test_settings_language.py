"""E2E: Settings can switch to Russian and restore it after reload."""

from __future__ import annotations

from playwright.sync_api import Page, expect


def test_settings_language_switches_to_russian_and_persists(
    page: Page,
    seeded_session: tuple[str, str],
) -> None:
    """Select Russian, verify live Settings/nav copy, then verify reload persistence."""
    base_url, _session_id = seeded_session

    page.goto(f"{base_url}/settings/appearance")

    language = page.get_by_role("combobox", name="Language")
    expect(language).to_be_visible(timeout=30_000)
    language.click()
    page.get_by_role("option", name="Русский").click()

    expect(page.get_by_role("heading", name="Внешний вид")).to_be_visible()
    expect(page.get_by_test_id("settings-nav-appearance")).to_have_text("Внешний вид")

    page.reload()

    expect(page.get_by_role("heading", name="Внешний вид")).to_be_visible(timeout=30_000)
    expect(page.get_by_role("combobox", name="Язык")).to_contain_text("Русский")
