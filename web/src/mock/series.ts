/**
 * The columnar series, the beeswarm aggregate, the historical snapshot and the
 * model registry.
 *
 * Series answer from the dataset clock, never the wall clock: the default window
 * is the `CURRENT_TICK` rows ending at `CURRENT_TICK`, so the same request always
 * returns the same payload. `since`/`until` resolve to row boundaries, and when
 * the requested span holds more rows than `max_points` the mock decimates with a
 * fixed stride and says so through `downsampled: true`.
 */
import type {
  AlertMarker,
  GlobalImportance,
  ImportanceFeature,
  MachineDetail,
  ModelInfo,
  PlantId,
  PlantSnapshot,
  RiskSeries,
  TelemetrySeries,
} from '@/contracts';
import { activeAlertsAt, alertsForMachine, markerTicks } from './alerts';
import { catalogFor } from './catalog';
import {
  CURRENT_TICK,
  MAX_SERIES_POINTS,
  MODEL_ID,
  N_FEATURES,
  RF_MODEL_ID,
  ROW_COUNT,
  channelsFor,
  currentRunId,
  datasetTsFor,
  makeChannelValues,
  makePlant,
  MOCK_SEED,
  seededRandom,
  statusFor,
  tickAt,
} from './core';
import { makeExplanation } from './explain';
import {
  isScored,
  makeMachineSummary,
  makeMachineSummaries,
  probabilityFor,
} from './machines';

/** How many rows the default (no `since`) window covers. */
const DEFAULT_WINDOW_ROWS = 200;

export type SeriesRange = {
  since?: string | null;
  until?: string | null;
  max_points?: number | null;
};

export class UnknownChannelError extends Error {
  readonly unknown: string[];

  constructor(unknown: string[]) {
    super(`unknown channel(s): ${unknown.join(', ')}`);
    this.name = 'UnknownChannelError';
    this.unknown = unknown;
  }
}

function resolveTicks(
  plantId: PlantId,
  range: SeriesRange,
): { ticks: number[]; maxPoints: number; downsampled: boolean } {
  const untilTick = range.until ? tickAt(plantId, range.until) : CURRENT_TICK;
  const sinceTick = range.since
    ? tickAt(plantId, range.since)
    : Math.max(0, untilTick - DEFAULT_WINDOW_ROWS + 1);
  const low = Math.max(0, Math.min(sinceTick, untilTick));
  const high = Math.min(ROW_COUNT, Math.max(sinceTick, untilTick));
  const maxPoints = Math.min(
    MAX_SERIES_POINTS,
    Math.max(2, Math.trunc(range.max_points ?? MAX_SERIES_POINTS)),
  );

  const total = high - low + 1;
  const stride = total > maxPoints ? Math.ceil(total / maxPoints) : 1;
  const ticks: number[] = [];
  for (let tick = low; tick <= high; tick += stride) ticks.push(tick);
  return { ticks, maxPoints, downsampled: stride > 1 };
}

/** `channels=a,b` and the repeated `channels=a&channels=b` form both work. */
export function parseChannels(values: string[]): string[] {
  return values
    .flatMap((value) => value.split(','))
    .map((name) => name.trim())
    .filter((name) => name !== '');
}

export function makeTelemetrySeries(
  plantId: PlantId,
  machineId: string,
  range: SeriesRange & { channels?: string[] },
): TelemetrySeries {
  const all = channelsFor(plantId);
  const requested = range.channels && range.channels.length > 0 ? range.channels : null;
  if (requested) {
    const unknown = requested.filter(
      (name) => !all.some((channel) => channel.name === name),
    );
    if (unknown.length > 0) throw new UnknownChannelError(unknown);
  }
  // Canonical order is preserved whatever order the caller asked in.
  const selected = all.filter((channel) => !requested || requested.includes(channel.name));

  const { ticks, maxPoints, downsampled } = resolveTicks(plantId, range);
  const channels: Record<string, Array<number | null>> = {};
  for (const channel of selected) channels[channel.name] = [];
  for (const tick of ticks) {
    const values = makeChannelValues(plantId, machineId, tick);
    for (const channel of selected) {
      const index = all.findIndex((entry) => entry.name === channel.name);
      channels[channel.name]?.push(values[index] ?? null);
    }
  }

  return {
    machine_id: machineId,
    plant_id: plantId,
    dataset_ts: ticks.map((tick) => datasetTsFor(plantId, tick)),
    channels,
    n_points: ticks.length,
    max_points: maxPoints,
    downsampled,
  };
}

export function makeRiskSeries(
  plantId: PlantId,
  machineId: string,
  range: SeriesRange,
): RiskSeries {
  const resolved = resolveTicks(plantId, range);
  const downsampled = resolved.downsampled;
  // `RiskSeries.probability` is `list[float]`, with no null member: a row the
  // machine was not scored for is not emitted at all rather than sent as a zero.
  const ticks = resolved.ticks.filter((tick) => isScored(machineId, tick));
  const kept = new Set(ticks);
  const probability = ticks.map((tick) => probabilityFor(machineId, tick));
  const status = ticks.map((tick) => statusFor(probabilityFor(machineId, tick)));
  // A marker only ships when its row survived the decimation, so every glyph has
  // a point on the curve underneath it.
  const alerts: AlertMarker[] = markerTicks(machineId)
    .filter((entry) => kept.has(entry.tick))
    .map((entry) => ({
      alert_id: entry.alert.alert_id,
      dataset_ts: entry.alert.dataset_ts,
      severity: entry.alert.severity,
      probability: entry.alert.probability,
    }));

  return {
    machine_id: machineId,
    plant_id: plantId,
    model_id: MODEL_ID,
    dataset_ts: ticks.map((tick) => datasetTsFor(plantId, tick)),
    probability,
    status,
    alerts,
    n_points: ticks.length,
    downsampled,
  };
}

export function makeMachineDetail(
  plantId: PlantId,
  machineId: string,
  tick: number,
): MachineDetail {
  return {
    ...makeMachineSummary(plantId, machineId, tick),
    channels: channelsFor(plantId),
    alert_count: alertsForMachine(machineId).length,
    variant_mix: plantId === 'ai4i' ? { L: 612, M: 287, H: 101 } : null,
    bearing: plantId === 'ims' ? Number(machineId.slice(-2)) : null,
  };
}

/** Beeswarm input: one row per alert this machine raised, per ranked feature. */
export function makeImportance(
  plantId: PlantId,
  machineId: string,
  options: { since?: string | null; until?: string | null; limit?: number | null },
): GlobalImportance {
  const sinceMs = options.since ? Date.parse(options.since) : null;
  const untilMs = options.until ? Date.parse(options.until) : null;
  const alerts = alertsForMachine(machineId).filter((alert) => {
    const ms = Date.parse(alert.dataset_ts);
    if (sinceMs !== null && ms < sinceMs) return false;
    if (untilMs !== null && ms > untilMs) return false;
    return true;
  });
  const limit = Math.min(50, Math.max(1, Math.trunc(options.limit ?? 20)));

  const features: ImportanceFeature[] = catalogFor(plantId)
    .slice(0, limit)
    .map((meta, index) => {
      const random = seededRandom(index * 7919 + machineId.length * 104729 + MOCK_SEED);
      const scale = Math.pow(0.88, index) * 0.3;
      const points = alerts.map((alert) => {
        const swing = (random() - 0.35) * 2;
        return {
          shap: Number((scale * swing * (meta.direction === 'down' ? -1 : 1)).toFixed(5)),
          value_percentile: Number((random() * 100).toFixed(2)),
          alert_id: alert.alert_id,
        };
      });
      const meanAbs =
        points.length === 0
          ? 0
          : points.reduce((sum, point) => sum + Math.abs(point.shap), 0) / points.length;
      return {
        feature: meta.feature,
        display_name: meta.display_name,
        mean_abs_shap: Number(meanAbs.toFixed(5)),
        points,
      };
    })
    .sort((a, b) => b.mean_abs_shap - a.mean_abs_shap);

  return { machine_id: machineId, n_alerts: alerts.length, features };
}

/** `GET /api/state_at`: the plant exactly as it stood on the row at or before `t`. */
export function makeStateAt(plantId: PlantId, datasetTs: string): PlantSnapshot {
  const tick = tickAt(plantId, datasetTs);
  const active = activeAlertsAt(plantId, tick);
  return {
    plant_id: plantId,
    run_id: currentRunId(),
    dataset_ts: datasetTsFor(plantId, tick),
    machines: makeMachineSummaries(plantId, tick),
    active_alerts: active,
    // Read from storage, never recomputed: the explanation stored with the alert.
    active_explanations: active.map((alert) => makeExplanation(alert, 'lgbm')),
  };
}

const TRAINED_AT = '2026-01-04T09:12:00.000Z';

/** The registry the compare panel's header reads (`model_id`, `family`, `n_features`). */
export function makeModels(): ModelInfo[] {
  const plant = makePlant('ai4i');
  return [
    {
      model_id: MODEL_ID,
      family: 'lgbm',
      version: '1.0.0',
      plant_id: plant.plant_id,
      trained_at: TRAINED_AT,
      seed: MOCK_SEED,
      n_features: N_FEATURES,
      n_train_rows: 41_820,
      is_served: true,
      metrics: { pr_auc: 0.771, recall_at_p80: 0.642, brier: 0.051, ece: 0.032 },
      model_card_path: 'models/registry/lgbm/1.0.0/model_card.md',
    },
    {
      model_id: RF_MODEL_ID,
      family: 'rf',
      version: '1.0.0',
      plant_id: plant.plant_id,
      trained_at: TRAINED_AT,
      seed: MOCK_SEED,
      n_features: N_FEATURES,
      n_train_rows: 41_820,
      is_served: false,
      metrics: { pr_auc: 0.724, recall_at_p80: 0.588, brier: 0.058, ece: 0.047 },
      model_card_path: 'models/registry/rf/1.0.0/model_card.md',
    },
  ];
}
