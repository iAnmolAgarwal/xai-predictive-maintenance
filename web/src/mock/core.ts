/**
 * The deterministic core of the mock: plants, channels, the seeded PRNG, the
 * dataset clock, the settings tree and the mutable replay/config state that the
 * handlers drive. Shaped by `contracts/openapi.json` and
 * `contracts/ws-schema.json`. Ids use the real backend forms (`ai4i-03`,
 * `alt_9f2c71ab40d3e155`, `run_1a2b3c4d5e6f`, `lgbm@1.0.0`) and the channel table
 * is the backend's, so a fixture can never teach the frontend a shape the API
 * does not emit.
 *
 * This module is mock-only and must never reach a production bundle; the marker
 * below is what `no-mock-in-prod` greps the built assets for.
 */
import type {
  ChannelSpec,
  ConfigResponse,
  HealthResponse,
  MachineStatus,
  Plant,
  PlantId,
  ReplayState,
  Speed,
} from '@/contracts';

export const MOCK_MARKER = '__MSW_MOCK_MARKER__';

export const RUN_ID = 'run_1a2b3c4d5e6f';
export const MODEL_ID = 'lgbm@1.0.0';
export const RF_MODEL_ID = 'rf@1.0.0';
export const DEMO_ALERT_ID = 'alt_9f2c71ab40d3e155';
export const DEMO_EXPLANATION_ID = 'exp_31c0a7f9b2d4e680';
export const IMS_DEMO_ALERT_ID = 'alt_5b7d0e2143a6c8f9';
export const DATASET_START = '2026-01-01T00:00:00.000Z';

/** Rows per machine in the mock replay; the dataset clock runs 0..ROW_COUNT. */
export const ROW_COUNT = 600;
/**
 * The dataset tick the REST surface answers "now" with. Wall clock never enters
 * a payload's dataset time, so every REST response is byte-identical run to run.
 */
export const CURRENT_TICK = 240;
/**
 * The live WebSocket clock starts here and ticks forward, so the sixth tick after
 * a client connects is `CURRENT_TICK` — the row the REST surface calls "now" and
 * the row the demo alert is stored against. Live and historical answers therefore
 * describe the same instant instead of two unrelated ones.
 */
export const LIVE_ALERT_TICK = 6;
export const LIVE_START_TICK = CURRENT_TICK - LIVE_ALERT_TICK;

/* Settings leaves the fixtures themselves read, so one edit moves both the
 * payloads and the `GET /api/config` tree that describes them. */
export const TOP_K = 8;
export const TOP_K_WHATIF = 5;
export const TOP_K_PREVIEW = 3;
export const MAX_SENTENCE_FEATURES = 2;
export const SPARKLINE_POINTS = 60;
export const MAX_SERIES_POINTS = 2000;
export const WS_PING_SECONDS = 10;
export const N_FEATURES = 154;
export const PROBABILITY_THRESHOLD = 0.6;
export const WATCH_THRESHOLD = 0.35;
export const SLOPE_ZERO_EPS = 1e-6;
/** The replay seed every fixture PRNG is anchored to. */
export const MOCK_SEED = 42;

/** The SHAP-is-not-causation line; config-sourced on the real API (R13). */
export const CAVEAT =
  'SHAP attributions describe how this model arrived at this score. They are ' +
  'associations learned from historical data, not proof of physical cause.';

/**
 * Successive run ids. A `restart` command and a successful `PUT /api/config`
 * both mint the next one (R5, R12); the sequence is fixed so a test can assert
 * the exact id it expects.
 */
export const RUN_IDS = [
  RUN_ID,
  'run_2b3c4d5e6f70',
  'run_3c4d5e6f7081',
  'run_4d5e6f708192',
  'run_5e6f708192a3',
] as const;

/** AI4I 2020 milling plant — backend.md §3.1, canonical order. */
export const AI4I_CHANNELS: ChannelSpec[] = [
  {
    name: 'air_temp',
    display_name: 'Air Temperature',
    unit: 'K',
    vibration_like: false,
    nominal_min: 294,
    nominal_max: 306,
  },
  {
    name: 'process_temp',
    display_name: 'Process Temperature',
    unit: 'K',
    vibration_like: false,
    nominal_min: 304,
    nominal_max: 315,
  },
  {
    name: 'temp_diff',
    display_name: 'Temperature Difference',
    unit: 'K',
    vibration_like: false,
    nominal_min: 6,
    nominal_max: 14,
  },
  {
    name: 'rot_speed',
    display_name: 'Rotational Speed',
    unit: 'rpm',
    vibration_like: false,
    nominal_min: 1100,
    nominal_max: 2900,
  },
  {
    name: 'torque',
    display_name: 'Torque',
    unit: 'N·m',
    vibration_like: false,
    nominal_min: 0,
    nominal_max: 80,
  },
  {
    name: 'power',
    display_name: 'Mechanical Power',
    unit: 'W',
    vibration_like: false,
    nominal_min: 2000,
    nominal_max: 14000,
  },
  {
    name: 'tool_wear',
    display_name: 'Tool Wear',
    unit: 'min',
    vibration_like: false,
    nominal_min: 0,
    nominal_max: 260,
  },
];

/** NASA IMS bearing plant — 9 channels, six of them vibration-like. */
export const IMS_CHANNELS: ChannelSpec[] = [
  {
    name: 'vibration_0k5khz',
    display_name: 'Vibration @ 0.5 kHz',
    unit: 'g²/Hz',
    vibration_like: true,
    nominal_min: 0,
    nominal_max: 0.05,
  },
  {
    name: 'vibration_1khz',
    display_name: 'Vibration @ 1 kHz',
    unit: 'g²/Hz',
    vibration_like: true,
    nominal_min: 0,
    nominal_max: 0.05,
  },
  {
    name: 'vibration_2khz',
    display_name: 'Vibration @ 2 kHz',
    unit: 'g²/Hz',
    vibration_like: true,
    nominal_min: 0,
    nominal_max: 0.02,
  },
  {
    name: 'vibration_3khz',
    display_name: 'Vibration @ 3 kHz',
    unit: 'g²/Hz',
    vibration_like: true,
    nominal_min: 0,
    nominal_max: 0.02,
  },
  {
    name: 'vibration_5khz',
    display_name: 'Vibration @ 5 kHz',
    unit: 'g²/Hz',
    vibration_like: true,
    nominal_min: 0,
    nominal_max: 0.01,
  },
  {
    name: 'vibration_8khz',
    display_name: 'Vibration @ 8 kHz',
    unit: 'g²/Hz',
    vibration_like: true,
    nominal_min: 0,
    nominal_max: 0.01,
  },
  {
    name: 'vibration_rms',
    display_name: 'Vibration RMS',
    unit: 'g',
    vibration_like: true,
    nominal_min: 0,
    nominal_max: 2,
  },
  {
    name: 'vibration_kurtosis',
    display_name: 'Vibration Kurtosis',
    unit: '',
    vibration_like: false,
    nominal_min: 1.5,
    nominal_max: 12,
  },
  {
    name: 'vibration_crest',
    display_name: 'Vibration Crest Factor',
    unit: '',
    vibration_like: false,
    nominal_min: 2,
    nominal_max: 12,
  },
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
    dataset_end: isoAt(DATASET_START, shape.row_interval_seconds * ROW_COUNT),
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

export function statusFor(probability: number): MachineStatus {
  if (probability >= PROBABILITY_THRESHOLD) return 'alert';
  if (probability >= WATCH_THRESHOLD) return 'watch';
  return 'healthy';
}

/**
 * A machine's unalerted probability at `tick`: deterministic, and the two demo
 * machines drift upward. `machines.probabilityFor` overlays the alert corpus on
 * top of this so a marker always lands on the curve it belongs to.
 */
export function baseProbabilityFor(machineId: string, tick: number): number {
  const index = Number(machineId.slice(-2));
  const random = seededRandom(index * 7919 + tick);
  const drift =
    machineId === 'ai4i-03' || machineId === 'ims-01' ? Math.min(0.9, tick * 0.02) : 0;
  return Math.min(0.99, Math.max(0.01, 0.08 + drift + random() * 0.12));
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
export function makeReplayState(plantId: PlantId, tick: number): ReplayState {
  const plant = makePlant(plantId);
  return {
    run_id: currentRunId(),
    plant_id: plantId,
    seed: MOCK_SEED,
    speed: state.speed,
    playing: state.playing,
    loop: false,
    loop_index: state.loopIndex,
    dataset_ts: datasetTsFor(plantId, tick),
    dataset_start: plant.dataset_start,
    dataset_end: plant.dataset_end,
    rows_published: tick * plant.machine_count,
    rows_total: ROW_COUNT * plant.machine_count,
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
    run_id: currentRunId(),
    db_ok: true,
    mqtt_connected: true,
    plants_available: ['ai4i', 'ims'],
    replay: makeReplayState(plantId, tick),
    uptime_seconds: 42,
  };
}

/* ── Settings tree ─────────────────────────────────────────────────────────── */

/**
 * `ConfigResponse.values` is the FULL flattened settings tree (backend §3.4.2),
 * not just the patchable subset; `mutable_keys` is the only marker of what
 * `PUT /api/config` accepts.
 */
const DEFAULT_CONFIG_VALUES: ConfigResponse['values'] = {
  'api.ws_ping_seconds': WS_PING_SECONDS,
  'api.ws_flush_ms': 100,
  'api.sparkline_points': SPARKLINE_POINTS,
  'api.max_series_points': MAX_SERIES_POINTS,
  'api.offline_after_seconds': 30,
  'alerting.probability_threshold': PROBABILITY_THRESHOLD,
  'alerting.watch_threshold': WATCH_THRESHOLD,
  'alerting.consecutive_rows_to_open': 2,
  'alerting.consecutive_rows_to_close': 3,
  'alerting.cooldown_minutes': 30,
  'alerting.severity_bands.medium': 0.6,
  'alerting.severity_bands.high': 0.75,
  'alerting.severity_bands.critical': 0.9,
  'explanation.top_k': TOP_K,
  'explanation.top_k_whatif': TOP_K_WHATIF,
  'explanation.top_k_preview': TOP_K_PREVIEW,
  'explanation.max_sentence_features': MAX_SENTENCE_FEATURES,
  'explanation.caveat': CAVEAT,
  'features.percentile_levels': [50, 90, 95, 99],
  'features.slope_zero_eps': SLOPE_ZERO_EPS,
  'model.served_model_id': MODEL_ID,
  'replay.allowed_speeds': [0.5, 1, 5, 20],
  'replay.loop': false,
  'replay.seed': MOCK_SEED,
  'plants.ai4i.row_interval_seconds': 300,
  'plants.ai4i.demo_machine_id': 'ai4i-03',
  'plants.ims.row_interval_seconds': 600,
  'plants.ims.demo_machine_id': 'ims-01',
  'paths.processed_data': 'data/processed',
};

/** Exactly the dotted keys `PUT /api/config` accepts (backend §3.4.2). */
export const MUTABLE_KEYS = [
  'alerting.probability_threshold',
  'alerting.watch_threshold',
  'alerting.consecutive_rows_to_open',
  'alerting.consecutive_rows_to_close',
  'alerting.cooldown_minutes',
  'alerting.severity_bands.medium',
  'alerting.severity_bands.high',
  'alerting.severity_bands.critical',
  'explanation.top_k',
  'features.percentile_levels',
];

export function makeConfig(): ConfigResponse {
  return {
    schema_version: 1,
    run_id: currentRunId(),
    values: { ...state.configValues },
    mutable_keys: [...MUTABLE_KEYS],
    updated_at: state.configUpdatedAt,
  };
}

/* ── Mutable mock state ─────────────────────────────────────────────────────
 * Everything a handler can change at runtime lives here and nowhere else, so
 * `resetMockState()` is a complete rewind between tests. It is seeded state, not
 * random state: the same sequence of requests always produces the same payloads.
 */

type MockState = {
  runIdIndex: number;
  playing: boolean;
  speed: Speed;
  tick: number;
  loopIndex: number;
  configValues: ConfigResponse['values'];
  configUpdatedAt: string | null;
};

function initialState(): MockState {
  return {
    runIdIndex: 0,
    playing: true,
    speed: 1,
    tick: LIVE_START_TICK,
    loopIndex: 0,
    configValues: { ...DEFAULT_CONFIG_VALUES },
    configUpdatedAt: null,
  };
}

let state: MockState = initialState();

/** Rewind every mutation a handler can make. Call it in a test `beforeEach`. */
export function resetMockState(): void {
  state = initialState();
}

export function mockState(): Readonly<MockState> {
  return state;
}

export function currentRunId(): string {
  return RUN_IDS[Math.min(state.runIdIndex, RUN_IDS.length - 1)] ?? RUN_ID;
}

/** Mint the next run id: a `restart` (R12) and a successful config PUT (R5). */
export function advanceRunId(): string {
  state = {
    ...state,
    runIdIndex: Math.min(state.runIdIndex + 1, RUN_IDS.length - 1),
    loopIndex: state.loopIndex + 1,
  };
  return currentRunId();
}

export function setReplay(
  patch: Partial<Pick<MockState, 'playing' | 'speed' | 'tick'>>,
): void {
  state = { ...state, ...patch };
}

export function applyConfigValues(values: ConfigResponse['values']): void {
  state = {
    ...state,
    configValues: { ...state.configValues, ...values },
    configUpdatedAt: new Date().toISOString(),
  };
}

/* ── Dataset-clock and channel helpers ─────────────────────────────────────── */

export function rowIntervalSeconds(plantId: PlantId): number {
  return PLANT_SHAPE[plantId].row_interval_seconds;
}

export function channelsFor(plantId: PlantId): ChannelSpec[] {
  return PLANT_SHAPE[plantId].channels.map((channel) => ({ ...channel }));
}

export function channelSpec(plantId: PlantId, name: string): ChannelSpec | undefined {
  return PLANT_SHAPE[plantId].channels.find((channel) => channel.name === name);
}

/** `ai4i-03` -> `ai4i`; anything unrecognised is not a machine id at all. */
export function plantOfMachine(machineId: string): PlantId | null {
  const prefix = machineId.split('-')[0];
  if (prefix !== 'ai4i' && prefix !== 'ims') return null;
  return machineIdsFor(prefix).includes(machineId) ? prefix : null;
}

export function machineDisplayName(plantId: PlantId, machineId: string): string {
  const index = Number(machineId.slice(-2));
  return `${PLANT_SHAPE[plantId].machine_prefix} ${String(index).padStart(2, '0')}`;
}

export function demoMachineId(plantId: PlantId): string {
  return PLANT_SHAPE[plantId].demo_machine_id;
}

/** The dataset tick a timestamp falls in, floored to the row boundary at or below it. */
export function tickAt(plantId: PlantId, datasetTs: string): number {
  const offsetMs = Date.parse(datasetTs) - Date.parse(DATASET_START);
  const tick = Math.floor(offsetMs / (rowIntervalSeconds(plantId) * 1000));
  return Math.min(ROW_COUNT, Math.max(0, tick));
}

/** A stable lowercase-hex id of `length` nibbles, derived from `parts`. */
export function hexId(
  prefix: string,
  length: number,
  ...parts: Array<string | number>
): string {
  let h = 0x811c9dc5;
  for (const part of parts) {
    for (const char of String(part)) {
      h = Math.imul(h ^ char.charCodeAt(0), 0x01000193) >>> 0;
    }
    h = Math.imul(h ^ 0x2f, 0x01000193) >>> 0;
  }
  const random = seededRandom(h);
  let hex = '';
  while (hex.length < length)
    hex += Math.floor(random() * 0x10000)
      .toString(16)
      .padStart(4, '0');
  return `${prefix}${hex.slice(0, length)}`;
}
