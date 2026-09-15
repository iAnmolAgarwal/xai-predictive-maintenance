/**
 * Contract-faithful MSW handlers: the same REST + WebSocket surface the API
 * serves, backed by the deterministic fixtures. Used by Vitest, by Playwright and
 * by `pnpm dev:mock`; never by a production bundle (the fixtures carry
 * `MOCK_MARKER`, which `no-mock-in-prod` greps the built assets for).
 *
 * ── Scenario hooks ─────────────────────────────────────────────────────────────
 * The mock is deterministic by default. Two hooks change its behaviour, and both
 * are read from the WebSocket URL's query string first and from the page URL
 * second, so a Playwright spec can drive them by navigating to
 * `/?mock_scenario=…` and a Vitest suite by connecting to `/ws?mock_scenario=…`:
 *
 *   ?mock_scenario=backpressure  after `BACKPRESSURE_TICK` (10) the socket emits
 *                                `{type:"error", code:"backpressure_dropped"}`,
 *                                the frame the shell's degraded pill reacts to.
 *   ?mock_scenario=quiet         suppresses the timed demo alert, for a test that
 *                                wants an empty rail it controls itself.
 *
 * Several scenarios may be combined: `?mock_scenario=quiet,backpressure`.
 *
 * ── Fixed timeline, per connection ────────────────────────────────────────────
 * The live clock starts at dataset tick `LIVE_START_TICK` (234) and advances one
 * row every `TICK_MS` (250 ms), carrying one `telemetry` and one `risk` frame for
 * every machine in the plant. The sixth tick after connect — `LIVE_ALERT_TICK`,
 * 1.5 s in — is dataset tick `CURRENT_TICK` (240), the row the demo alert is
 * stored against: its `alert` frame is sent and immediately followed by its
 * `explanation` frame. That is `alt_9f2c71ab40d3e155` on `ai4i-03` for the AI4I
 * plant and `alt_5b7d0e2143a6c8f9` on `ims-01` for IMS, and it is the same alert
 * `GET /api/alerts` and `GET /api/state_at` answer with, not a parallel one.
 * `ping` is emitted every `api.ws_ping_seconds` (10 s → every 40 ticks),
 * regardless of replay state (R11).
 *
 * ── State that outlives a request ─────────────────────────────────────────────
 * `POST /api/replay/command` and `PUT /api/config` mutate the fixture state in
 * `core.ts` and broadcast the resulting `replay_state` / `config` frame to every
 * connected client. `restart` mints the next `run_id` (R12), as does a successful
 * config PUT (R5). `resetMockState()` rewinds all of it; call it in a `beforeEach`.
 */
import { http, HttpResponse, ws } from 'msw';
import type {
  ConfigPatch,
  PlantId,
  Problem,
  ReplayCommand,
  ServerFrame,
  WhatIfRequest,
} from '@/contracts';
import {
  DEMO_ALERT_ID,
  DEMO_ALERT_TICK,
  LIVE_ALERT_TICK,
  LIVE_START_TICK,
  MOCK_MARKER,
  MUTABLE_KEYS,
  PLANTS,
  RUN_ID,
  UnknownChannelError,
  WhatIfValidationError,
  WS_PING_SECONDS,
  activeAlertsAt,
  advanceRunId,
  applyConfigValues,
  CURRENT_TICK,
  currentRunId,
  datasetTsFor,
  demoMachineId,
  findAlert,
  machineIdsFor,
  makeAlert,
  makeChannelValues,
  makeComparison,
  makeConfig,
  makeExplanation,
  makeHealth,
  makeImportance,
  makeMachineDetail,
  makeMachineSummaries,
  makeModels,
  makePlant,
  MODEL_ID,
  makeReplayState,
  makeRiskSeries,
  makeSnapshotMachines,
  makeStateAt,
  makeTelemetrySeries,
  makeWhatIf,
  mockState,
  parseChannels,
  plantOfMachine,
  queryAlerts,
  setReplay,
  tickAt,
  topFeaturesFor,
} from './fixtures';

/** Milliseconds between simulated replay ticks in the mock. */
export const TICK_MS = 250;
/** Ticks after connect at which `?mock_scenario=backpressure` emits its `error` frame. */
const BACKPRESSURE_TICK = 10;
/** Ticks between heartbeats: `api.ws_ping_seconds` at one tick per `TICK_MS`. */
export const PING_EVERY_TICKS = Math.round((WS_PING_SECONDS * 1000) / TICK_MS);

const plantIdFrom = (value: string | null): PlantId => (value === 'ims' ? 'ims' : 'ai4i');

/* ── RFC-9457 problem responses ─────────────────────────────────────────────── */

function problem(
  status: number,
  slug: string,
  title: string,
  detail: string,
  instance: string,
): HttpResponse<Problem> {
  const body: Problem = {
    type: `https://xpm.local/errors/${slug}`,
    title,
    status,
    detail,
    instance,
  };
  return HttpResponse.json(body, {
    status,
    headers: { 'Content-Type': 'application/problem+json' },
  });
}

const notFound = (title: string, detail: string, instance: string): HttpResponse<Problem> =>
  problem(404, 'not-found', title, detail, instance);

/* ── REST ───────────────────────────────────────────────────────────────────── */

export const restHandlers = [
  http.get('/api/health', ({ request }) =>
    HttpResponse.json(
      makeHealth(
        plantIdFrom(new URL(request.url).searchParams.get('plant_id')),
        CURRENT_TICK,
      ),
    ),
  ),
  http.get('/api/config', () => HttpResponse.json(makeConfig())),

  http.put('/api/config', async ({ request }) => {
    const patch = (await request.json()) as ConfigPatch;
    const values = patch.values ?? {};
    const immutable = Object.keys(values).filter((key) => !MUTABLE_KEYS.includes(key));
    if (immutable.length > 0) {
      // `replay.speed` is the headline case: speed goes through a replay command
      // and nowhere else (R12).
      return problem(
        409,
        'config-immutable',
        'Config key is not mutable',
        immutable.join(', '),
        '/api/config',
      );
    }
    applyConfigValues(values);
    advanceRunId();
    const response = makeConfig();
    socketLink.broadcast(JSON.stringify({ type: 'config', ...response }));
    return HttpResponse.json(response);
  }),

  http.get('/api/plants', () => HttpResponse.json(PLANTS)),
  http.get('/api/replay', () =>
    HttpResponse.json(makeReplayState('ai4i', mockState().tick)),
  ),

  http.post('/api/replay/command', async ({ request }) => {
    const command = (await request.json()) as ReplayCommand;
    const plantId = plantIdFrom(command.plant_id ?? null);
    switch (command.command) {
      case 'play':
        setReplay({ playing: true });
        break;
      case 'pause':
        setReplay({ playing: false });
        break;
      case 'set_speed':
        if (command.speed) setReplay({ speed: command.speed });
        break;
      case 'seek':
        if (command.dataset_ts) setReplay({ tick: tickAt(plantId, command.dataset_ts) });
        break;
      case 'restart':
        advanceRunId();
        setReplay({ tick: 0, playing: true });
        break;
    }
    const state = makeReplayState(plantId, mockState().tick);
    socketLink.broadcast(JSON.stringify({ type: 'replay_state', ...state }));
    if (command.command === 'seek') broadcastSnapshot(mockState().tick);
    return HttpResponse.json(state);
  }),

  http.get('/api/machines', ({ request }) => {
    const plantId = plantIdFrom(new URL(request.url).searchParams.get('plant_id'));
    return HttpResponse.json(makeMachineSummaries(plantId, CURRENT_TICK));
  }),

  http.get('/api/machines/:machineId', ({ params }) => {
    const machineId = String(params.machineId);
    const plantId = plantOfMachine(machineId);
    if (plantId === null) {
      return notFound('Machine not found', 'no such machine', `/api/machines/${machineId}`);
    }
    return HttpResponse.json(makeMachineDetail(plantId, machineId, CURRENT_TICK));
  }),

  http.get('/api/machines/:machineId/importance', ({ params, request }) => {
    const machineId = String(params.machineId);
    const plantId = plantOfMachine(machineId);
    const instance = `/api/machines/${machineId}/importance`;
    if (plantId === null) return notFound('Machine not found', 'no such machine', instance);
    const query = new URL(request.url).searchParams;
    return HttpResponse.json(
      makeImportance(plantId, machineId, {
        since: query.get('since'),
        until: query.get('until'),
        limit: query.get('limit') === null ? null : Number(query.get('limit')),
      }),
    );
  }),

  http.get('/api/telemetry', ({ request }) => {
    const query = new URL(request.url).searchParams;
    const machineId = query.get('machine_id') ?? '';
    const plantId = plantOfMachine(machineId);
    if (plantId === null) {
      return problem(
        422,
        'unprocessable',
        'Unknown machine_id',
        machineId,
        '/api/telemetry',
      );
    }
    try {
      return HttpResponse.json(
        makeTelemetrySeries(plantId, machineId, {
          since: query.get('since'),
          until: query.get('until'),
          max_points:
            query.get('max_points') === null ? null : Number(query.get('max_points')),
          channels: parseChannels(query.getAll('channels')),
        }),
      );
    } catch (error) {
      if (error instanceof UnknownChannelError) {
        return problem(
          422,
          'unprocessable',
          'Unknown channel',
          error.unknown.join(', '),
          '/api/telemetry',
        );
      }
      throw error;
    }
  }),

  http.get('/api/risk', ({ request }) => {
    const query = new URL(request.url).searchParams;
    const machineId = query.get('machine_id') ?? '';
    const plantId = plantOfMachine(machineId);
    if (plantId === null) {
      return problem(422, 'unprocessable', 'Unknown machine_id', machineId, '/api/risk');
    }
    return HttpResponse.json(
      makeRiskSeries(plantId, machineId, {
        since: query.get('since'),
        until: query.get('until'),
        max_points:
          query.get('max_points') === null ? null : Number(query.get('max_points')),
      }),
    );
  }),

  http.get('/api/state_at', ({ request }) => {
    const query = new URL(request.url).searchParams;
    const datasetTs = query.get('dataset_ts');
    if (datasetTs === null || Number.isNaN(Date.parse(datasetTs))) {
      return problem(
        422,
        'unprocessable',
        'dataset_ts is required',
        String(datasetTs),
        '/api/state_at',
      );
    }
    return HttpResponse.json(makeStateAt(plantIdFrom(query.get('plant_id')), datasetTs));
  }),

  http.get('/api/alerts', ({ request }) => {
    const query = new URL(request.url).searchParams;
    return HttpResponse.json(
      queryAlerts({
        plant_id: query.get('plant_id'),
        machine_id: query.get('machine_id'),
        since: query.get('since'),
        until: query.get('until'),
        severity: query.get('severity'),
        feature: query.get('feature'),
        limit: query.get('limit') === null ? null : Number(query.get('limit')),
        cursor: query.get('cursor'),
      }),
    );
  }),

  http.get('/api/alerts/:alertId', ({ params }) => {
    const alertId = String(params.alertId);
    const alert = findAlert(alertId);
    if (!alert) return notFound('Alert not found', alertId, `/api/alerts/${alertId}`);
    return HttpResponse.json(alert);
  }),

  http.get('/api/alerts/:alertId/explanation', ({ params, request }) => {
    const alertId = String(params.alertId);
    const instance = `/api/alerts/${alertId}/explanation`;
    const alert = findAlert(alertId);
    if (!alert) return notFound('Alert not found', alertId, instance);
    const model = new URL(request.url).searchParams.get('model');
    if (model !== null && model !== 'lgbm' && model !== 'rf') {
      return problem(422, 'unprocessable', 'Unknown model', model, instance);
    }
    return HttpResponse.json(makeExplanation(alert, model === 'rf' ? 'rf' : 'lgbm'));
  }),

  http.get('/api/alerts/:alertId/compare', ({ params }) => {
    const alertId = String(params.alertId);
    const alert = findAlert(alertId);
    if (!alert) {
      return notFound('Alert not found', alertId, `/api/alerts/${alertId}/compare`);
    }
    return HttpResponse.json(makeComparison(alert));
  }),

  http.post('/api/whatif', async ({ request }) => {
    const body = (await request.json()) as WhatIfRequest;
    const alert = findAlert(body.alert_id);
    if (!alert) return notFound('Alert not found', body.alert_id, '/api/whatif');
    try {
      return HttpResponse.json(makeWhatIf(alert, body));
    } catch (error) {
      if (error instanceof WhatIfValidationError) {
        return problem(
          422,
          'unprocessable',
          'Overrides must be a subset of the what-if features',
          error.invalid.join(', '),
          '/api/whatif',
        );
      }
      throw error;
    }
  }),

  http.get('/api/models', () => HttpResponse.json(makeModels())),
];

/* ── WebSocket ──────────────────────────────────────────────────────────────── */

/** The socket the app connects to; `plant_id` is the complete subscription. */
export const socketLink = ws.link('*/ws');

/** Scenario flags, from the socket URL first and the page URL second. */
function scenariosFor(url: URL): Set<string> {
  const fromSocket = url.searchParams.get('mock_scenario');
  const fromPage =
    typeof globalThis.location === 'undefined'
      ? null
      : new URLSearchParams(globalThis.location.search).get('mock_scenario');
  return new Set((fromSocket ?? fromPage ?? '').split(',').filter((flag) => flag !== ''));
}

/** Re-send `snapshot` to every client, in its own plant — required after a seek. */
function broadcastSnapshot(tick: number): void {
  for (const client of socketLink.clients) {
    const plantId = plantIdFrom(client.url.searchParams.get('plant_id'));
    client.send(JSON.stringify(snapshotFrame(plantId, tick)));
  }
}

function snapshotFrame(plantId: PlantId, tick: number): ServerFrame {
  return {
    type: 'snapshot',
    plant_id: plantId,
    run_id: currentRunId(),
    dataset_ts: datasetTsFor(plantId, tick),
    machines: makeSnapshotMachines(plantId, tick),
    active_alerts: activeAlertsAt(plantId, tick),
    replay_state: makeReplayState(plantId, tick),
  };
}

export const wsHandler = socketLink.addEventListener('connection', ({ client }) => {
  const plantId = plantIdFrom(client.url.searchParams.get('plant_id'));
  const scenarios = scenariosFor(client.url);
  const plant = makePlant(plantId);
  const machineIds = machineIdsFor(plantId);
  let tick = LIVE_START_TICK;

  const send = (frame: ServerFrame): void => client.send(JSON.stringify(frame));

  // hello, then snapshot, on every connect — no resume, ever (R10).
  send({
    type: 'hello',
    protocol_version: 1,
    run_id: currentRunId(),
    server_time: new Date().toISOString(),
    plant,
  });
  send(snapshotFrame(plantId, tick));

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
    const summaries = makeMachineSummaries(plantId, tick);
    send({
      type: 'risk',
      plant_id: plantId,
      ts: new Date().toISOString(),
      updates: summaries.map((summary) => ({
        machine_id: summary.machine_id,
        dataset_ts: datasetTsFor(plantId, tick),
        probability: summary.probability ?? 0,
        status: summary.status,
        alert_id: summary.open_alert_id,
        model_id: MODEL_ID,
        top_features: topFeaturesFor(makeAlert(plantId, summary.machine_id, tick)),
      })),
    });
    if (tick === DEMO_ALERT_TICK && !scenarios.has('quiet')) {
      const alert = makeAlert(plantId, demoMachineId(plantId), tick);
      send({ type: 'alert', ...alert });
      send({ type: 'explanation', ...makeExplanation(alert) });
    }
    if (tick === LIVE_START_TICK + BACKPRESSURE_TICK && scenarios.has('backpressure')) {
      send({
        type: 'error',
        code: 'backpressure_dropped',
        message: 'Dropped 42 telemetry frames for a slow client.',
        request_id: null,
      });
    }
    if ((tick - LIVE_START_TICK) % PING_EVERY_TICKS === 0) {
      send({ type: 'ping', ts: new Date().toISOString() });
    }
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

export { DEMO_ALERT_ID, DEMO_ALERT_TICK, LIVE_ALERT_TICK, RUN_ID };
