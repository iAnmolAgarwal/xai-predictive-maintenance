import type {
  ChannelSpec,
  MachineSnapshot,
  MachineStatus,
  MachineSummary,
  RiskUpdate,
  TopFeature,
} from '@/contracts';
import { parseDatasetTs } from '@/lib/formatters';
import type { SliceCreator } from './types';

/** The hot, rAF-committed scalars a tile reads. */
export type MachineLive = {
  probability: number | null;
  status: MachineStatus;
  datasetTsMs: number;
  topFeatures: TopFeature[];
  revision: number;
};

export type MachinesSlice = {
  machines: {
    byId: Record<string, MachineSummary>;
    /** Canonical channel order for the selected plant. */
    channels: ChannelSpec[];
    /** Grid order, stable. */
    order: string[];
    live: Record<string, MachineLive>;
  };
  setChannels: (channels: readonly ChannelSpec[]) => void;
  /** Wholesale rebuild from a `snapshot` frame (R10). */
  seedMachines: (machines: readonly MachineSnapshot[]) => void;
  /** Commit a coalesced batch of `risk` updates, one per machine. */
  applyRiskUpdates: (updates: readonly RiskUpdate[]) => void;
};

export const createMachinesSlice: SliceCreator<MachinesSlice> = (set) => ({
  machines: { byId: {}, channels: [], order: [], live: {} },
  setChannels: (channels) =>
    set((state) => ({ machines: { ...state.machines, channels: [...channels] } })),
  seedMachines: (machines) =>
    set((state) => {
      const byId: Record<string, MachineSummary> = {};
      const live: Record<string, MachineLive> = {};
      const order: string[] = [];
      for (const machine of machines) {
        const { values: _values, ...summary } = machine;
        byId[machine.machine_id] = summary;
        live[machine.machine_id] = {
          probability: machine.probability,
          status: machine.status,
          datasetTsMs: parseDatasetTs(machine.dataset_ts),
          topFeatures: [],
          revision: 0,
        };
        order.push(machine.machine_id);
      }
      return { machines: { ...state.machines, byId, live, order } };
    }),
  applyRiskUpdates: (updates) =>
    set((state) => {
      if (updates.length === 0) return {};
      const live = { ...state.machines.live };
      const byId = { ...state.machines.byId };
      for (const update of updates) {
        const previous = live[update.machine_id];
        live[update.machine_id] = {
          probability: update.probability,
          status: update.status,
          datasetTsMs: parseDatasetTs(update.dataset_ts),
          topFeatures: update.top_features,
          revision: (previous?.revision ?? 0) + 1,
        };
        const summary = byId[update.machine_id];
        if (summary) {
          byId[update.machine_id] = {
            ...summary,
            status: update.status,
            probability: update.probability,
            dataset_ts: update.dataset_ts,
            open_alert_id: update.alert_id,
          };
        }
      }
      return { machines: { ...state.machines, live, byId } };
    }),
});
