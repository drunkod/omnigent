# Step 02 — Resources and initialization

- Add `i18next` and `react-i18next` runtime dependencies.
- Add matching `web/src/locales/en.json` and `web/src/locales/ru.json` resources.
- Add `web/src/i18n.ts` with bundled resources, `supportedLngs`, English fallback, and synchronous initialization (`initAsync: false` for the installed i18next version).
- Do not add a detector, backend plugin, CDN, or translation SaaS for this slice.
