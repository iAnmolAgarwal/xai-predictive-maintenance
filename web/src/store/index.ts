/**
 * The Zustand store (frontend.md §3.3). One store, typed slices, no Provider.
 *
 * `subscribeWithSelector` is the only middleware: the 20x replay path writes
 * from a rAF callback outside React (`store.getState()`), and canvas draw calls
 * read imperatively. No `immer` (it cannot see typed arrays), no `persist`, and
 * `devtools` is deliberately absent from production builds.
 */
import { create } from 'zustand';
import { subscribeWithSelector } from 'zustand/middleware';
import { createAlertsSlice, type AlertsSlice } from './slices/alerts';
import { createConfigSlice, type ConfigSlice } from './slices/config';
import { createConnectionSlice, type ConnectionSlice } from './slices/connection';
import { createExplanationsSlice, type ExplanationsSlice } from './slices/explanations';
import { createMachinesSlice, type MachinesSlice } from './slices/machines';
import { createPlantsSlice, type PlantsSlice } from './slices/plants';
import { createPlaybackSlice, type PlaybackSlice } from './slices/playback';
import { createRiskSlice, type RiskSlice } from './slices/risk';
import { createTelemetrySlice, type TelemetrySlice } from './slices/telemetry';
import { createUiSlice, type UiSlice } from './slices/ui';
import { createWhatIfSlice, type WhatIfSlice } from './slices/whatif';

export type Store = ConnectionSlice &
  PlantsSlice &
  MachinesSlice &
  TelemetrySlice &
  RiskSlice &
  AlertsSlice &
  ExplanationsSlice &
  PlaybackSlice &
  WhatIfSlice &
  UiSlice &
  ConfigSlice;

export const useStore = create<Store>()(
  subscribeWithSelector((...args) => ({
    ...createConnectionSlice(...args),
    ...createPlantsSlice(...args),
    ...createMachinesSlice(...args),
    ...createTelemetrySlice(...args),
    ...createRiskSlice(...args),
    ...createAlertsSlice(...args),
    ...createExplanationsSlice(...args),
    ...createPlaybackSlice(...args),
    ...createWhatIfSlice(...args),
    ...createUiSlice(...args),
    ...createConfigSlice(...args),
  })),
);

/** The initial state, captured once so tests can restore it between cases. */
const initialState = useStore.getState();

/** Restore every slice to its initial state. Test-only; never called by the app. */
export function resetStore(): void {
  useStore.setState(initialState, true);
}

export type { ConnStatus } from './slices/connection';
export type { MachineLive } from './slices/machines';
export type { AlertFilters } from './slices/alerts';
export type { HistoricalState } from './slices/playback';
