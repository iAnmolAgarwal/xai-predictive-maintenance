import { useEffect, useState } from 'react';
import type { RefObject } from 'react';

export type Size = { width: number; height: number };

/**
 * Observe an element's content box. Charts call `setSize` from this rather than
 * re-constructing themselves on resize.
 */
export function useResizeObserver(ref: RefObject<Element | null>): Size | null {
  const [size, setSize] = useState<Size | null>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry) return;
      const box = entry.contentRect;
      setSize({ width: Math.round(box.width), height: Math.round(box.height) });
    });
    observer.observe(el);
    return () => {
      observer.disconnect();
    };
  }, [ref]);

  return size;
}
