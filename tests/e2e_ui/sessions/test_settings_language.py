"""E2E: Settings can switch to Russian and restore it after reload."""

from __future__ import annotations

from playwright.sync_api import Page, expect


def test_settings_language_switches_to_russian_and_persists(
    page: Page,
    seeded_session: tuple[str, str],
) -> None:
    """Select Russian, verify live Settings/nav copy, then verify reload persistence."""
    base_url, session_id = seeded_session

    page.goto(f"{base_url}/settings/appearance")

    language = page.get_by_role("combobox", name="Language")
    expect(language).to_be_visible(timeout=30_000)
    language.click()
    page.get_by_role("option", name="Русский").click()

    expect(page.get_by_role("heading", name="Внешний вид")).to_be_visible()
    expect(page.get_by_test_id("settings-nav-appearance")).to_have_text("Внешний вид")

    page.get_by_role("link", name="Назад в Omnigent").click()
    expect(page.get_by_test_id("new-chat-button")).to_have_text("Новая сессия")
    expect(page.get_by_test_id("sidebar-search-button")).to_have_attribute("aria-label", "Поиск")
    expect(page.get_by_role("heading", name="Сессии")).to_be_visible()

    page.goto(f"{base_url}/c/{session_id}")
    composer = page.get_by_role("textbox", name="Написать агенту")
    expect(composer).to_be_visible(timeout=30_000)
    expect(composer).to_have_attribute("placeholder", "Спросите агента о чём угодно…")

    page.goto(f"{base_url}/settings/appearance")
    page.reload()

    expect(page.get_by_role("heading", name="Внешний вид")).to_be_visible(timeout=30_000)
    expect(page.get_by_role("combobox", name="Язык")).to_contain_text("Русский")
