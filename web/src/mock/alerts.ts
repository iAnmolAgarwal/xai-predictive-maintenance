/**
 * The alert corpus: 62 deterministic alerts across both plants, every severity
 * band and a spread of `top_feature` values, so the rail can page, filter and
 * deep-link without the fixture running out of rows. Roughly a third carry a
 * non-null `closed_dataset_ts` (the rail's "resolved" chip); the two demo alerts
 * never close.
 *
 * Alert ids, dataset times, probabilities and headlines are all functions of
 * `(plant_id, machine_id, tick)`, so `makeAlert` is a pure fixture builder and
 * the corpus is just a fixed schedule of calls to it.
 */
import type { Alert, AlertPage, AlertSeverity, PlantId } from '@/contracts';
import {
  CURRENT_TICK,
  DEMO_ALERT_ID,
  IMS_DEMO_ALERT_ID,
  datasetTsFor,
  demoMachineId,
  hexId,
  machineDisplayName,
  machineIdsFor,
  MODEL_ID,
  currentRunId,
  seededRandom,
} from './core';
import { explanationIdFor, headlineFor } from './explain';

/**
 * Dataset tick the demo machines' headline alert is stored against, in both
 * plants. It is `CURRENT_TICK`, the newest row, so the demo alert is the last one
 * its machine raised and is still open — `open_alert_id` on the plant floor, an
 * active explanation in `GET /api/state_at`, and the frame the socket sends six
 * ticks after connect.
 */
export const DEMO_ALERT_TICK = CURRENT_TICK;

/** Severity bands, `alerting.severity_bands.*`; the probability picks the band. */
function severityFor(probability: number): AlertSeverity {
  if (probability >= 0.9) return 'critical';
  if (probability >= 0.75) return 'high';
  return 'medium';
}

const DEMO_PROBABILITY: Record<PlantId, number> = { ai4i: 0.771, ims: 0.74 };

function alertIdFor(plantId: PlantId, machineId: string, tick: number): string {
  if (machineId === demoMachineId(plantId) && tick === DEMO_ALERT_TICK) {
    return plantId === 'ai4i' ? DEMO_ALERT_ID : IMS_DEMO_ALERT_ID;
  }
  return hexId('alt_', 16, plantId, machineId, tick);
}

/** Probabilities cycle through the three bands so every severity is represented. */
function probabilityForAlert(plantId: PlantId, machineId: string, tick: number): number {
  if (machineId === demoMachineId(plantId) && tick === DEMO_ALERT_TICK) {
    return DEMO_PROBABILITY[plantId];
  }
  const random = seededRandom(Number(machineId.slice(-2)) * 7919 + tick * 31);
  const band = (Number(machineId.slice(-2)) + tick) % 3;
  const ranges: Array<[number, number]> = [
    [0.61, 0.74],
    [0.76, 0.885],
    [0.905, 0.975],
  ];
  const [low, high] = ranges[band] ?? [0.61, 0.74];
  return Number((low + random() * (high - low)).toFixed(4));
}

/**
 * The tick an alert closes on, or `null` if it is still open.
 *
 * At most one alert per machine is open at any dataset instant (backend §3.4.1),
 * so an alert with a successor always closes before that successor opens. The
 * last alert of each demo machine is pinned open, which is what gives the plant
 * floor a non-null `open_alert_id` to deep-link at `CURRENT_TICK`.
 */
function closedTickFor(plantId: PlantId, machineId: string, tick: number): number | null {
  const ticks = ticksFor(plantId, machineId);
  // An alert raised on a row the schedule does not hold is a live alert someone
  // just built: freshly raised, therefore open.
  if (!ticks.includes(tick)) return null;
  const next = ticks.find((candidate) => candidate > tick) ?? null;
  const random = seededRandom(Number(machineId.slice(-2)) * 104729 + tick);
  const raw = random() > 0.38 ? null : tick + 3 + Math.floor(random() * 10);
  if (next === null) {
    return machineId === demoMachineId(plantId) ? null : raw;
  }
  return Math.min(raw ?? next - 1, next - 1);
}

export function makeAlert(plantId: PlantId, machineId: string, tick: number): Alert {
  const probability = probabilityForAlert(plantId, machineId, tick);
  const closedTick = closedTickFor(plantId, machineId, tick);
  const datasetTs = datasetTsFor(plantId, tick);
  const partial: Alert = {
    alert_id: alertIdFor(plantId, machineId, tick),
    run_id: currentRunId(),
    plant_id: plantId,
    machine_id: machineId,
    machine_display_name: machineDisplayName(plantId, machineId),
    // `ts` is wall-clock emit time on the wire; the mock derives it from dataset
    // time so two runs of the same fixture are byte-identical.
    ts: new Date(Date.parse(datasetTs) + 1200).toISOString(),
    dataset_ts: datasetTs,
    model_id: MODEL_ID,
    probability,
    severity: severityFor(probability),
    headline: '',
    top_feature: '',
    explanation_id: '',
    closed_dataset_ts: closedTick === null ? null : datasetTsFor(plantId, closedTick),
  };
  const { headline, topFeature } = headlineFor(partial);
  return {
    ...partial,
    headline,
    top_feature: topFeature,
    explanation_id: explanationIdFor(partial, 'lgbm'),
  };
}

/* ── The schedule ──────────────────────────────────────────────────────────── */

/** Alerts per machine; the demo machines carry enough history for the beeswarm. */
function alertCountFor(plantId: PlantId, machineId: string): number {
  if (machineId === demoMachineId(plantId)) return plantId === 'ai4i' ? 20 : 8;
  // `ims-04` is the offline machine: it has published nothing, so it can have
  // raised nothing.
  if (machineId === 'ims-04') return 0;
  // AI4I stays at 42 alerts in total, one page below the default `limit=50`, so
  // an unfiltered first page of the demo plant is complete and `next_cursor` is
  // null; paging is exercised by asking for a smaller `limit`.
  return plantId === 'ai4i' ? 2 : 6;
}

function ticksFor(plantId: PlantId, machineId: string): number[] {
  const count = alertCountFor(plantId, machineId);
  if (count === 0) return [];
  const random = seededRandom(
    Number(machineId.slice(-2)) * 15485863 + (plantId === 'ims' ? 7 : 3),
  );
  const ticks = new Set<number>();
  if (machineId === demoMachineId(plantId)) ticks.add(DEMO_ALERT_TICK);
  let guard = 0;
  while (ticks.size < count && guard < 2000) {
    guard += 1;
    const candidate = 8 + Math.floor(random() * (CURRENT_TICK - 16));
    // Keep alerts at least three rows apart, so a closing row always exists
    // strictly between one alert and the next.
    if ([...ticks].some((existing) => Math.abs(existing - candidate) < 3)) continue;
    ticks.add(candidate);
  }
  return [...ticks].sort((a, b) => a - b);
}

type CorpusEntry = { alert: Alert; tick: number; closedTick: number | null };

function buildCorpus(): CorpusEntry[] {
  const entries: CorpusEntry[] = [];
  for (const plantId of ['ai4i', 'ims'] as const) {
    for (const machineId of machineIdsFor(plantId)) {
      for (const tick of ticksFor(plantId, machineId)) {
        entries.push({
          alert: makeAlert(plantId, machineId, tick),
          tick,
          closedTick: closedTickFor(plantId, machineId, tick),
        });
      }
    }
  }
  // Newest first: the order the rail renders and the cursor pages through.
  return entries.sort(
    (a, b) =>
      Date.parse(b.alert.dataset_ts) - Date.parse(a.alert.dataset_ts) ||
      a.alert.alert_id.localeCompare(b.alert.alert_id),
  );
}

const CORPUS = buildCorpus();

/** Every fixture alert, newest dataset time first. */
export function allAlerts(): Alert[] {
  return CORPUS.map((entry) => entry.alert);
}

export function findAlert(alertId: string): Alert | undefined {
  return CORPUS.find((entry) => entry.alert.alert_id === alertId)?.alert;
}

export function alertsForMachine(machineId: string): Alert[] {
  return CORPUS.filter((entry) => entry.alert.machine_id === machineId).map(
    (entry) => entry.alert,
  );
}

/** The machine's open alert at `tick`, or null — at most one is open (backend §3.4.1). */
export function openAlertAt(machineId: string, tick: number): Alert | null {
  const open = CORPUS.filter(
    (entry) =>
      entry.alert.machine_id === machineId &&
      entry.tick <= tick &&
      (entry.closedTick === null || entry.closedTick > tick),
  );
  return open[0]?.alert ?? null;
}

/** `dataset_ts <= t AND (closed_dataset_ts IS NULL OR closed_dataset_ts > t)`. */
export function activeAlertsAt(plantId: PlantId, tick: number): Alert[] {
  return CORPUS.filter(
    (entry) =>
      entry.alert.plant_id === plantId &&
      entry.tick <= tick &&
      (entry.closedTick === null || entry.closedTick > tick),
  ).map((entry) => entry.alert);
}

/** The tick an alert was raised on, for lining markers up with a risk series. */
export function tickOfAlert(alertId: string): number | null {
  return CORPUS.find((entry) => entry.alert.alert_id === alertId)?.tick ?? null;
}

/* ── Filtering and paging ──────────────────────────────────────────────────── */

export type AlertQuery = {
  plant_id?: string | null;
  machine_id?: string | null;
  since?: string | null;
  until?: string | null;
  severity?: string | null;
  feature?: string | null;
  limit?: number | null;
  cursor?: string | null;
};

/** Opaque to the client; encodes (dataset_ts_ms, alert_id) exactly as the API's does. */
function encodeCursor(alert: Alert): string {
  return `c_${Date.parse(alert.dataset_ts)}_${alert.alert_id}`;
}

export const DEFAULT_ALERT_LIMIT = 50;

export function queryAlerts(query: AlertQuery): AlertPage {
  const limit = Math.min(200, Math.max(1, Math.trunc(query.limit ?? DEFAULT_ALERT_LIMIT)));
  const sinceMs = query.since ? Date.parse(query.since) : null;
  const untilMs = query.until ? Date.parse(query.until) : null;

  let items = allAlerts().filter((alert) => {
    if (query.plant_id && alert.plant_id !== query.plant_id) return false;
    if (query.machine_id && alert.machine_id !== query.machine_id) return false;
    if (query.severity && alert.severity !== query.severity) return false;
    if (query.feature && alert.top_feature !== query.feature) return false;
    const ms = Date.parse(alert.dataset_ts);
    if (sinceMs !== null && ms < sinceMs) return false;
    if (untilMs !== null && ms > untilMs) return false;
    return true;
  });

  if (query.cursor) {
    const index = items.findIndex((alert) => encodeCursor(alert) === query.cursor);
    items = index === -1 ? [] : items.slice(index + 1);
  }

  const page = items.slice(0, limit);
  const last = page[page.length - 1];
  return {
    items: page,
    next_cursor: last && items.length > limit ? encodeCursor(last) : null,
    limit,
  };
}

/** The dataset tick a machine's alerts fall on, for the risk timeline markers. */
export function markerTicks(machineId: string): Array<{ alert: Alert; tick: number }> {
  return CORPUS.filter((entry) => entry.alert.machine_id === machineId).map((entry) => ({
    alert: entry.alert,
    tick: entry.tick,
  }));
}
