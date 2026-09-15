/**
 * The socket side of the mock: the fixed timeline, the frames the REST handlers
 * broadcast, and the scenario hook the degraded state is tested through.
 *
 * These run against the real `WebSocket`, intercepted by MSW, on real timers —
 * the demo alert lands 1.5 s after connect, which is the whole point of the fixed
 * tick.
 */
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from 'vitest';
import type { ServerFrame } from '@/contracts';
import { mockServer } from '../server';
import { PING_EVERY_TICKS, TICK_MS } from '../handlers';
import {
  CURRENT_TICK,
  DEMO_ALERT_ID,
  LIVE_START_TICK,
  RUN_IDS,
  WS_PING_SECONDS,
  datasetTsFor,
  makeConfig,
  resetMockState,
} from '../fixtures';

beforeAll(() => mockServer.listen({ onUnhandledRequest: 'error' }));
afterEach(() => mockServer.resetHandlers());
afterAll(() => mockServer.close());
beforeEach(() => resetMockState());

type Session = { frames: ServerFrame[]; socket: WebSocket };

function connect(query = 'plant_id=ai4i'): Session {
  const socket = new WebSocket(`ws://localhost/ws?${query}`);
  const frames: ServerFrame[] = [];
  socket.addEventListener('message', (event: MessageEvent<string>) => {
    frames.push(JSON.parse(event.data) as ServerFrame);
  });
  return { frames, socket };
}

async function waitForFrame<T extends ServerFrame['type']>(
  session: Session,
  type: T,
  timeout = 6000,
): Promise<Extract<ServerFrame, { type: T }>> {
  const deadline = Date.now() + timeout;
  for (;;) {
    const found = session.frames.find((frame) => frame.type === type);
    if (found) return found as Extract<ServerFrame, { type: T }>;
    if (Date.now() > deadline) throw new Error(`no ${type} frame within ${timeout} ms`);
    await new Promise((resolve) => setTimeout(resolve, 20));
  }
}

describe('the connect handshake', () => {
  it('sends hello then snapshot, seeded at the live start tick', async () => {
    const session = connect();
    const hello = await waitForFrame(session, 'hello');
    const snapshot = await waitForFrame(session, 'snapshot');

    expect(session.frames[0]?.type).toBe('hello');
    expect(session.frames[1]?.type).toBe('snapshot');
    expect(hello.run_id).toBe(RUN_IDS[0]);
    expect(hello.plant.machine_count).toBe(12);
    expect(snapshot.dataset_ts).toBe(datasetTsFor('ai4i', LIVE_START_TICK));
    expect(snapshot.machines).toHaveLength(12);
    expect(snapshot.machines[0]?.values).toHaveLength(hello.plant.channels.length);
    expect(snapshot.replay_state.run_id).toBe(hello.run_id);
    session.socket.close();
  });
});

describe('the fixed timeline', () => {
  it('fires the demo alert and its explanation on the sixth tick', async () => {
    const session = connect();
    const alert = await waitForFrame(session, 'alert');
    const explanation = await waitForFrame(session, 'explanation');

    expect(alert.alert_id).toBe(DEMO_ALERT_ID);
    expect(alert.machine_id).toBe('ai4i-03');
    expect(alert.dataset_ts).toBe(datasetTsFor('ai4i', CURRENT_TICK));
    expect(explanation.alert_id).toBe(alert.alert_id);
    expect(explanation.explanation_id).toBe(alert.explanation_id);

    // The explanation never arrives before its alert.
    const alertIndex = session.frames.findIndex((frame) => frame.type === 'alert');
    const explanationIndex = session.frames.findIndex(
      (frame) => frame.type === 'explanation',
    );
    expect(explanationIndex).toBe(alertIndex + 1);
    session.socket.close();
  }, 10_000);

  it('streams telemetry and risk for every machine on every tick', async () => {
    const session = connect();
    const telemetry = await waitForFrame(session, 'telemetry');
    const risk = await waitForFrame(session, 'risk');

    expect(telemetry.updates).toHaveLength(12);
    expect(telemetry.updates[0]?.values).toHaveLength(7);
    expect(risk.updates).toHaveLength(12);
    expect(risk.updates[0]?.top_features).toHaveLength(3);
    session.socket.close();
  });

  it('sends no risk update for a machine that has no score (R25)', async () => {
    const session = connect('plant_id=ims&mock_scenario=quiet');
    const snapshot = await waitForFrame(session, 'snapshot');
    // `ims-04` is the designed offline machine: the snapshot still lists it with a
    // null probability, and the plant floor renders that as "—".
    expect(snapshot.machines).toHaveLength(4);
    expect(
      snapshot.machines.find((machine) => machine.machine_id === 'ims-04')?.probability,
    ).toBeNull();

    // Four live ticks in, it has still never been named in a `risk` frame —
    // `RiskUpdate.probability` is non-nullable, so a 0 there would be a lie.
    await new Promise((resolve) => setTimeout(resolve, TICK_MS * 4));
    const riskFrames = session.frames.filter((frame) => frame.type === 'risk');
    expect(riskFrames.length).toBeGreaterThan(2);
    for (const frame of riskFrames) {
      expect(frame.updates.map((update) => update.machine_id)).not.toContain('ims-04');
      expect(frame.updates).toHaveLength(3);
      for (const update of frame.updates) expect(typeof update.probability).toBe('number');
    }

    // And the REST surface keeps reporting the same machine as unscored.
    const summaries = (await (await fetch('/api/machines?plant_id=ims')).json()) as Array<{
      machine_id: string;
      probability: number | null;
    }>;
    expect(summaries.find((row) => row.machine_id === 'ims-04')?.probability).toBeNull();
    session.socket.close();
  }, 10_000);

  it('paces the heartbeat at api.ws_ping_seconds', () => {
    expect(PING_EVERY_TICKS * TICK_MS).toBe(WS_PING_SECONDS * 1000);
    expect(makeConfig().values['api.ws_ping_seconds']).toBe(WS_PING_SECONDS);
  });
});

describe('scenario hooks', () => {
  it('emits a backpressure_dropped error frame on request', async () => {
    const session = connect('plant_id=ai4i&mock_scenario=backpressure,quiet');
    const error = await waitForFrame(session, 'error');
    expect(error.code).toBe('backpressure_dropped');
    expect(error.request_id).toBeNull();
    expect(session.frames.some((frame) => frame.type === 'alert')).toBe(false);
    session.socket.close();
  }, 10_000);
});

describe('frames broadcast by the REST handlers', () => {
  it('pushes replay_state for every command and a new run id on restart', async () => {
    const session = connect();
    await waitForFrame(session, 'snapshot');

    await fetch('/api/replay/command', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ schema_version: 1, command: 'pause', request_id: 'req_00a1' }),
    });
    const paused = await waitForFrame(session, 'replay_state');
    expect(paused.playing).toBe(false);
    expect(paused.run_id).toBe(RUN_IDS[0]);

    await fetch('/api/replay/command', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        schema_version: 1,
        command: 'restart',
        request_id: 'req_00a2',
      }),
    });
    const restarted = await waitFor(() =>
      session.frames.filter((frame) => frame.type === 'replay_state').at(-1),
    );
    expect(restarted?.type === 'replay_state' && restarted.run_id).toBe(RUN_IDS[1]);
    session.socket.close();
  }, 10_000);

  it('pushes a config frame after a successful PUT', async () => {
    const session = connect();
    await waitForFrame(session, 'snapshot');

    await fetch('/api/config', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ values: { 'explanation.top_k': 6 } }),
    });
    const config = await waitForFrame(session, 'config');
    expect(config.values['explanation.top_k']).toBe(6);
    expect(config.run_id).toBe(RUN_IDS[1]);
    session.socket.close();
  }, 10_000);

  it('re-sends a snapshot after a seek', async () => {
    const session = connect();
    await waitForFrame(session, 'snapshot');
    const before = session.frames.filter((frame) => frame.type === 'snapshot').length;

    await fetch('/api/replay/command', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        schema_version: 1,
        command: 'seek',
        dataset_ts: datasetTsFor('ai4i', 90),
        request_id: 'req_00a3',
      }),
    });
    const second = await waitFor(() => {
      const snapshots = session.frames.filter((frame) => frame.type === 'snapshot');
      return snapshots.length > before ? snapshots.at(-1) : undefined;
    });
    expect(second?.type === 'snapshot' && second.dataset_ts).toBe(datasetTsFor('ai4i', 90));
    session.socket.close();
  }, 10_000);
});

async function waitFor<T>(read: () => T | undefined, timeout = 4000): Promise<T> {
  const deadline = Date.now() + timeout;
  for (;;) {
    const value = read();
    if (value !== undefined) return value;
    if (Date.now() > deadline) throw new Error('timed out waiting for a frame');
    await new Promise((resolve) => setTimeout(resolve, 20));
  }
}
