# Step 01 — Language control

- Add the control to Settings → Appearance after font controls.
- Display native language names: English and Русский.
- Validate Radix Select values with `isLocale`.
- Persist first, then call `i18n.changeLanguage` for immediate rerender.
- Add a stable `language-select` test id and translated accessible label/helper text.
