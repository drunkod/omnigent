# Settings Russian localization

## Goal

Add a persisted English/Russian language selector and translate the UI owned by the Settings surface without attempting an app-wide migration.

## Corrections to the draft plan

- Use `ru`, not the draft's Spanish `es` locale.
- Cover all strings owned by `web/src/pages/SettingsPage.tsx` and `web/src/shell/settingsNav.tsx`, not only Appearance and Git.
- Keep separately owned surfaces (`MembersPage`, `PoliciesPage`, `HostCapabilityPanel`, and `KeyboardShortcutsList`) outside this first slice.
- Validate values received from the select; do not cast arbitrary strings to `Locale`.
- Initialize bundled resources synchronously and constrain i18next to supported locales.
- Translate visible copy, placeholders, dialog actions, and accessible names together.
- Add focused preference, component, navigation, and Playwright happy-path coverage.

## Task order

1. [`T01-foundation`](tasks/T01-foundation/README.md) — dependency, locale persistence, resources, and boot wiring.
2. [`T02-settings-surface`](tasks/T02-settings-surface/README.md) — selector and complete Settings-owned copy migration.
3. [`T03-tests-validation`](tasks/T03-tests-validation/README.md) — unit/e2e coverage and build validation.

## Acceptance criteria

- Settings → Appearance offers English and Русский.
- Choosing Русский updates Settings content and sidebar navigation immediately.
- The choice persists under `omnigent:ui-locale` and is restored on reload.
- Invalid or corrupt stored values fall back to English without breaking boot.
- English remains the fallback and the rest of the application remains unchanged in this slice.
- Focused Vitest tests, type-check, standalone build, embed build, and the new Playwright happy path pass.
