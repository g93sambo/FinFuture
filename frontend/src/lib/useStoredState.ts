"use client";

import { useCallback, useEffect, useState } from "react";

const PREFIX = "finfuture.saved.";
const MAX_AGE_MS = 24 * 60 * 60 * 1000;

/**
 * State that survives leaving and coming back to a page (per browser, per key).
 * Used for results that take a while to build, such as an allocation or a fund comparison.
 * Entries older than a day are ignored so stale prices are not shown as current.
 */
export function useStoredState<T>(key: string | null): [T | null, (value: T | null) => void, Date | null] {
  const [value, setValue] = useState<T | null>(null);
  const [savedAt, setSavedAt] = useState<Date | null>(null);

  useEffect(() => {
    setValue(null);
    setSavedAt(null);
    if (!key) return;
    try {
      const raw = window.localStorage.getItem(PREFIX + key);
      if (!raw) return;
      const parsed = JSON.parse(raw) as { at: number; value: T };
      if (Date.now() - parsed.at > MAX_AGE_MS) {
        window.localStorage.removeItem(PREFIX + key);
        return;
      }
      setValue(parsed.value);
      setSavedAt(new Date(parsed.at));
    } catch {
      // Storage blocked or corrupt entry: start empty
    }
  }, [key]);

  const update = useCallback(
    (next: T | null) => {
      setValue(next);
      const at = Date.now();
      setSavedAt(next === null ? null : new Date(at));
      if (!key) return;
      try {
        if (next === null) window.localStorage.removeItem(PREFIX + key);
        else window.localStorage.setItem(PREFIX + key, JSON.stringify({ at, value: next }));
      } catch {
        // Quota exceeded or storage blocked: keep the in-memory value only
      }
    },
    [key],
  );

  return [value, update, savedAt];
}
