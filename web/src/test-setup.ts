import "@testing-library/jest-dom/vitest";
import { vi } from "vitest";

// Node 26 exposes an experimental global `localStorage` accessor that returns
// undefined without a --localstorage-file. Install deterministic browser-like
// storage before i18n reads the persisted locale or test suites clear storage.
const storageByInstance = new WeakMap<object, Map<string, string>>();
const storageFor = (instance: object) => {
  let storage = storageByInstance.get(instance);
  if (!storage) {
    storage = new Map();
    storageByInstance.set(instance, storage);
  }
  return storage;
};
Storage.prototype.clear = function () {
  storageFor(this).clear();
};
Storage.prototype.getItem = function (key) {
  return storageFor(this).get(key) ?? null;
};
Storage.prototype.key = function (index) {
  return [...storageFor(this).keys()][index] ?? null;
};
Storage.prototype.removeItem = function (key) {
  storageFor(this).delete(key);
};
Storage.prototype.setItem = function (key, value) {
  storageFor(this).set(key, String(value));
};
Object.defineProperty(Storage.prototype, "length", {
  configurable: true,
  get() {
    return storageFor(this).size;
  },
});
const localStorageMock = Object.create(Storage.prototype) as Storage;
const sessionStorageMock = Object.create(Storage.prototype) as Storage;
for (const [name, storage] of [
  ["localStorage", localStorageMock],
  ["sessionStorage", sessionStorageMock],
] as const) {
  Object.defineProperty(globalThis, name, {
    configurable: true,
    value: storage,
  });
  Object.defineProperty(window, name, {
    configurable: true,
    value: storage,
  });
}

await import("@/i18n");

// The @lobehub icon packages have broken nested-module resolution
// under vitest; stub presentational glyphs so component modules that
// import them can still load in tests. (The Antigravity glyph additionally
// drags in @lobehub/fluent-emoji → @emoji-mart/data, whose JSON modules need
// an import attribute Node refuses under vitest — so it must be stubbed too.)
vi.mock("@/components/icons/ClaudeIcon", () => ({
  ClaudeIcon: () => null,
}));
vi.mock("@/components/icons/CodexIcon", () => ({
  CodexIcon: () => null,
}));
vi.mock("@/components/icons/OpenCodeIcon", () => ({
  OpenCodeIcon: () => null,
}));
vi.mock("@/components/icons/CursorIcon", () => ({
  CursorIcon: () => null,
}));
vi.mock("@/components/icons/GooseIcon", () => ({
  GooseIcon: () => null,
}));
vi.mock("@/components/icons/KiroIcon", () => ({
  KiroIcon: () => null,
}));
vi.mock("@/components/icons/AntigravityIcon", () => ({
  AntigravityIcon: () => null,
}));

// Radix UI primitives (DropdownMenu, etc.) call these pointer-capture and
// scroll APIs that jsdom doesn't implement. Stub them so component tests
// that open a Radix menu don't throw. No-ops are sufficient — the tests
// assert on the resulting DOM, not on capture/scroll side effects.
if (!Element.prototype.hasPointerCapture) {
  Element.prototype.hasPointerCapture = () => false;
}
if (!Element.prototype.setPointerCapture) {
  Element.prototype.setPointerCapture = () => {};
}
if (!Element.prototype.releasePointerCapture) {
  Element.prototype.releasePointerCapture = () => {};
}
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {};
}

// jsdom doesn't implement IntersectionObserver (used by the sidebar's
// infinite-scroll sentinel). A no-op stub is enough — tests that need to drive
// auto-loading can override the global with their own controllable mock.
if (!("IntersectionObserver" in globalThis)) {
  class MockIntersectionObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
    takeRecords() {
      return [];
    }
    root = null;
    rootMargin = "";
    thresholds = [];
  }
  Object.defineProperty(globalThis, "IntersectionObserver", {
    writable: true,
    configurable: true,
    value: MockIntersectionObserver,
  });
}

// cmdk (the command-palette primitive) constructs a ResizeObserver on mount,
// which jsdom doesn't implement. A no-op stub lets command-palette/selector
// component tests render without throwing.
if (typeof globalThis.ResizeObserver === "undefined") {
  globalThis.ResizeObserver = class {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  };
}

Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }),
});
