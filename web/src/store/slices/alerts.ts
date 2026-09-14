import { ALERT_CAP } from '@/config';
import type { Alert, AlertSeverity } from '@/contracts';
import { parseDatasetTs } from '@/lib/formatters';
import type { SliceCreator } from './types';

export type AlertFilters = {
  machineIds: string[];
  severities: AlertSeverity[];
  feature: string | null;
};

export type AlertsSlice = {
  alerts: {
    byId: Record<string, Alert>;
    /** newest first, capped at ALERT_CAP. */
    order: string[];
    filters: AlertFilters;
    unseenCount: number;
    nextCursor: string | null;
  };
  /** Live `alert` frames and REST backfill share one path. */
  addAlerts: (alerts: readonly Alert[], options?: { unseen?: boolean }) => void;
  setAlertFilters: (patch: Partial<AlertFilters>) => void;
  markAlertsSeen: () => void;
  setAlertsCursor: (cursor: string | null) => void;
  resetAlerts: () => void;
};

const emptyFilters = (): AlertFilters => ({ machineIds: [], severities: [], feature: null });

export const createAlertsSlice: SliceCreator<AlertsSlice> = (set) => ({
  alerts: {
    byId: {},
    order: [],
    filters: emptyFilters(),
    unseenCount: 0,
    nextCursor: null,
  },
  addAlerts: (incoming, options) =>
    set((state) => {
      if (incoming.length === 0) return {};
      const byId = { ...state.alerts.byId };
      for (const alert of incoming) byId[alert.alert_id] = alert;
      // Reverse-chronological by dataset time, which is the clock the UI sorts
      // on everywhere (R8); ties keep insertion order.
      const order = Object.keys(byId).sort((a, b) => {
        const alertA = byId[a];
        const alertB = byId[b];
        return (
          parseDatasetTs(alertB?.dataset_ts ?? null) -
          parseDatasetTs(alertA?.dataset_ts ?? null)
        );
      });
      const kept = order.slice(0, ALERT_CAP);
      if (kept.length < order.length) {
        for (const evicted of order.slice(ALERT_CAP)) delete byId[evicted];
      }
      const newlyUnseen =
        options?.unseen === true
          ? incoming.filter(
              (alert) =>
                alert.closed_dataset_ts === null &&
                state.alerts.byId[alert.alert_id] === undefined,
            ).length
          : 0;
      return {
        alerts: {
          ...state.alerts,
          byId,
          order: kept,
          unseenCount: state.alerts.unseenCount + newlyUnseen,
        },
      };
    }),
  setAlertFilters: (patch) =>
    set((state) => ({
      alerts: { ...state.alerts, filters: { ...state.alerts.filters, ...patch } },
    })),
  markAlertsSeen: () => set((state) => ({ alerts: { ...state.alerts, unseenCount: 0 } })),
  setAlertsCursor: (cursor) =>
    set((state) => ({ alerts: { ...state.alerts, nextCursor: cursor } })),
  resetAlerts: () =>
    set((state) => ({
      alerts: {
        byId: {},
        order: [],
        filters: state.alerts.filters,
        unseenCount: 0,
        nextCursor: null,
      },
    })),
});
