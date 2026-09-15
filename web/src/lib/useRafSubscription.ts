import { useEffect, useRef } from 'react';

/**
 * Run `draw` on the next animation frame whenever `revision` changes, coalescing
 * several revisions inside one frame into a single call. Canvas surfaces use
 * this to redraw from a ring buffer without a React render.
 */
export function useRafSubscription(revision: number, draw: () => void): void {
  const drawRef = useRef(draw);
  drawRef.current = draw;

  useEffect(() => {
    let frame = requestAnimationFrame(() => {
      frame = 0;
      drawRef.current();
    });
    return () => {
      if (frame !== 0) cancelAnimationFrame(frame);
    };
  }, [revision]);
}
