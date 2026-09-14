import { act, render, renderHook, waitFor } from '@testing-library/react';
import { useRef } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { useDebouncedCallback, useThrottledCallback } from '../useThrottledCallback';
import { useMediaQuery } from '../useMediaQuery';
import { useRafSubscription } from '../useRafSubscription';
import { useResizeObserver } from '../useResizeObserver';

describe('useThrottledCallback', () => {
  it('emits leading and trailing calls, coalescing the middle', () => {
    vi.useFakeTimers();
    const spy = vi.fn();
    const { result } = renderHook(() => useThrottledCallback(spy, 60));

    act(() => {
      result.current(1);
      result.current(2);
      result.current(3);
    });
    expect(spy).toHaveBeenCalledTimes(1);
    expect(spy).toHaveBeenLastCalledWith(1);

    act(() => {
      vi.advanceTimersByTime(60);
    });
    expect(spy).toHaveBeenCalledTimes(2);
    expect(spy).toHaveBeenLastCalledWith(3);
    vi.useRealTimers();
  });
});

describe('useDebouncedCallback', () => {
  it('only fires after the input settles', () => {
    vi.useFakeTimers();
    const spy = vi.fn();
    const { result } = renderHook(() => useDebouncedCallback(spy, 40));

    act(() => {
      result.current('a');
      vi.advanceTimersByTime(20);
      result.current('b');
      vi.advanceTimersByTime(39);
    });
    expect(spy).not.toHaveBeenCalled();

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(spy).toHaveBeenCalledExactlyOnceWith('b');
    vi.useRealTimers();
  });
});

describe('useRafSubscription', () => {
  it('redraws once per revision change, on an animation frame', async () => {
    const draw = vi.fn();
    const { rerender } = renderHook(({ revision }) => useRafSubscription(revision, draw), {
      initialProps: { revision: 1 },
    });
    await waitFor(() => expect(draw).toHaveBeenCalledTimes(1));

    rerender({ revision: 2 });
    await waitFor(() => expect(draw).toHaveBeenCalledTimes(2));

    rerender({ revision: 2 });
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(draw).toHaveBeenCalledTimes(2);
  });
});

describe('useResizeObserver', () => {
  it('reports the observed content box', async () => {
    const observers: Array<(entries: ResizeObserverEntry[]) => void> = [];
    vi.stubGlobal(
      'ResizeObserver',
      class {
        constructor(callback: (entries: ResizeObserverEntry[]) => void) {
          observers.push(callback);
        }
        observe(): void {}
        unobserve(): void {}
        disconnect(): void {}
      },
    );

    let size: { width: number; height: number } | null = null;
    function Probe() {
      const ref = useRef<HTMLDivElement | null>(null);
      size = useResizeObserver(ref);
      return <div ref={ref} />;
    }
    render(<Probe />);

    act(() => {
      observers[0]?.([
        { contentRect: { width: 640.4, height: 160.2 } } as ResizeObserverEntry,
      ]);
    });
    await waitFor(() => expect(size).toEqual({ width: 640, height: 160 }));
    vi.unstubAllGlobals();
  });
});

describe('useMediaQuery', () => {
  it('tracks the query and updates on change', () => {
    const listeners: Array<(event: MediaQueryListEvent) => void> = [];
    const list = {
      matches: false,
      media: '(min-width: 1440px)',
      addEventListener: (_: string, listener: (event: MediaQueryListEvent) => void) =>
        listeners.push(listener),
      removeEventListener: () => {},
    };
    vi.stubGlobal('matchMedia', () => list);

    const { result } = renderHook(() => useMediaQuery('(min-width: 1440px)'));
    expect(result.current).toBe(false);

    act(() => {
      listeners.forEach((listener) => listener({ matches: true } as MediaQueryListEvent));
    });
    expect(result.current).toBe(true);
    vi.unstubAllGlobals();
  });
});
