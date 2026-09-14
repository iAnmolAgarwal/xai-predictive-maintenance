import { beforeEach, describe, expect, it } from 'vitest';
import { ALERT_CAP } from '@/config';
import type { Alert, RiskUpdate } from '@/contracts';
import {
  DATASET_START,
  PLANTS,
  makeAlert,
  makeConfig,
  makeExplanation,
  makeReplayState,
  makeSnapshotMachines,
} from '@/mock/fixtures';
import { resetStore, useStore } from '../index';
import {
  availableTopFeatures,
  historicalExplanations,
  matchesFilters,
  selectedMachineCount,
  selectedPlant,
  visibleAlerts,
} from '../selectors';

const alertAt = (id: string, overrides: Partial<Alert> = {}): Alert => ({
  ...makeAlert('ai4i', 'ai4i-03', 6),
  alert_id: id,
  ...overrides,
});

beforeEach(() => {
  resetStore();
});

describe('connection slice', () => {
  it('tracks status, liveness and the degraded treatment', () => {
    const store = useStore.getState();
    store.setConnectionStatus('reconnecting', 3);
    store.setConnectionDegraded(true);
    store.noteMessageReceived(1234);
    expect(useStore.getState().connection).toMatchObject({
      status: 'reconnecting',
      attempt: 3,
      degraded: true,
      lastMessageAt: 1234,
    });

    useStore.getState().setConnectionStatus('open');
    expect(useStore.getState().connection.degraded).toBe(false);

    useStore.getState().setConnectionError('api unreachable');
    expect(useStore.getState().connection.error).toBe('api unreachable');
  });
});

describe('plants slice', () => {
  it('selects the first available plant and keeps a valid selection', () => {
    useStore.getState().setPlants(PLANTS);
    expect(useStore.getState().plants.selected).toBe('ai4i');
    expect(useStore.getState().plants.order).toEqual(['ai4i', 'ims']);

    useStore.getState().selectPlant('ims');
    useStore.getState().setPlants(PLANTS);
    expect(useStore.getState().plants.selected).toBe('ims');
  });

  it('skips an unavailable plant when choosing a default', () => {
    const unavailable = PLANTS.map((plant, index) =>
      index === 0 ? { ...plant, available: false } : plant,
    );
    useStore.getState().setPlants(unavailable);
    expect(useStore.getState().plants.selected).toBe('ims');
  });

  it('upserts a plant from a hello frame without duplicating the order', () => {
    const [plant] = PLANTS;
    if (!plant) throw new Error('fixture missing');
    useStore.getState().upsertPlant(plant);
    useStore.getState().upsertPlant(plant);
    expect(useStore.getState().plants.order).toEqual(['ai4i']);
  });
});

describe('machines slice', () => {
  it('seeds from a snapshot and applies risk updates per machine', () => {
    const machines = makeSnapshotMachines('ai4i', 4);
    useStore.getState().seedMachines(machines);
    const seeded = useStore.getState().machines;
    expect(seeded.order).toHaveLength(12);
    expect(seeded.byId['ai4i-01']).toBeDefined();
    expect('values' in (seeded.byId['ai4i-01'] ?? {})).toBe(false);

    const update: RiskUpdate = {
      machine_id: 'ai4i-01',
      dataset_ts: DATASET_START,
      probability: 0.82,
      status: 'alert',
      alert_id: 'alt_9f2c71ab40d3e155',
      model_id: 'lgbm@1.0.0',
      top_features: [{ feature: 'torque_p95_4h', shap: 0.31 }],
    };
    useStore.getState().applyRiskUpdates([update]);

    const live = useStore.getState().machines.live['ai4i-01'];
    expect(live).toMatchObject({ probability: 0.82, status: 'alert', revision: 1 });
    expect(useStore.getState().machines.byId['ai4i-01']?.open_alert_id).toBe(
      'alt_9f2c71ab40d3e155',
    );
    // Untouched machines keep their identity, so their tiles do not re-render.
    expect(useStore.getState().machines.live['ai4i-02']?.revision).toBe(0);
  });

  it('ignores an empty risk batch', () => {
    useStore.getState().seedMachines(makeSnapshotMachines('ai4i', 0));
    const before = useStore.getState().machines;
    useStore.getState().applyRiskUpdates([]);
    expect(useStore.getState().machines).toBe(before);
  });

  it('stores the canonical channel order', () => {
    const [plant] = PLANTS;
    if (!plant) throw new Error('fixture missing');
    useStore.getState().setChannels(plant.channels);
    expect(useStore.getState().machines.channels.map((c) => c.name)).toEqual(
      plant.channels.map((c) => c.name),
    );
  });
});

describe('telemetry and risk revisions', () => {
  it('bumps and resets per machine', () => {
    useStore.getState().bumpTelemetryRevisions(['ai4i-01', 'ai4i-02']);
    useStore.getState().bumpTelemetryRevisions(['ai4i-01']);
    useStore.getState().bumpRiskRevisions(['ai4i-01']);
    expect(useStore.getState().telemetry.revision).toEqual({ 'ai4i-01': 2, 'ai4i-02': 1 });
    expect(useStore.getState().risk.revision['ai4i-01']).toBe(1);

    useStore.getState().resetTelemetryRevisions(['ai4i-01']);
    useStore.getState().resetRiskRevisions(['ai4i-01']);
    expect(useStore.getState().telemetry.revision).toEqual({ 'ai4i-01': 0 });
    expect(useStore.getState().risk.revision).toEqual({ 'ai4i-01': 0 });

    const before = useStore.getState().telemetry;
    useStore.getState().bumpTelemetryRevisions([]);
    useStore.getState().bumpRiskRevisions([]);
    expect(useStore.getState().telemetry).toBe(before);
  });
});

describe('alerts slice', () => {
  it('keeps newest first and evicts the oldest past the cap', () => {
    const many = Array.from({ length: ALERT_CAP + 5 }, (_, index) =>
      alertAt(`alt_${index.toString(16).padStart(16, '0')}`, {
        dataset_ts: new Date(Date.parse(DATASET_START) + index * 60_000).toISOString(),
      }),
    );
    useStore.getState().addAlerts(many);

    const { order, byId } = useStore.getState().alerts;
    expect(order).toHaveLength(ALERT_CAP);
    expect(Object.keys(byId)).toHaveLength(ALERT_CAP);
    expect(order[0]).toBe(many[many.length - 1]?.alert_id);
    expect(byId[many[0]?.alert_id ?? '']).toBeUndefined();
  });

  it('counts only new open alerts as unseen', () => {
    useStore.getState().addAlerts([alertAt('alt_1111111111111111')], { unseen: true });
    useStore.getState().addAlerts([alertAt('alt_1111111111111111')], { unseen: true });
    useStore
      .getState()
      .addAlerts([alertAt('alt_2222222222222222', { closed_dataset_ts: DATASET_START })], {
        unseen: true,
      });
    expect(useStore.getState().alerts.unseenCount).toBe(1);

    useStore.getState().markAlertsSeen();
    expect(useStore.getState().alerts.unseenCount).toBe(0);
  });

  it('ignores an empty batch and tracks the cursor', () => {
    const before = useStore.getState().alerts;
    useStore.getState().addAlerts([]);
    expect(useStore.getState().alerts).toBe(before);

    useStore.getState().setAlertsCursor('cursor-2');
    expect(useStore.getState().alerts.nextCursor).toBe('cursor-2');
  });

  it('composes the three filters', () => {
    useStore.getState().addAlerts([
      alertAt('alt_aaaaaaaaaaaaaaaa', { machine_id: 'ai4i-03', severity: 'high' }),
      alertAt('alt_bbbbbbbbbbbbbbbb', {
        machine_id: 'ai4i-07',
        severity: 'medium',
        top_feature: 'tool_wear_max_24h',
      }),
    ]);

    useStore.getState().setAlertFilters({ machineIds: ['ai4i-03'] });
    expect(visibleAlerts(useStore.getState()).map((alert) => alert.alert_id)).toEqual([
      'alt_aaaaaaaaaaaaaaaa',
    ]);

    useStore.getState().setAlertFilters({ machineIds: [], severities: ['medium'] });
    expect(visibleAlerts(useStore.getState()).map((alert) => alert.alert_id)).toEqual([
      'alt_bbbbbbbbbbbbbbbb',
    ]);

    useStore.getState().setAlertFilters({ severities: [], feature: 'tool_wear_max_24h' });
    expect(visibleAlerts(useStore.getState())).toHaveLength(1);
    expect(availableTopFeatures(useStore.getState())).toEqual([
      'tool_wear_max_24h',
      'torque_p95_4h',
    ]);

    expect(
      matchesFilters(alertAt('alt_cccccccccccccccc'), {
        machineIds: [],
        severities: [],
        feature: null,
      }),
    ).toBe(true);
  });

  it('clears alerts on a wholesale rebuild but keeps the user filters', () => {
    useStore.getState().setAlertFilters({ severities: ['critical'] });
    useStore.getState().addAlerts([alertAt('alt_dddddddddddddddd')], { unseen: true });
    useStore.getState().resetAlerts();
    expect(useStore.getState().alerts.order).toEqual([]);
    expect(useStore.getState().alerts.unseenCount).toBe(0);
    expect(useStore.getState().alerts.filters.severities).toEqual(['critical']);
  });
});

describe('explanations slice', () => {
  it('stores explanations, comparisons, importance, loading and errors', () => {
    const alert = makeAlert('ai4i', 'ai4i-03', 6);
    const explanation = makeExplanation(alert);
    useStore.getState().putExplanation(explanation);
    useStore.getState().putComparison({
      alert_id: alert.alert_id,
      lgbm: explanation,
      rf: explanation,
      probability_delta: 0.13,
      rank_correlation: 0.82,
      disagreements: [],
      commentary: 'rf weights tool wear more.',
    });
    useStore.getState().putImportance({
      machine_id: 'ai4i-03',
      n_alerts: 3,
      features: [],
    });
    useStore.getState().setExplanationLoading(alert.alert_id, true);
    useStore.getState().setExplanationError(alert.alert_id, 'boom');

    const state = useStore.getState().explanations;
    expect(state.byAlertId[alert.alert_id]?.explanation_id).toBe(
      explanation.explanation_id,
    );
    expect(state.compareByAlertId[alert.alert_id]?.commentary).toBe(
      'rf weights tool wear more.',
    );
    expect(state.importanceByMachineId['ai4i-03']?.n_alerts).toBe(3);
    expect(state.loading[alert.alert_id]).toBe(true);
    expect(state.error[alert.alert_id]).toBe('boom');
  });
});

describe('playback slice', () => {
  it('reconciles optimistic transport state with the authoritative frame', () => {
    useStore.getState().setPlayingOptimistic(false);
    useStore.getState().setSpeedOptimistic(20);
    expect(useStore.getState().playback).toMatchObject({ playing: false, speed: 20 });

    useStore.getState().applyReplayState(makeReplayState('ai4i', 3));
    expect(useStore.getState().playback).toMatchObject({ playing: true, speed: 1 });
    expect(useStore.getState().playback.runId).toBe('run_1a2b3c4d5e6f');
    expect(useStore.getState().playback.spanMs.start).toBe(Date.parse(DATASET_START));
  });

  it('freezes the dataset clock while scrubbing', () => {
    useStore.getState().setDatasetTsMs(1000);
    useStore.getState().setScrubbing(true, 500);
    useStore.getState().setDatasetTsMs(2000);
    expect(useStore.getState().playback.datasetTsMs).toBe(1000);
    expect(useStore.getState().playback.scrubDatasetTsMs).toBe(500);

    useStore.getState().setScrubbing(false);
    useStore.getState().setDatasetTsMs(3000);
    expect(useStore.getState().playback.datasetTsMs).toBe(3000);
  });

  it('holds a derived historical snapshot', () => {
    useStore.getState().setHistorical({
      datasetTsMs: 10,
      machines: {},
      explanationByMachineId: {},
    });
    expect(useStore.getState().playback.historical?.datasetTsMs).toBe(10);
    useStore.getState().setRunId('run_0000000000ff');
    expect(useStore.getState().playback.runId).toBe('run_0000000000ff');
  });
});

describe('what-if slice', () => {
  it('tracks overrides, latency and errors, and resets on alert change', () => {
    const alert = makeAlert('ai4i', 'ai4i-03', 6);
    useStore.getState().setWhatIfAlert(alert.alert_id, 'rf');
    useStore.getState().setWhatIfOverride('torque_p95_4h', 50);
    useStore.getState().setWhatIfInFlight(true);

    const response = {
      alert_id: alert.alert_id,
      model_id: 'lgbm@1.0.0',
      model_kind: 'lgbm' as const,
      shap_space: 'probability' as const,
      baseline_probability: 0.56,
      probability: 0.61,
      base_value: 0.08,
      output_value: 0.61,
      contributions: [],
      other_contributions_shap: 0.04,
      other_contributions_count: 146,
      n_features: 154,
      gradients: { torque_p95_4h: 0.012 },
      sentence: 'provisional sentence',
      sentence_spans: [],
      provisional: true,
      caveat: 'SHAP describes association, not physical cause.',
      compute_ms: 11,
    };
    useStore.getState().setWhatIfAuthoritative(response, 41);

    expect(useStore.getState().whatif).toMatchObject({
      model: 'rf',
      lastLatencyMs: 41,
      lastComputeMs: 11,
      inFlight: false,
    });
    expect(useStore.getState().whatif.gradients).toEqual({ torque_p95_4h: 0.012 });

    useStore.getState().clearWhatIfOverride('torque_p95_4h');
    expect(useStore.getState().whatif.overrides).toEqual({});

    useStore.getState().setWhatIfOverride('temp_diff_slope_1h', 0.4);
    useStore.getState().resetWhatIfOverrides();
    expect(useStore.getState().whatif.overrides).toEqual({});

    useStore.getState().setWhatIfOptimistic(response);
    expect(useStore.getState().whatif.optimistic).not.toBeNull();

    useStore.getState().setWhatIfError('whatif failed');
    expect(useStore.getState().whatif.error).toBe('whatif failed');

    useStore.getState().setWhatIfAlert(null);
    expect(useStore.getState().whatif.authoritative).toBeNull();
  });
});

describe('ui slice', () => {
  it('shares selection, hover and chrome flags', () => {
    const store = useStore.getState();
    store.setSelectedMachineId('ai4i-03');
    store.setSelectedAlertId('alt_9f2c71ab40d3e155');
    store.setHoveredFeature('torque_p95_4h');
    store.setCompareOpen(true);
    store.setReducedMotion(true);
    store.setRailOpen(false);
    useStore.getState().toggleRail();

    expect(useStore.getState().ui).toMatchObject({
      selectedMachineId: 'ai4i-03',
      selectedAlertId: 'alt_9f2c71ab40d3e155',
      hoveredFeature: 'torque_p95_4h',
      compareOpen: true,
      reducedMotion: true,
      railOpen: true,
    });
  });
});

describe('config slice', () => {
  it('stores the flattened settings tree', () => {
    useStore.getState().applyConfig(makeConfig());
    expect(useStore.getState().config?.values['api.ws_ping_seconds']).toBe(10);
  });
});

describe('selectors', () => {
  it('derives the per-machine historical explanation from a PlantSnapshot', () => {
    const alert = makeAlert('ai4i', 'ai4i-03', 6);
    const explanation = makeExplanation(alert);
    const orphan = { ...alert, alert_id: 'alt_0000000000000001', machine_id: 'ai4i-07' };

    const derived = historicalExplanations({
      plant_id: 'ai4i',
      run_id: 'run_1a2b3c4d5e6f',
      dataset_ts: alert.dataset_ts,
      machines: [],
      active_alerts: [alert, orphan],
      active_explanations: [explanation],
    });

    expect(derived['ai4i-03']?.explanation_id).toBe(explanation.explanation_id);
    // An alert with no stored explanation is a correct historical answer.
    expect(derived['ai4i-07']).toBeNull();
    // A machine with no open alert simply has no entry.
    expect(derived['ai4i-01']).toBeUndefined();
  });

  it('reads the grid size from the plant descriptor', () => {
    useStore.getState().setPlants(PLANTS);
    expect(selectedPlant(useStore.getState())?.plant_id).toBe('ai4i');
    expect(selectedMachineCount(useStore.getState())).toBe(12);

    useStore.getState().selectPlant('ims');
    expect(selectedMachineCount(useStore.getState())).toBe(4);

    resetStore();
    expect(selectedPlant(useStore.getState())).toBeNull();
    expect(selectedMachineCount(useStore.getState())).toBe(0);
  });
});
