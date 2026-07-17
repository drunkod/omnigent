import { useCallback, useEffect, useState } from "react";

const storageKey = (conversationId: string) =>
  `omnigent.activeTerminalKey.${conversationId}`;

function readStoredKey(
  conversationId: string,
  fallback: string | null,
): string | null {
  if (typeof window === "undefined") return fallback;
  try {
    return (
      window.sessionStorage.getItem(storageKey(conversationId)) ?? fallback
    );
  } catch {
    return fallback;
  }
}

/** Session-storage-backed active terminal selection, scoped per conversation. */
export function usePersistentActiveKey(
  conversationId: string,
  initialValue: string | null = null,
) {
  const [activeKey, setActiveKeyState] = useState<string | null>(() =>
    readStoredKey(conversationId, initialValue),
  );

  useEffect(() => {
    setActiveKeyState(readStoredKey(conversationId, initialValue));
  }, [conversationId, initialValue]);

  const setActiveKey = useCallback(
    (next: string | null) => {
      setActiveKeyState(next);
      if (typeof window === "undefined") return;
      try {
        if (next === null || next === "") {
          window.sessionStorage.removeItem(storageKey(conversationId));
        } else {
          window.sessionStorage.setItem(storageKey(conversationId), next);
        }
      } catch {
        // Persistence is best-effort; in-memory selection still works.
      }
    },
    [conversationId],
  );

  return [activeKey, setActiveKey] as const;
}
