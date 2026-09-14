import { useEffect } from 'react';
import { Outlet } from 'react-router';
import { RAIL_BREAKPOINT_PX } from '@/config';
import { useMediaQuery } from '@/lib/useMediaQuery';
import { useStore } from '@/store';
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

  useEffect(() => {
    setReducedMotion(prefersReducedMotion);
  }, [prefersReducedMotion, setReducedMotion]);

  useEffect(() => {
    // Docked at ≥ 1440 px, hidden-by-default as a drawer below it.
    setRailOpen(wideEnoughForRail);
  }, [wideEnoughForRail, setRailOpen]);

  const overlay = !wideEnoughForRail;
  const showRail = overlay ? railOpen : true;

  return (
    <div
      className={[styles.shell, overlay ? styles.shellNarrow : '']
        .filter(Boolean)
        .join(' ')}
      data-testid="app-shell"
      data-rail={overlay ? 'overlay' : 'docked'}
    >
      <TopBar
        railCollapsed={overlay}
        onToggleRail={() => {
          if (!railOpen) markAlertsSeen();
          toggleRail();
        }}
      />
      <main className={styles.main} data-testid="main-region" id="main-region">
        <Outlet />
      </main>
      {showRail ? (
        <RightRail overlay={overlay} open={railOpen} onClose={() => setRailOpen(false)} />
      ) : null}
      <LiveRegions />
    </div>
  );
}
