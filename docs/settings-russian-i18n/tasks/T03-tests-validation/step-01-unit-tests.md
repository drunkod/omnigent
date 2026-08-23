# Step 01 — Unit tests

- Add `localePreferences.test.ts` for defaults, valid persistence, corrupt data, unsupported locales, and write failures where practical.
- Extend colocated `SettingsPage.test.tsx` for live Russian switching and persistence.
- Extend `settingsNav.test.tsx` to assert Russian nav rendering.
- Reset the global i18n language to English between tests to prevent leakage.
