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

function pluralBaseKey(key) {
  const match = key.match(/^(.*)_(one|few|many|other)$/);
  return match ? match[1] : key;
}

function groupByPluralBase(entries) {
  const groups = new Map();
  for (const [key, message] of entries) {
    const base = pluralBaseKey(key);
    const variants = groups.get(base) ?? new Map();
    variants.set(key, message);
    groups.set(base, variants);
  }
  return groups;
}

const resources = new Map();
for (const locale of LOCALES) {
  const source = await readFile(new URL(`../src/locales/${locale}.json`, import.meta.url), "utf8");
  resources.set(locale, flatten(JSON.parse(source)));
}

const [referenceLocale, ...translatedLocales] = LOCALES;
const reference = resources.get(referenceLocale);
const referenceGroups = groupByPluralBase(reference);
const referenceKeys = [...referenceGroups.keys()].sort();

for (const locale of translatedLocales) {
  const translated = resources.get(locale);
  const translatedGroups = groupByPluralBase(translated);
  const translatedKeys = [...translatedGroups.keys()].sort();
  assert.deepEqual(
    translatedKeys,
    referenceKeys,
    `${locale}.json must have the same translation keys as ${referenceLocale}.json (ignoring plural suffixes)`,
  );

  for (const key of referenceKeys) {
    const referenceVariants = referenceGroups.get(key);
    const translatedVariants = translatedGroups.get(key);
    const referenceInterpolations = [
      ...new Set([...referenceVariants.values()].flatMap((message) => interpolationNames(message))),
    ].sort();
    const translatedInterpolations = [
      ...new Set(
        [...translatedVariants.values()].flatMap((message) => interpolationNames(message)),
      ),
    ].sort();
    assert.deepEqual(
      translatedInterpolations,
      referenceInterpolations,
      `${locale}.${key} must use the same interpolation variables across plural variants`,
    );
  }
}

console.log(
  `i18n resources valid: ${LOCALES.join(", ")} each contain ${referenceKeys.length} matching base keys`,
);
