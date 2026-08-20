# T01 — i18n foundation

Add the minimum application infrastructure for bundled English and Russian resources.

## Subtasks

1. [`step-01-locale-preference.md`](step-01-locale-preference.md)
2. [`step-02-resources-and-init.md`](step-02-resources-and-init.md)
3. [`step-03-boot-provider.md`](step-03-boot-provider.md)

## Done when

The app initializes i18next synchronously from a validated persisted locale and exposes it through `I18nextProvider`, with no runtime translation fetch.
