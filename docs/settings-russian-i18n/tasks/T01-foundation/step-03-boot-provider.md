# Step 03 — Boot provider

- Import the configured i18n instance in `web/src/main.tsx`.
- Wrap the existing application provider tree with `I18nextProvider` without reordering existing providers.
- Initialize i18n in Vitest setup so components using `useTranslation` render consistently in isolated tests.
