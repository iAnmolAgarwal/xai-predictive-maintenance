/**
 * Contract-faithful MSW handlers: the same REST + WebSocket surface the API
 * serves, backed by the deterministic fixtures. Used by Vitest, by Playwright and
 * by `pnpm dev:mock`; never by a production bundle.
 */
import { http, HttpResponse, ws } from 'msw';
import type { PlantId, ReplayCommand, ServerFrame } from '@/contracts';
import {
  DEMO_ALERT_ID,
  MOCK_MARKER,
  PLANTS,
  RUN_ID,
  datasetTsFor,
  machineIdsFor,
  makeAlert,
  makeChannelValues,
  makeConfig,
  makeExplanation,
  makeHealth,
  makeMachineSummary,
  makePlant,
  makeReplayState,
  makeSnapshotMachines,
  probabilityFor,
} from './fixtures';

/** Milliseconds between simulated replay ticks in the mock. */
const TICK_MS = 250;
/** Tick at which the demo machine's alert fires. */
const ALERT_TICK = 6;

const plantIdFrom = (value: string | null): PlantId => (value === 'ims' ? 'ims' : 'ai4i');

export const restHandlers = [
  http.get('/api/health', ({ request }) =>
    HttpResponse.json(
      makeHealth(plantIdFrom(new URL(request.url).searchParams.get('plant_id')), 0),
    ),
  ),
  http.get('/api/config', () => HttpResponse.json(makeConfig())),
  http.get('/api/plants', () => HttpResponse.json(PLANTS)),
  http.get('/api/replay', () => HttpResponse.json(makeReplayState('ai4i', 0))),
  http.post('/api/replay/command', async ({ request }) => {
    const command = (await request.json()) as ReplayCommand;
    const state = makeReplayState(plantIdFrom(command.plant_id ?? null), 0);
    return HttpResponse.json({
      ...state,
      playing: command.command === 'pause' ? false : state.playing,
      speed: command.speed ?? state.speed,
    });
  }),
  http.get('/api/machines', ({ request }) => {
    const plantId = plantIdFrom(new URL(request.url).searchParams.get('plant_id'));
    return HttpResponse.json(
      machineIdsFor(plantId).map((id) => makeMachineSummary(plantId, id, 0)),
    );
  }),
  http.get('/api/machines/:machineId', ({ params }) => {
    const machineId = String(params.machineId);
    const plantId = plantIdFrom(machineId.split('-')[0] ?? 'ai4i');
    const plant = makePlant(plantId);
    if (!machineIdsFor(plantId).includes(machineId)) {
      return HttpResponse.json(
        { type: 'about:blank', title: 'Not Found', status: 404, detail: 'no such machine' },
        { status: 404, headers: { 'Content-Type': 'application/problem+json' } },
      );
    }
    return HttpResponse.json({
      ...makeMachineSummary(plantId, machineId, 0),
      channels: plant.channels,
      alert_count: machineId === plant.demo_machine_id ? 1 : 0,
      variant_mix: plantId === 'ai4i' ? { L: 6, M: 4, H: 2 } : null,
      bearing: plantId === 'ims' ? Number(machineId.slice(-2)) : null,
    });
  }),
  http.get('/api/alerts', () => {
    const alert = makeAlert('ai4i', 'ai4i-03', ALERT_TICK);
    return HttpResponse.json({ items: [alert], next_cursor: null });
  }),
  http.get('/api/alerts/:alertId', () =>
    HttpResponse.json(makeAlert('ai4i', 'ai4i-03', ALERT_TICK)),
  ),
  http.get('/api/alerts/:alertId/explanation', () =>
    HttpResponse.json(makeExplanation(makeAlert('ai4i', 'ai4i-03', ALERT_TICK))),
  ),
];

/** The socket the app connects to; `plant_id` is the complete subscription. */
export const socketLink = ws.link('*/ws');

export const wsHandler = socketLink.addEventListener('connection', ({ client }) => {
  const plantId = plantIdFrom(client.url.searchParams.get('plant_id'));
  const plant = makePlant(plantId);
  const machineIds = machineIdsFor(plantId);
  let tick = 0;

  const send = (frame: ServerFrame): void => client.send(JSON.stringify(frame));

  // hello, then snapshot, on every connect — no resume, ever (R10).
  send({
    type: 'hello',
    protocol_version: 1,
    run_id: RUN_ID,
    server_time: new Date().toISOString(),
    plant,
  });
  send({
    type: 'snapshot',
    plant_id: plantId,
    run_id: RUN_ID,
    dataset_ts: datasetTsFor(plantId, tick),
    machines: makeSnapshotMachines(plantId, tick),
    active_alerts: [],
    replay_state: makeReplayState(plantId, tick),
  });

  const timer = setInterval(() => {
    tick += 1;
    send({
      type: 'telemetry',
      plant_id: plantId,
      dataset_ts: datasetTsFor(plantId, tick),
      ts: new Date().toISOString(),
      updates: machineIds.map((machineId, index) => ({
        machine_id: machineId,
        dataset_ts: datasetTsFor(plantId, tick),
        seq: tick * machineIds.length + index,
        values: makeChannelValues(plantId, machineId, tick),
      })),
    });
    send({
      type: 'risk',
      plant_id: plantId,
      ts: new Date().toISOString(),
      updates: machineIds.map((machineId) => {
        const summary = makeMachineSummary(plantId, machineId, tick);
        return {
          machine_id: machineId,
          dataset_ts: datasetTsFor(plantId, tick),
          probability: summary.probability ?? probabilityFor(machineId, tick),
          status: summary.status,
          alert_id: summary.open_alert_id,
          model_id: 'lgbm@1.0.0',
          top_features: [
            { feature: 'torque_p95_4h', shap: 0.31 },
            { feature: 'temp_diff_slope_1h', shap: 0.19 },
            { feature: 'rot_speed_mean_24h', shap: -0.06 },
          ],
        };
      }),
    });
    if (tick === ALERT_TICK) {
      const alert = makeAlert(plantId, plant.demo_machine_id, tick);
      send({ type: 'alert', ...alert });
      send({ type: 'explanation', ...makeExplanation(alert) });
    }
    if (tick % 40 === 0) send({ type: 'ping', ts: new Date().toISOString() });
  }, TICK_MS);

  client.addEventListener('message', (event) => {
    // The client speaks exactly one frame type; anything else is a protocol bug.
    if (typeof event.data === 'string' && !event.data.includes('pong')) {
      console.warn(`${MOCK_MARKER}: unexpected client frame`, event.data);
    }
  });
  client.addEventListener('close', () => clearInterval(timer));
});

export const handlers = [...restHandlers, wsHandler];

export { DEMO_ALERT_ID };
