import { useEffect, useRef, type RefObject } from 'react';
import { Badge } from '@/components/ui/Badge';
import { IconButton } from '@/components/ui/IconButton';
import { useStore } from '@/store';
import { Slot } from '../slots';
import styles from './RightRail.module.css';

/** Everything a keyboard can reach inside the drawer, in DOM order. */
const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * The alert rail. At ≥ 1440 px it is a fixed 360 px column; below that it is an
 * overlay drawer with an unread-count badge on its toggle (R8), so live alerts
 * are never silently missed.
 */
export function RightRail({
  overlay,
  open,
  onClose,
  returnFocusRef,
}: {
  overlay: boolean;
  open: boolean;
  onClose: () => void;
  /** Focus goes back to whatever opened the drawer, not to the document. */
  returnFocusRef?: RefObject<HTMLButtonElement | null>;
}) {
  const unseenCount = useStore((state) => state.alerts.unseenCount);
  const markAlertsSeen = useStore((state) => state.markAlertsSeen);
  const closeRef = useRef<HTMLButtonElement | null>(null);
  const railRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!overlay || !open) return;
    const onKeyDown = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') {
        onClose();
        return;
      }
      if (event.key !== 'Tab') return;
      // Modal drawer: Tab must not walk the page behind the overlay.
      const focusable = railRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE);
      if (!focusable || focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (!first || !last) return;
      const active = document.activeElement;
      if (event.shiftKey && (active === first || !railRef.current?.contains(active))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener('keydown', onKeyDown);
    closeRef.current?.focus();
    const opener = returnFocusRef;
    return () => {
      window.removeEventListener('keydown', onKeyDown);
      // Whoever opened the drawer gets focus back, so a keyboard user does not
      // lose their place when it closes.
      opener?.current?.focus();
    };
  }, [overlay, open, onClose, returnFocusRef]);

  if (overlay && !open) return null;

  return (
    <>
      {overlay ? (
        // A scrim: it dims the grid the drawer covers and gives the pointer the
        // same dismissal Escape already provides. It is deliberately not in the
        // accessibility tree or the tab order -- the drawer's own "Close alerts"
        // button and the Escape handler are the keyboard paths, so a second
        // control here would only add a duplicate name.
        <div
          aria-hidden="true"
          className={styles.scrim}
          data-testid="rail-scrim"
          onClick={onClose}
        />
      ) : null}
      <aside
        ref={railRef}
        id="right-rail"
        className={[styles.rail, overlay ? styles.overlay : ''].filter(Boolean).join(' ')}
        data-testid="right-rail"
        data-overlay={overlay ? 'true' : 'false'}
        aria-label="Alert feed"
        {...(overlay ? { role: 'dialog' as const, 'aria-modal': true } : {})}
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
    </>
  );
}
