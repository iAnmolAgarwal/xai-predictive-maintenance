import { useEffect, useRef } from 'react';
import { Outlet } from 'react-router';
import { RAIL_BREAKPOINT_PX } from '@/config';
import { useMediaQuery } from '@/lib/useMediaQuery';
import { useStore } from '@/store';
import { ConnectionBanner } from './ConnectionBanner';
import { LiveRegions } from './LiveRegions';
import { RightRail } from './RightRail';
import { TopBar } from './TopBar';
import styles from './AppLayout.module.css';

/**
 * The three-region chrome: top bar, main region (the router outlet) and the
 * right rail. A CSS grid with a fixed `--rail-w` column that collapses to an
 * overlay drawer below 1440 px (R8).
 *
 * It subscribes to nothing that streams, so telemetry never re-renders the
 * chrome.
 */
export function AppLayout() {
  const wideEnoughForRail = useMediaQuery(`(min-width: ${String(RAIL_BREAKPOINT_PX)}px)`);
  const prefersReducedMotion = useMediaQuery('(prefers-reduced-motion: reduce)');
  const railOpen = useStore((state) => state.ui.railOpen);
  const setRailOpen = useStore((state) => state.setRailOpen);
  const toggleRail = useStore((state) => state.toggleRail);
  const markAlertsSeen = useStore((state) => state.markAlertsSeen);
  const setReducedMotion = useStore((state) => state.setReducedMotion);
  const railToggleRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    setReducedMotion(prefersReducedMotion);
  }, [prefersReducedMotion, setReducedMotion]);

  useEffect(() => {
    // Docked at ≥ 1440 px, hidden-by-default as a drawer below it.
    setRailOpen(wideEnoughForRail);
  }, [wideEnoughForRail, setRailOpen]);

  const overlay = !wideEnoughForRail;
  const showRail = overlay ? railOpen : true;
  const modalOpen = overlay && railOpen;

  return (
    <div
      className={[styles.shell, overlay ? styles.shellNarrow : '']
        .filter(Boolean)
        .join(' ')}
      data-testid="app-shell"
      data-rail={overlay ? 'overlay' : 'docked'}
    >
      <a className={styles.skipLink} href="#main-region">
        Skip to main content
      </a>
      <TopBar
        railCollapsed={overlay}
        railToggleRef={railToggleRef}
        onToggleRail={() => {
          if (!railOpen) markAlertsSeen();
          toggleRail();
        }}
      />
      {/* `inert` keeps the hidden grid out of the tab order and the a11y tree
          while the drawer is open. */}
      <main
        className={styles.main}
        data-testid="main-region"
        id="main-region"
        inert={modalOpen}
      >
        <ConnectionBanner />
        <Outlet />
      </main>
      {showRail ? (
        <RightRail
          overlay={overlay}
          open={railOpen}
          onClose={() => setRailOpen(false)}
          returnFocusRef={railToggleRef}
        />
      ) : null}
      <LiveRegions />
    </div>
  );
}
