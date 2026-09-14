/** Shared testid selectors for the Playwright suites (frontend.md §4.2). */
export const testIds = {
  appShell: 'app-shell',
  topBar: 'top-bar',
  mainRegion: 'main-region',
  rightRail: 'right-rail',
  connectionPill: 'connection-pill',
  runId: 'run-id',
  plantSelect: 'plant-select',
  machineGrid: 'machine-grid',
  machineDetail: 'machine-detail',
  demoLink: 'floor-demo-link',
} as const;

/** The placeholder tile the shell draws before the plant-floor feature exists. */
export const placeholderTile = (machineId: string): string =>
  `floor-placeholder-tile-${machineId}`;
