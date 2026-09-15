import { CAPACITY } from '@/config';
import type { SliceCreator } from './types';

/**
 * The samples themselves live in the module-level ring buffers
 * (`store/ringBuffer.ts`); the store carries only the integer revision that
 * tells a chart to redraw.
 */
export type TelemetrySlice = {
  telemetry: { revision: Record<string, number>; capacity: number };
  bumpTelemetryRevisions: (machineIds: readonly string[]) => void;
  resetTelemetryRevisions: (machineIds: readonly string[]) => void;
};

export const createTelemetrySlice: SliceCreator<TelemetrySlice> = (set) => ({
  telemetry: { revision: {}, capacity: CAPACITY },
  bumpTelemetryRevisions: (machineIds) =>
    set((state) => {
      if (machineIds.length === 0) return {};
      const revision = { ...state.telemetry.revision };
      for (const id of machineIds) revision[id] = (revision[id] ?? 0) + 1;
      return { telemetry: { ...state.telemetry, revision } };
    }),
  resetTelemetryRevisions: (machineIds) =>
    set((state) => {
      const revision: Record<string, number> = {};
      for (const id of machineIds) revision[id] = 0;
      return { telemetry: { ...state.telemetry, revision } };
    }),
});
