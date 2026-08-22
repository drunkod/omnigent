import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const LOCALES = ["en", "ru"];
const INTERPOLATION_PATTERN = /{{\s*([^},\s]+)[^}]*}}/g;

function flatten(value, prefix = "", entries = new Map()) {
  assert.equal(
    value !== null && typeof value === "object" && !Array.isArray(value),
    true,
    `${prefix || "locale root"} must be an object`,
  );

  for (const [key, child] of Object.entries(value)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (child !== null && typeof child === "object" && !Array.isArray(child)) {
      flatten(child, path, entries);
      continue;
    }

    assert.equal(typeof child, "string", `${path} must be a string`);
    assert.notEqual(child.length, 0, `${path} must not be empty`);
    entries.set(path, child);
  }

  return entries;
}

function interpolationNames(message) {
  return [...message.matchAll(INTERPOLATION_PATTERN)].map((match) => match[1]).sort();
}

const resources = new Map();
for (const locale of LOCALES) {
  const source = await readFile(new URL(`../src/locales/${locale}.json`, import.meta.url), "utf8");
  resources.set(locale, flatten(JSON.parse(source)));
}

const [referenceLocale, ...translatedLocales] = LOCALES;
const reference = resources.get(referenceLocale);
const referenceKeys = [...reference.keys()].sort();

for (const locale of translatedLocales) {
  const translated = resources.get(locale);
  const translatedKeys = [...translated.keys()].sort();
  assert.deepEqual(
    translatedKeys,
    referenceKeys,
    `${locale}.json must have the same translation keys as ${referenceLocale}.json`,
  );

  for (const key of referenceKeys) {
    assert.deepEqual(
      interpolationNames(translated.get(key)),
      interpolationNames(reference.get(key)),
      `${locale}.${key} must use the same interpolation variables as ${referenceLocale}.${key}`,
    );
  }
}

console.log(
  `i18n resources valid: ${LOCALES.join(", ")} each contain ${referenceKeys.length} matching keys`,
);
