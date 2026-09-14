/**
 * Deterministic replay fixtures shaped by `contracts/openapi.json` and
 * `contracts/ws-schema.json`. Ids use the real backend forms (`ai4i-03`,
 * `alt_9f2c71ab40d3e155`, `run_1a2b3c4d5e6f`, `lgbm@1.0.0`) and the channel table
 * is the backend's, so a fixture can never teach the frontend a shape the API
 * does not emit.
 *
 * This module is mock-only and must never reach a production bundle; the marker
 * below is what `no-mock-in-prod` greps the built assets for.
 */
import type {
  Alert,
  ChannelSpec,
  ConfigResponse,
  Explanation,
  HealthResponse,
  MachineSnapshot,
  MachineSummary,
  Plant,
  PlantId,
  ReplayState,
} from '@/contracts';

export const MOCK_MARKER = '__MSW_MOCK_MARKER__';

export const RUN_ID = 'run_1a2b3c4d5e6f';
export const MODEL_ID = 'lgbm@1.0.0';
export const DEMO_ALERT_ID = 'alt_9f2c71ab40d3e155';
export const DEMO_EXPLANATION_ID = 'exp_31c0a7f9b2d4e680';
export const DATASET_START = '2026-01-01T00:00:00.000Z';

/** AI4I 2020 milling plant — backend.md §3.1, canonical order. */
export const AI4I_CHANNELS: ChannelSpec[] = [
  { name: 'air_temp', display_name: 'Air Temperature', unit: 'K', vibration_like: false, nominal_min: 294, nominal_max: 306 },
  { name: 'process_temp', display_name: 'Process Temperature', unit: 'K', vibration_like: false, nominal_min: 304, nominal_max: 315 },
  { name: 'temp_diff', display_name: 'Temperature Difference', unit: 'K', vibration_like: false, nominal_min: 6, nominal_max: 14 },
  { name: 'rot_speed', display_name: 'Rotational Speed', unit: 'rpm', vibration_like: false, nominal_min: 1100, nominal_max: 2900 },
  { name: 'torque', display_name: 'Torque', unit: 'N·m', vibration_like: false, nominal_min: 0, nominal_max: 80 },
  { name: 'power', display_name: 'Mechanical Power', unit: 'W', vibration_like: false, nominal_min: 2000, nominal_max: 14000 },
  { name: 'tool_wear', display_name: 'Tool Wear', unit: 'min', vibration_like: false, nominal_min: 0, nominal_max: 260 },
];

/** NASA IMS bearing plant — 9 channels, six of them vibration-like. */
export const IMS_CHANNELS: ChannelSpec[] = [
  { name: 'vibration_0k5khz', display_name: 'Vibration @ 0.5 kHz', unit: 'g²/Hz', vibration_like: true, nominal_min: 0, nominal_max: 0.05 },
  { name: 'vibration_1khz', display_name: 'Vibration @ 1 kHz', unit: 'g²/Hz', vibration_like: true, nominal_min: 0, nominal_max: 0.05 },
  { name: 'vibration_2khz', display_name: 'Vibration @ 2 kHz', unit: 'g²/Hz', vibration_like: true, nominal_min: 0, nominal_max: 0.02 },
  { name: 'vibration_3khz', display_name: 'Vibration @ 3 kHz', unit: 'g²/Hz', vibration_like: true, nominal_min: 0, nominal_max: 0.02 },
  { name: 'vibration_5khz', display_name: 'Vibration @ 5 kHz', unit: 'g²/Hz', vibration_like: true, nominal_min: 0, nominal_max: 0.01 },
  { name: 'vibration_8khz', display_name: 'Vibration @ 8 kHz', unit: 'g²/Hz', vibration_like: true, nominal_min: 0, nominal_max: 0.01 },
  { name: 'vibration_rms', display_name: 'Vibration RMS', unit: 'g', vibration_like: true, nominal_min: 0, nominal_max: 2 },
  { name: 'vibration_kurtosis', display_name: 'Vibration Kurtosis', unit: '', vibration_like: false, nominal_min: 1.5, nominal_max: 12 },
  { name: 'vibration_crest', display_name: 'Vibration Crest Factor', unit: '', vibration_like: false, nominal_min: 2, nominal_max: 12 },
];

const PLANT_SHAPE = {
  ai4i: {
    display_name: 'AI4I 2020 Milling Plant',
    machine_count: 12,
    row_interval_seconds: 300,
    demo_machine_id: 'ai4i-03',
    channels: AI4I_CHANNELS,
    machine_prefix: 'Mill',
  },
  ims: {
    display_name: 'NASA IMS Bearing Test Rig',
    machine_count: 4,
    row_interval_seconds: 600,
    demo_machine_id: 'ims-01',
    channels: IMS_CHANNELS,
    machine_prefix: 'Bearing',
  },
} as const;

export function makePlant(plantId: PlantId): Plant {
  const shape = PLANT_SHAPE[plantId];
  return {
    plant_id: plantId,
    display_name: shape.display_name,
    machine_count: shape.machine_count,
    available: true,
    unavailable_reason: null,
    channels: shape.channels.map((channel) => ({ ...channel })),
    dataset_start: DATASET_START,
    dataset_end: isoAt(DATASET_START, shape.row_interval_seconds * 600),
    row_interval_seconds: shape.row_interval_seconds,
    demo_machine_id: shape.demo_machine_id,
  };
}

export const PLANTS: Plant[] = [makePlant('ai4i'), makePlant('ims')];

export function machineIdsFor(plantId: PlantId): string[] {
  const { machine_count: count } = PLANT_SHAPE[plantId];
  return Array.from(
    { length: count },
    (_, index) => `${plantId}-${String(index + 1).padStart(2, '0')}`,
  );
}

/** mulberry32: a tiny deterministic PRNG, so every run of the mock is identical. */
export function seededRandom(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function isoAt(start: string, seconds: number): string {
  return new Date(Date.parse(start) + seconds * 1000).toISOString();
}

export function datasetTsFor(plantId: PlantId, tick: number): string {
  return isoAt(DATASET_START, PLANT_SHAPE[plantId].row_interval_seconds * tick);
}

function statusFor(probability: number): MachineSummary['status'] {
  if (probability >= 0.6) return 'alert';
  if (probability >= 0.35) return 'watch';
  return 'healthy';
}

/** A machine's probability at `tick`: deterministic, and the demo machine fails. */
export function probabilityFor(machineId: string, tick: number): number {
  const index = Number(machineId.slice(-2));
  const random = seededRandom(index * 7919 + tick);
  const drift =
    machineId === 'ai4i-03' || machineId === 'ims-01' ? Math.min(0.9, tick * 0.02) : 0;
  return Math.min(0.99, Math.max(0.01, 0.08 + drift + random() * 0.12));
}

export function makeMachineSummary(
  plantId: PlantId,
  machineId: string,
  tick: number,
): MachineSummary {
  const probability = probabilityFor(machineId, tick);
  const index = Number(machineId.slice(-2));
  // `ims-04` stands in for a machine that has stopped publishing: status comes
  // from the backend, never synthesised in the frontend.
  const offline = machineId === 'ims-04';
  return {
    machine_id: machineId,
    plant_id: plantId,
    display_name: `${PLANT_SHAPE[plantId].machine_prefix} ${String(index).padStart(2, '0')}`,
    status: offline ? 'offline' : statusFor(probability),
    probability: offline ? null : probability,
    dataset_ts: datasetTsFor(plantId, tick),
    open_alert_id: machineId === 'ai4i-03' && tick > 20 ? DEMO_ALERT_ID : null,
    risk_sparkline: Array.from({ length: 60 }, (_, i) => {
      const sampleTick = tick - 59 + i;
      if (offline || sampleTick < 0) return null;
      return probabilityFor(machineId, sampleTick);
    }),
  };
}

export function makeChannelValues(
  plantId: PlantId,
  machineId: string,
  tick: number,
): Array<number | null> {
  const channels = PLANT_SHAPE[plantId].channels;
  const random = seededRandom(Number(machineId.slice(-2)) * 104729 + tick);
  return channels.map((channel, index) => {
    // One deliberate hole in the data, so the null-is-a-gap path is exercised.
    if (machineId === 'ims-04') return null;
    const span = channel.nominal_max - channel.nominal_min;
    const wave = Math.sin((tick + index * 3) / 6) * 0.25 + 0.5;
    return channel.nominal_min + span * (wave + (random() - 0.5) * 0.08);
  });
}

export function makeSnapshotMachines(plantId: PlantId, tick: number): MachineSnapshot[] {
  return machineIdsFor(plantId).map((machineId) => ({
    ...makeMachineSummary(plantId, machineId, tick),
    values: makeChannelValues(plantId, machineId, tick),
  }));
}

export function makeReplayState(plantId: PlantId, tick: number): ReplayState {
  const plant = makePlant(plantId);
  return {
    run_id: RUN_ID,
    plant_id: plantId,
    seed: 42,
    speed: 1,
    playing: true,
    loop: false,
    loop_index: 0,
    dataset_ts: datasetTsFor(plantId, tick),
    dataset_start: plant.dataset_start,
    dataset_end: plant.dataset_end,
    rows_published: tick * plant.machine_count,
    rows_total: 600 * plant.machine_count,
    machine_count: plant.machine_count,
    ts: new Date().toISOString(),
    schema_version: 1,
  };
}

export function makeHealth(plantId: PlantId, tick: number): HealthResponse {
  return {
    status: 'ok',
    version: '1.0.0',
    model_id: MODEL_ID,
    run_id: RUN_ID,
    db_ok: true,
    mqtt_connected: true,
    plants_available: ['ai4i', 'ims'],
    replay: makeReplayState(plantId, tick),
    uptime_seconds: 42,
  };
}

/** The flattened settings tree, carrying every key the shell reads at runtime. */
export function makeConfig(): ConfigResponse {
  return {
    schema_version: 1,
    run_id: RUN_ID,
    values: {
      'api.ws_ping_seconds': 10,
      'api.ws_flush_ms': 100,
      'api.sparkline_points': 60,
      'api.max_series_points': 2000,
      'api.offline_after_seconds': 30,
      'replay.allowed_speeds': [0.5, 1, 5, 20],
      'explanation.top_k': 8,
      'explanation.top_k_whatif': 5,
      'explanation.top_k_preview': 3,
      'alerting.probability_threshold': 0.6,
      'alerting.watch_threshold': 0.35,
      'alerting.severity_bands.medium': 0.6,
      'alerting.severity_bands.high': 0.75,
      'alerting.severity_bands.critical': 0.9,
    },
    mutable_keys: ['alerting.probability_threshold', 'explanation.top_k'],
    updated_at: null,
  };
}

export function makeAlert(plantId: PlantId, machineId: string, tick: number): Alert {
  const probability = Math.max(0.62, probabilityFor(machineId, tick));
  return {
    alert_id: DEMO_ALERT_ID,
    run_id: RUN_ID,
    plant_id: plantId,
    machine_id: machineId,
    machine_display_name: makeMachineSummary(plantId, machineId, tick).display_name,
    ts: new Date().toISOString(),
    dataset_ts: datasetTsFor(plantId, tick),
    model_id: MODEL_ID,
    probability,
    severity: probability >= 0.9 ? 'critical' : probability >= 0.75 ? 'high' : 'medium',
    headline: 'Torque stayed above its 95th percentile for 4 consecutive hours',
    top_feature: 'torque_p95_4h',
    explanation_id: DEMO_EXPLANATION_ID,
    closed_dataset_ts: null,
  };
}

export function makeExplanation(alert: Alert): Explanation {
  const contributions: Explanation['contributions'] = [
    {
      feature: 'torque_p95_4h',
      display_name: 'Torque — 95th pct over 4 h',
      shap: 0.31,
      value: 48.1,
      unit: 'N·m',
      percentile: 97,
      window_hours: 4,
      stat: 'p95',
      framing: 'consecutive',
      consecutive_hours: 4,
      threshold: 46.2,
      direction: 'up',
      sentence: 'torque stayed above its 95th percentile for 4 consecutive hours',
    },
    {
      feature: 'temp_diff_slope_1h',
      display_name: 'Temperature Difference — slope over 1 h',
      shap: 0.19,
      value: 0.31,
      unit: 'K',
      percentile: 91,
      window_hours: 1,
      stat: 'slope',
      framing: 'trend',
      consecutive_hours: null,
      threshold: null,
      direction: 'up',
      sentence: 'the temperature difference has been climbing for the last hour',
    },
    {
      feature: 'rot_speed_mean_24h',
      display_name: 'Rotational Speed — mean over 24 h',
      shap: -0.06,
      value: 1503,
      unit: 'rpm',
      percentile: 38,
      window_hours: 24,
      stat: 'mean',
      framing: 'percentile',
      consecutive_hours: null,
      threshold: null,
      direction: 'down',
      sentence: 'rotational speed is unremarkable for this machine',
    },
  ];
  const other = 0.04;
  const sum = contributions.reduce((total, c) => total + c.shap, 0);
  const base = 0.08;
  return {
    explanation_id: alert.explanation_id,
    alert_id: alert.alert_id,
    machine_id: alert.machine_id,
    model_id: MODEL_ID,
    model_kind: 'lgbm',
    dataset_ts: alert.dataset_ts,
    shap_space: 'probability',
    base_value: base,
    output_value: base + sum + other,
    probability: base + sum + other,
    contributions,
    other_contributions_shap: other,
    other_contributions_count: 146,
    n_features: 154,
    sentence:
      'Mill 03 was flagged at 56% risk because torque stayed above its 95th percentile for 4 consecutive hours.',
    sentence_spans: [{ start: 47, end: 53, feature: 'torque_p95_4h' }],
    caveat:
      'SHAP attributions describe how this model arrived at this score. They are associations learned from historical data, not proof of physical cause.',
  };
}
