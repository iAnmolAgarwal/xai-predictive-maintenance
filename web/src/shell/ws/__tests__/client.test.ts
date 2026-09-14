import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { wsSilenceTimeoutMs } from '@/config';
import type { Plant, ServerFrame } from '@/contracts';
import {
  DATASET_START,
  RUN_ID,
  makeAlert,
  makeConfig,
  makeExplanation,
  makePlant,
  makeReplayState,
  makeSnapshotMachines,
} from '@/mock/fixtures';
import { resetStore, useStore } from '@/store';
import { clearRings, getRiskRing, getTelemetryRing, readLast } from '@/store/ringBuffer';
import { createWsClient, wsUrl, type WsClient } from '../client';
import type { FakeSocket } from './fakeSocket';
import { socketFactory } from './fakeSocket';

const ORIGIN = 'http://xpm.test';

const helloFrame = (plant: Plant, runId = RUN_ID): ServerFrame => ({
  type: 'hello',
  protocol_version: 1,
  run_id: runId,
  server_time: '2026-01-01T00:00:00.000Z',
  plant,
});

const snapshotFrame = (plant: Plant, runId = RUN_ID, tick = 0): ServerFrame => ({
  type: 'snapshot',
  plant_id: plant.plant_id,
  run_id: runId,
  dataset_ts: DATASET_START,
  machines: makeSnapshotMachines(plant.plant_id, tick),
  active_alerts: [makeAlert(plant.plant_id, plant.demo_machine_id, tick)],
  // hello, snapshot and replay_state always carry the same run id (R12).
  replay_state: { ...makeReplayState(plant.plant_id, tick), run_id: runId },
});

describe('ws client', () => {
  let sockets: FakeSocket[];
  let client: WsClient;
  let frames: FrameRequestCallback[];
  let now = 1_000_000;

  const runFrame = (): void => {
    const pending = frames.splice(0, frames.length);
    pending.forEach((callback) => callback(0));
  };

  const connectAndSeed = (plant = makePlant('ai4i'), runId = RUN_ID): FakeSocket => {
    client.connect(plant.plant_id);
    const socket = sockets[sockets.length - 1];
    if (!socket) throw new Error('no socket was created');
    socket.open();
    socket.receive(helloFrame(plant, runId));
    socket.receive(snapshotFrame(plant, runId));
    return socket;
  };

  beforeEach(() => {
    vi.useFakeTimers();
    resetStore();
    clearRings();
    sockets = [];
    frames = [];
    now = 1_000_000;
    useStore.getState().applyConfig(makeConfig());
    client = createWsClient({
      socketFactory: socketFactory(sockets),
      origin: ORIGIN,
      now: () => now,
      random: () => 0.5,
      requestFrame: (callback) => frames.push(callback),
      cancelFrame: () => frames.splice(0, frames.length),
    });
  });

  afterEach(() => {
    client.disconnect();
    vi.useRealTimers();
  });

  it('subscribes with the plant_id query parameter and nothing else', () => {
    client.connect('ai4i');
    const socket = sockets[0];
    expect(socket?.url).toBe(`${ORIGIN.replace('http', 'ws')}/ws?plant_id=ai4i`);

    socket?.open();
    // No subscribe frame, no client ping, no resume cursor: the query parameter
    // is the whole subscription (R10, R11).
    expect(socket?.sent).toEqual([]);
    expect(useStore.getState().connection.status).toBe('open');
  });

  it('builds a wss URL on a secure origin', () => {
    expect(wsUrl('ims', 'https://xpm.test')).toBe('wss://xpm.test/ws?plant_id=ims');
  });

  it('populates the dashboard from hello + snapshot alone', () => {
    const plant = makePlant('ai4i');
    connectAndSeed(plant);

    const state = useStore.getState();
    expect(state.plants.byId['ai4i']?.machine_count).toBe(12);
    expect(state.machines.order).toHaveLength(12);
    expect(state.machines.channels).toHaveLength(plant.channels.length);
    expect(state.playback.runId).toBe(RUN_ID);
    expect(state.playback.spanMs.start).toBe(Date.parse(plant.dataset_start));
    expect(state.alerts.order).toHaveLength(1);
    // Backfill is not "new": the rail badge stays quiet on a reconnect.
    expect(state.alerts.unseenCount).toBe(0);
  });

  it('seeds each ring buffer from machines[].values positionally, ignoring any top-level values', () => {
    const plant = makePlant('ai4i');
    // Permute the channel list and the values together: a positional mapping
    // survives it, a name-based one cannot.
    const permuted: Plant = {
      ...plant,
      channels: [...plant.channels].reverse(),
    };
    const machines = makeSnapshotMachines('ai4i', 0).map((machine) => ({
      ...machine,
      values: [...machine.values].reverse(),
    }));

    client.connect('ai4i');
    const socket = sockets[0];
    socket?.open();
    socket?.receive(helloFrame(permuted));
    socket?.receive({
      type: 'snapshot',
      plant_id: 'ai4i',
      run_id: RUN_ID,
      dataset_ts: DATASET_START,
      machines,
      active_alerts: [],
      replay_state: makeReplayState('ai4i', 0),
      // A stray top-level array must not be read: the handler only knows
      // machines[].values.
      values: [1, 2, 3, 4, 5, 6, 7],
    });

    const ring = getTelemetryRing('ai4i-01');
    expect(ring?.series).toHaveLength(permuted.channels.length);
    const seeded = readLast(
      ring ?? { series: [], datasetTsMs: new Float64Array(), cap: 0, count: 0, write: 0 },
      1,
    );
    const expected = machines[0]?.values ?? [];
    expected.forEach((value, index) => {
      expect(seeded.series[index]?.[0]).toBe(value);
    });
  });

  it('appends batched telemetry into the ring buffers and commits once per frame', () => {
    const plant = makePlant('ai4i');
    const socket = connectAndSeed(plant);
    runFrame();
    const before = useStore.getState().telemetry.revision['ai4i-01'] ?? 0;

    for (let tick = 1; tick <= 25; tick += 1) {
      socket.receive({
        type: 'telemetry',
        plant_id: 'ai4i',
        dataset_ts: DATASET_START,
        ts: '2026-01-01T00:00:00.000Z',
        updates: [
          {
            machine_id: 'ai4i-01',
            dataset_ts: new Date(Date.parse(DATASET_START) + tick * 1000).toISOString(),
            seq: tick,
            values: plant.channels.map((_, index) => tick + index),
          },
        ],
      });
    }
    // 25 frames, one animation frame: React hears about it exactly once.
    expect(useStore.getState().telemetry.revision['ai4i-01']).toBe(before);
    runFrame();
    expect(useStore.getState().telemetry.revision['ai4i-01']).toBe(before + 1);

    const ring = getTelemetryRing('ai4i-01');
    // Every sample is kept: coalescing applies to the store, not the buffer.
    expect(ring?.count).toBe(26);
  });

  it('applies risk updates with last-value-wins per machine', () => {
    const socket = connectAndSeed();
    const riskUpdate = (probability: number) => ({
      machine_id: 'ai4i-02',
      dataset_ts: DATASET_START,
      probability,
      status: 'alert' as const,
      alert_id: null,
      model_id: 'lgbm@1.0.0',
      top_features: [{ feature: 'torque_p95_4h', shap: 0.31 }],
    });
    socket.receive({
      type: 'risk',
      plant_id: 'ai4i',
      ts: '2026-01-01T00:00:00.000Z',
      updates: [riskUpdate(0.4)],
    });
    socket.receive({
      type: 'risk',
      plant_id: 'ai4i',
      ts: '2026-01-01T00:00:00.000Z',
      updates: [riskUpdate(0.8)],
    });
    runFrame();

    const live = useStore.getState().machines.live['ai4i-02'];
    expect(live?.probability).toBe(0.8);
    expect(live?.status).toBe('alert');
    expect(getRiskRing('ai4i-02')?.count).toBe(3);
  });

  it('routes alerts and explanations through the same rAF commit', () => {
    const socket = connectAndSeed();
    const alert = { ...makeAlert('ai4i', 'ai4i-03', 6), alert_id: 'alt_00000000000000ff' };
    socket.receive({ type: 'alert', ...alert });
    socket.receive({ type: 'explanation', ...makeExplanation(alert) });
    expect(useStore.getState().alerts.unseenCount).toBe(0);

    runFrame();
    expect(useStore.getState().alerts.byId['alt_00000000000000ff']).toBeDefined();
    expect(useStore.getState().alerts.unseenCount).toBe(1);
    expect(
      useStore.getState().explanations.byAlertId['alt_00000000000000ff'],
    ).toBeDefined();
    // The frames are stored as the REST models they spread, with no `type` left on.
    expect('type' in (useStore.getState().alerts.byId['alt_00000000000000ff'] ?? {})).toBe(
      false,
    );
  });

  it('replies to a server ping with exactly one pong, even while paused', () => {
    const socket = connectAndSeed();
    socket.receive({
      type: 'replay_state',
      ...makeReplayState('ai4i', 2),
      playing: false,
    });
    now += 5_000;
    socket.receive({ type: 'ping', ts: '2026-01-01T00:00:05.000Z' });

    expect(socket.sent).toHaveLength(1);
    expect(JSON.parse(socket.sent[0] ?? '{}')).toEqual({
      type: 'pong',
      ts: new Date(now).toISOString(),
    });
    expect(useStore.getState().connection.lastMessageAt).toBe(now);
    expect(useStore.getState().connection.status).toBe('open');
    expect(useStore.getState().playback.playing).toBe(false);
  });

  it('derives the liveness timeout from api.ws_ping_seconds rather than a literal', () => {
    const config = makeConfig();
    useStore.getState().applyConfig({
      ...config,
      values: { ...config.values, 'api.ws_ping_seconds': 4 },
    });
    expect(wsSilenceTimeoutMs(useStore.getState().config?.values ?? null)).toBe(10_000);

    const socket = connectAndSeed();
    now += 9_000;
    vi.advanceTimersByTime(9_000);
    expect(socket.closed).toBe(false);

    now += 2_000;
    vi.advanceTimersByTime(2_000);
    expect(socket.closed).toBe(true);
    expect(useStore.getState().connection.status).toBe('reconnecting');
  });

  it('falls back to the documented default when config has not resolved', () => {
    expect(wsSilenceTimeoutMs(null)).toBe(25_000);
    expect(wsSilenceTimeoutMs({ 'api.ws_ping_seconds': 'nonsense' })).toBe(25_000);
  });

  it('reconnects with backoff and rebuilds wholesale from the new hello + snapshot', () => {
    const plant = makePlant('ai4i');
    const first = connectAndSeed(plant);
    runFrame();
    useStore
      .getState()
      .addAlerts([
        { ...makeAlert('ai4i', 'ai4i-07', 3), alert_id: 'alt_0000000000000fff' },
      ]);
    expect(useStore.getState().alerts.order).toHaveLength(2);

    first.drop();
    expect(useStore.getState().connection.status).toBe('reconnecting');
    expect(useStore.getState().connection.attempt).toBe(1);
    expect(sockets).toHaveLength(1);

    // Full jitter with a 0.5 RNG on the first attempt: 250 ms.
    vi.advanceTimersByTime(249);
    expect(sockets).toHaveLength(1);
    vi.advanceTimersByTime(1);
    expect(sockets).toHaveLength(2);

    const second = sockets[1];
    second?.open();
    second?.receive(helloFrame(plant, 'run_0000000000aa'));
    second?.receive(snapshotFrame(plant, 'run_0000000000aa'));

    // The client sent no cursor and no subscribe frame, and the snapshot
    // replaced state rather than stitching onto it.
    expect(second?.sent).toEqual([]);
    expect(useStore.getState().playback.runId).toBe('run_0000000000aa');
    expect(useStore.getState().alerts.order).toHaveLength(1);
    expect(getTelemetryRing('ai4i-01')?.count).toBe(1);
    expect(useStore.getState().connection.attempt).toBe(0);
  });

  it('ignores unknown frame types and malformed payloads without erroring', () => {
    const socket = connectAndSeed();
    const before = useStore.getState();

    socket.receive({ type: 'future_thing', payload: { anything: true } });
    socket.receiveRaw('not json at all');
    socket.receiveRaw(new ArrayBuffer(4));
    socket.receive(['not', 'an', 'object']);
    socket.receive({ noTypeField: true });

    expect(useStore.getState().connection.error).toBeNull();
    expect(useStore.getState().machines.order).toEqual(before.machines.order);
  });

  it('treats backpressure as degraded, not as an error banner', () => {
    const socket = connectAndSeed();
    socket.receive({
      type: 'error',
      code: 'backpressure_dropped',
      message: 'dropped 4 telemetry frames',
      request_id: null,
    });
    expect(useStore.getState().connection.degraded).toBe(true);
    expect(useStore.getState().connection.error).toBeNull();

    socket.receive({
      type: 'error',
      code: 'internal_error',
      message: 'explainer unavailable',
      request_id: 'req_00ab',
    });
    expect(useStore.getState().connection.error).toBe('explainer unavailable');
  });

  it('applies a pushed config frame in place', () => {
    const socket = connectAndSeed();
    const config = makeConfig();
    socket.receive({
      type: 'config',
      ...config,
      values: { ...config.values, 'explanation.top_k': 5 },
    });
    expect(useStore.getState().config?.values['explanation.top_k']).toBe(5);
  });

  it('ignores telemetry for a machine with no ring buffer', () => {
    const socket = connectAndSeed();
    socket.receive({
      type: 'telemetry',
      plant_id: 'ai4i',
      dataset_ts: DATASET_START,
      ts: DATASET_START,
      updates: [
        { machine_id: 'ims-99', dataset_ts: DATASET_START, seq: 1, values: [1, 2] },
      ],
    });
    runFrame();
    expect(useStore.getState().telemetry.revision['ims-99']).toBeUndefined();
  });

  it('stops reconnecting once disconnected on purpose', () => {
    const socket = connectAndSeed();
    client.disconnect();
    expect(socket.closed).toBe(true);
    expect(useStore.getState().connection.status).toBe('closed');

    vi.advanceTimersByTime(60_000);
    expect(sockets).toHaveLength(1);
  });

  it('replaces the socket when the selected plant changes', () => {
    connectAndSeed(makePlant('ai4i'));
    client.connect('ims');
    expect(sockets).toHaveLength(2);
    expect(sockets[0]?.closed).toBe(true);
    expect(client.currentUrl()).toContain('plant_id=ims');
  });
});
