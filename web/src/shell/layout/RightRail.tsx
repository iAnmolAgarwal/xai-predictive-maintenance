import { useEffect, useRef } from 'react';
import { Badge } from '@/components/ui/Badge';
import { IconButton } from '@/components/ui/IconButton';
import { useStore } from '@/store';
import { Slot } from '../slots';
import styles from './RightRail.module.css';

/**
 * The alert rail. At ≥ 1440 px it is a fixed 360 px column; below that it is an
 * overlay drawer with an unread-count badge on its toggle (R8), so live alerts
 * are never silently missed.
 */
export function RightRail({
  overlay,
  open,
  onClose,
}: {
  overlay: boolean;
  open: boolean;
  onClose: () => void;
}) {
  const unseenCount = useStore((state) => state.alerts.unseenCount);
  const markAlertsSeen = useStore((state) => state.markAlertsSeen);
  const closeRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    if (!overlay || !open) return;
    const onKeyDown = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKeyDown);
    closeRef.current?.focus();
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [overlay, open, onClose]);

  if (overlay && !open) return null;

  return (
    <aside
      id="right-rail"
      className={[styles.rail, overlay ? styles.overlay : ''].filter(Boolean).join(' ')}
      data-testid="right-rail"
      data-overlay={overlay ? 'true' : 'false'}
      aria-label="Alert feed"
    >
      <div className={styles.header}>
        <h2 className={styles.title}>
          Alerts
          {unseenCount > 0 ? (
            <Badge tone="count" data-testid="rail-unread-count">
              {unseenCount}
            </Badge>
          ) : null}
        </h2>
        <div className={styles.headerActions}>
          {unseenCount > 0 ? (
            <IconButton
              label="Mark alerts as seen"
              glyph="✓"
              onClick={() => markAlertsSeen()}
            />
          ) : null}
          {overlay ? (
            <IconButton ref={closeRef} label="Close alerts" glyph="✕" onClick={onClose} />
          ) : null}
        </div>
      </div>
      <div className={styles.body}>
        <Slot name="rail.feed" />
      </div>
    </aside>
  );
}
