"use client";

import { useCallback, useEffect, useRef, useState } from "react";

interface RequestState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
  setData: (d: T | null) => void;
}

// In-memory stale-while-revalidate cache across component lifecycles
const swrCache = new Map<string, unknown>();

/** Helper: delays a loading flag (e.g. 150ms) to avoid loading flashes on sub-150ms responses */
export function useDelayedFlag(active: boolean, delay = 180) {
  const [show, setShow] = useState(false);
  useEffect(() => {
    if (!active) {
      setShow(false);
      return;
    }
    const t = setTimeout(() => setShow(true), delay);
    return () => clearTimeout(t);
  }, [active, delay]);
  return show;
}

/** Runs `fn` when `key` changes, using stale-while-revalidate to never blank the screen. */
export function useRequest<T>(key: string | null, fn: () => Promise<T>): RequestState<T> {
  const cached = key ? (swrCache.get(key) as T | undefined) : undefined;
  const [data, setData] = useState<T | null>(cached ?? null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(key !== null && cached === undefined);
  const [tick, setTick] = useState(0);
  const fnRef = useRef(fn);
  fnRef.current = fn;

  useEffect(() => {
    if (key === null) {
      setLoading(false);
      return;
    }
    let live = true;
    const existing = swrCache.get(key) as T | undefined;
    if (existing !== undefined) {
      setData(existing);
      setLoading(false);
    } else {
      setLoading(true);
    }
    setError(null);

    fnRef
      .current()
      .then((d) => {
        if (!live) return;
        swrCache.set(key, d);
        setData(d);
      })
      .catch((e: Error) => {
        if (live) setError(e.message);
      })
      .finally(() => {
        if (live) setLoading(false);
      });

    return () => {
      live = false;
    };
  }, [key, tick]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  const updateData = useCallback(
    (d: T | null) => {
      if (key && d !== null) swrCache.set(key, d);
      setData(d);
    },
    [key],
  );

  return { data, error, loading, reload, setData: updateData };
}

/** Wraps a one-off action (button press) with pending + error state. */
export function useAction<A extends unknown[], R>(fn: (...args: A) => Promise<R>) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = useCallback(
    async (...args: A): Promise<R | undefined> => {
      setPending(true);
      setError(null);
      try {
        return await fn(...args);
      } catch (e) {
        setError((e as Error).message);
        return undefined;
      } finally {
        setPending(false);
      }
    },
    [fn],
  );
  return { run, pending, error, setError };
}
