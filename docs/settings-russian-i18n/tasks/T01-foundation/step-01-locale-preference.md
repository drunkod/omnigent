# Step 01 — Locale preference

- Add `web/src/lib/localePreferences.ts`.
- Support only `en` and `ru`; default to `en`.
- Persist JSON under `omnigent:ui-locale`.
- Guard browser globals, malformed JSON, unsupported values, and storage failures.
- Export a validator for safe select handling and focused unit tests.
