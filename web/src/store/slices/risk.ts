import { CAPACITY } from '@/config';
import type { SliceCreator } from './types';

export type RiskSlice = {
  risk: { revision: Record<string, number>; capacity: number };
  bumpRiskRevisions: (machineIds: readonly string[]) => void;
  resetRiskRevisions: (machineIds: readonly string[]) => void;
};

export const createRiskSlice: SliceCreator<RiskSlice> = (set) => ({
  risk: { revision: {}, capacity: CAPACITY },
  bumpRiskRevisions: (machineIds) =>
    set((state) => {
      if (machineIds.length === 0) return {};
      const revision = { ...state.risk.revision };
      for (const id of machineIds) revision[id] = (revision[id] ?? 0) + 1;
      return { risk: { ...state.risk, revision } };
    }),
  resetRiskRevisions: (machineIds) =>
    set((state) => {
      const revision: Record<string, number> = {};
      for (const id of machineIds) revision[id] = 0;
      return { risk: { ...state.risk, revision } };
    }),
});
