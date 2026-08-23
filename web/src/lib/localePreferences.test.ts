import { afterEach, describe, expect, it } from "vitest";
import { DEFAULT_LOCALE, isLocale, readLocale, writeLocale } from "./localePreferences";

afterEach(() => {
  localStorage.clear();
});

describe("localePreferences", () => {
  it("defaults to English when no preference is stored", () => {
    expect(readLocale()).toBe(DEFAULT_LOCALE);
  });

  it("persists and restores a supported locale", () => {
    writeLocale("ru");

    expect(localStorage.getItem("omnigent:ui-locale")).toBe(JSON.stringify("ru"));
    expect(readLocale()).toBe("ru");
  });

  it("falls back to English for malformed or unsupported stored values", () => {
    localStorage.setItem("omnigent:ui-locale", "not-json");
    expect(readLocale()).toBe("en");

    localStorage.setItem("omnigent:ui-locale", JSON.stringify("de"));
    expect(readLocale()).toBe("en");
  });

  it("validates values before they reach i18next", () => {
    expect(isLocale("en")).toBe(true);
    expect(isLocale("ru")).toBe(true);
    expect(isLocale("de")).toBe(false);
    expect(isLocale(null)).toBe(false);
  });
});
