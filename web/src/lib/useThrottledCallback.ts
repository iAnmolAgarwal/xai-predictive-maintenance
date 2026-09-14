import { useCallback, useEffect, useRef } from 'react';

/**
 * Leading + trailing throttle. The leading call fires immediately so a slider
 * feels instant; the trailing call guarantees the final value is never lost.
 */
export function useThrottledCallback<A extends unknown[]>(
  fn: (...args: A) => void,
  waitMs: number,
): (...args: A) => void {
  const fnRef = useRef(fn);
  fnRef.current = fn;
  const lastCallAt = useRef(0);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pending = useRef<A | null>(null);

  useEffect(
    () => () => {
      if (timer.current !== null) clearTimeout(timer.current);
    },
    [],
  );

  return useCallback(
    (...args: A) => {
      const now = Date.now();
      const elapsed = now - lastCallAt.current;
      if (elapsed >= waitMs) {
        lastCallAt.current = now;
        fnRef.current(...args);
        return;
      }
      pending.current = args;
      if (timer.current !== null) return;
      timer.current = setTimeout(() => {
        timer.current = null;
        lastCallAt.current = Date.now();
        const queued = pending.current;
        pending.current = null;
        if (queued) fnRef.current(...queued);
      }, waitMs - elapsed);
    },
    [waitMs],
  );
}

/** Trailing-only debounce, for input that should settle before it commits. */
export function useDebouncedCallback<A extends unknown[]>(
  fn: (...args: A) => void,
  waitMs: number,
): (...args: A) => void {
  const fnRef = useRef(fn);
  fnRef.current = fn;
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      if (timer.current !== null) clearTimeout(timer.current);
    },
    [],
  );

  return useCallback(
    (...args: A) => {
      if (timer.current !== null) clearTimeout(timer.current);
      timer.current = setTimeout(() => {
        timer.current = null;
        fnRef.current(...args);
      }, waitMs);
    },
    [waitMs],
  );
}
