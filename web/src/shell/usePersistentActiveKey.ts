import { useCallback, useEffect, useState } from "react";

const storageKey = (conversationId: string, surface: string) =>
  `omnigent.activeTerminalKey.${conversationId}.${surface}`;

function readStoredKey(
  conversationId: string,
  surface: string,
  fallback: string | null,
): string | null {
  if (typeof window === "undefined") return fallback;
  try {
    return window.sessionStorage.getItem(storageKey(conversationId, surface)) ?? fallback;
  } catch {
    return fallback;
  }
}

/** Session-storage-backed active terminal selection, scoped per surface. */
export function usePersistentActiveKey(
  conversationId: string,
  surface: string,
  initialValue: string | null = null,
) {
  const [activeKey, setActiveKeyState] = useState<string | null>(() =>
    readStoredKey(conversationId, surface, initialValue),
  );

  useEffect(() => {
    setActiveKeyState(readStoredKey(conversationId, surface, initialValue));
  }, [conversationId, surface, initialValue]);

  const setActiveKey = useCallback(
    (next: string | null) => {
      setActiveKeyState(next);
      if (typeof window === "undefined") return;
      try {
        if (next === null || next === "") {
          window.sessionStorage.removeItem(storageKey(conversationId, surface));
        } else {
          window.sessionStorage.setItem(storageKey(conversationId, surface), next);
        }
      } catch {
        // Persistence is best-effort; in-memory selection still works.
      }
    },
    [conversationId, surface],
  );

  return [activeKey, setActiveKey] as const;
}
