/**
 * One case per REST handler: the query parameters it honours, the envelope it
 * returns and the RFC-9457 problem it answers a bad request with.
 */
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from 'vitest';
import type {
  Alert,
  AlertPage,
  ConfigResponse,
  Explanation,
  GlobalImportance,
  ModelComparison,
  ModelInfo,
  PlantSnapshot,
  Problem,
  ReplayState,
  RiskSeries,
  TelemetrySeries,
  WhatIfResponse,
} from '@/contracts';
import { mockServer } from '../server';
import {
  CURRENT_TICK,
  DEMO_ALERT_ID,
  RUN_IDS,
  datasetTsFor,
  findAlert,
  makeExplanation,
  resetMockState,
} from '../fixtures';

beforeAll(() => mockServer.listen({ onUnhandledRequest: 'error' }));
afterEach(() => mockServer.resetHandlers());
afterAll(() => mockServer.close());
beforeEach(() => resetMockState());

const UNKNOWN_ALERT = 'alt_deadbeefdeadbeef';

async function get<T>(path: string): Promise<{ status: number; body: T }> {
  const response = await fetch(path);
  return { status: response.status, body: (await response.json()) as T };
}

async function send<T>(
  method: 'POST' | 'PUT',
  path: string,
  body: unknown,
): Promise<{ status: number; contentType: string | null; body: T }> {
  const response = await fetch(path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return {
    status: response.status,
    contentType: response.headers.get('Content-Type'),
    body: (await response.json()) as T,
  };
}

describe('GET /api/telemetry', () => {
  it('returns equal-length columnar arrays in canonical channel order', async () => {
    const { body } = await get<TelemetrySeries>('/api/telemetry?machine_id=ai4i-03');
    expect(Object.keys(body.channels)).toEqual([
      'air_temp',
      'process_temp',
      'temp_diff',
      'rot_speed',
      'torque',
      'power',
      'tool_wear',
    ]);
    for (const column of Object.values(body.channels)) {
      expect(column).toHaveLength(body.dataset_ts.length);
    }
    expect(body.n_points).toBe(body.dataset_ts.length);
    expect(body.downsampled).toBe(false);
  });

  it('honours channels, since/until and max_points', async () => {
    const since = datasetTsFor('ai4i', 0);
    const until = datasetTsFor('ai4i', 599);
    const { body } = await get<TelemetrySeries>(
      `/api/telemetry?machine_id=ai4i-03&channels=torque,tool_wear&since=${since}&until=${until}&max_points=100`,
    );
    expect(Object.keys(body.channels)).toEqual(['torque', 'tool_wear']);
    expect(body.max_points).toBe(100);
    expect(body.n_points).toBeLessThanOrEqual(100);
    expect(body.downsampled).toBe(true);
    expect(body.dataset_ts[0]).toBe(since);
  });

  it('answers 422 for an unknown channel and for an unknown machine', async () => {
    const channel = await get<Problem>(
      '/api/telemetry?machine_id=ai4i-03&channels=torque&channels=not_a_channel',
    );
    expect(channel.status).toBe(422);
    expect(channel.body.detail).toBe('not_a_channel');

    const machine = await get<Problem>('/api/telemetry?machine_id=ai4i-99');
    expect(machine.status).toBe(422);
  });
});

describe('GET /api/risk', () => {
  it('lines every alert marker up with a row in the series', async () => {
    const { body } = await get<RiskSeries>('/api/risk?machine_id=ai4i-03');
    expect(body.probability).toHaveLength(body.dataset_ts.length);
    expect(body.status).toHaveLength(body.dataset_ts.length);
    expect(body.alerts.length).toBeGreaterThan(0);
    for (const marker of body.alerts) {
      const index = body.dataset_ts.indexOf(marker.dataset_ts);
      expect(index).toBeGreaterThanOrEqual(0);
      expect(body.probability[index]).toBeCloseTo(marker.probability, 10);
    }
  });

  it('emits no row for a machine that was never scored', async () => {
    const { body } = await get<RiskSeries>('/api/risk?machine_id=ims-04');
    expect(body.dataset_ts).toEqual([]);
    expect(body.probability).toEqual([]);
  });
});

describe('GET /api/alerts', () => {
  it('pages with an opaque cursor and never repeats a row', async () => {
    const first = await get<AlertPage>('/api/alerts?plant_id=ai4i&limit=10');
    expect(first.body.items).toHaveLength(10);
    expect(first.body.limit).toBe(10);
    expect(first.body.next_cursor).not.toBeNull();

    const second = await get<AlertPage>(
      `/api/alerts?plant_id=ai4i&limit=10&cursor=${encodeURIComponent(first.body.next_cursor ?? '')}`,
    );
    const firstIds = first.body.items.map((alert) => alert.alert_id);
    const secondIds = second.body.items.map((alert) => alert.alert_id);
    expect(secondIds.some((id) => firstIds.includes(id))).toBe(false);
    expect(Date.parse(second.body.items[0]?.dataset_ts ?? '')).toBeLessThanOrEqual(
      Date.parse(first.body.items[9]?.dataset_ts ?? ''),
    );
  });

  it('closes the last page with a null cursor', async () => {
    let cursor: string | null = null;
    let seen = 0;
    for (let page = 0; page < 20; page += 1) {
      const query: string = cursor === null ? '' : `&cursor=${encodeURIComponent(cursor)}`;
      const { body }: { body: AlertPage } = await get<AlertPage>(
        `/api/alerts?plant_id=ims&limit=8${query}`,
      );
      seen += body.items.length;
      cursor = body.next_cursor;
      if (cursor === null) break;
    }
    expect(cursor).toBeNull();
    expect(seen).toBe(20);
  });

  it('filters by machine, severity, feature and dataset window', async () => {
    const byMachine = await get<AlertPage>('/api/alerts?machine_id=ai4i-03');
    expect(byMachine.body.items.every((alert) => alert.machine_id === 'ai4i-03')).toBe(
      true,
    );

    const bySeverity = await get<AlertPage>('/api/alerts?severity=critical');
    expect(bySeverity.body.items.length).toBeGreaterThan(0);
    expect(bySeverity.body.items.every((alert) => alert.severity === 'critical')).toBe(
      true,
    );

    const byFeature = await get<AlertPage>('/api/alerts?feature=torque_p95_4h');
    expect(byFeature.body.items.length).toBeGreaterThan(0);
    expect(
      byFeature.body.items.every((alert) => alert.top_feature === 'torque_p95_4h'),
    ).toBe(true);

    const since = datasetTsFor('ai4i', CURRENT_TICK - 4);
    const byWindow = await get<AlertPage>(`/api/alerts?plant_id=ai4i&since=${since}`);
    expect(byWindow.body.items.map((alert) => alert.alert_id)).toContain(DEMO_ALERT_ID);
    expect(
      byWindow.body.items.every(
        (alert) => Date.parse(alert.dataset_ts) >= Date.parse(since),
      ),
    ).toBe(true);
  });
});

describe('GET /api/alerts/{id}', () => {
  it('returns the stored alert and a problem+json 404 for an unknown id', async () => {
    const found = await get<Alert>(`/api/alerts/${DEMO_ALERT_ID}`);
    expect(found.body.alert_id).toBe(DEMO_ALERT_ID);

    const response = await fetch(`/api/alerts/${UNKNOWN_ALERT}`);
    expect(response.status).toBe(404);
    expect(response.headers.get('Content-Type')).toContain('application/problem+json');
    const problem = (await response.json()) as Problem;
    expect(problem).toMatchObject({
      type: 'https://xpm.local/errors/not-found',
      status: 404,
      detail: UNKNOWN_ALERT,
      instance: `/api/alerts/${UNKNOWN_ALERT}`,
    });
  });
});

describe('GET /api/alerts/{id}/explanation', () => {
  it('serves lgbm by default and a genuinely different rf explanation', async () => {
    const lgbm = await get<Explanation>(`/api/alerts/${DEMO_ALERT_ID}/explanation`);
    const rf = await get<Explanation>(`/api/alerts/${DEMO_ALERT_ID}/explanation?model=rf`);

    expect(lgbm.body.model_kind).toBe('lgbm');
    expect(rf.body.model_kind).toBe('rf');
    expect(rf.body.probability).not.toBe(lgbm.body.probability);
    expect(rf.body.explanation_id).not.toBe(lgbm.body.explanation_id);
    expect(rf.body.contributions.map((entry) => entry.shap)).not.toEqual(
      lgbm.body.contributions.map((entry) => entry.shap),
    );
    expect(rf.body.caveat).toBe(lgbm.body.caveat);
  });

  it('404s an unknown alert and 422s an unknown model', async () => {
    expect((await get<Problem>(`/api/alerts/${UNKNOWN_ALERT}/explanation`)).status).toBe(
      404,
    );
    expect(
      (await get<Problem>(`/api/alerts/${DEMO_ALERT_ID}/explanation?model=xgboost`)).status,
    ).toBe(422);
  });
});

describe('GET /api/alerts/{id}/compare', () => {
  it('returns a finite correlation, commentary and signed deltas', async () => {
    const { body } = await get<ModelComparison>(`/api/alerts/${DEMO_ALERT_ID}/compare`);
    expect(Number.isFinite(body.rank_correlation)).toBe(true);
    expect(body.commentary.length).toBeGreaterThan(20);
    expect(body.probability_delta).toBeCloseTo(
      body.lgbm.probability - body.rf.probability,
      12,
    );
    expect(body.disagreements.length).toBeGreaterThan(0);
    for (const row of body.disagreements) {
      expect(row.delta).toBeCloseTo(row.lgbm_shap - row.rf_shap, 12);
    }
    // At least one feature is ranked by one model and not the other.
    expect(
      body.disagreements.some((row) => row.lgbm_rank === null || row.rf_rank === null),
    ).toBe(true);
  });

  it('404s an unknown alert', async () => {
    expect((await get<Problem>(`/api/alerts/${UNKNOWN_ALERT}/compare`)).status).toBe(404);
  });
});

describe('GET /api/machines/{id}/importance', () => {
  it('ranks features by mean |shap| with one point per alert', async () => {
    const { body } = await get<GlobalImportance>('/api/machines/ai4i-03/importance');
    expect(body.features).toHaveLength(20);
    const means = body.features.map((feature) => feature.mean_abs_shap);
    expect([...means].sort((a, b) => b - a)).toEqual(means);
    for (const feature of body.features) {
      expect(feature.points).toHaveLength(body.n_alerts);
    }
    expect(body.features.reduce((sum, f) => sum + f.points.length, 0)).toBeGreaterThan(300);
  });

  it('honours limit and 404s an unknown machine', async () => {
    const { body } = await get<GlobalImportance>(
      '/api/machines/ai4i-03/importance?limit=5',
    );
    expect(body.features).toHaveLength(5);
    expect((await get<Problem>('/api/machines/ai4i-99/importance')).status).toBe(404);
  });
});

describe('GET /api/state_at', () => {
  it('resolves to the row boundary at or below the request', async () => {
    const boundary = datasetTsFor('ai4i', 120);
    const between = new Date(Date.parse(boundary) + 137_000).toISOString();
    const { body } = await get<PlantSnapshot>(
      `/api/state_at?plant_id=ai4i&dataset_ts=${between}`,
    );
    expect(body.dataset_ts).toBe(boundary);
    expect(body.machines).toHaveLength(12);
  });

  it('carries the explanation that was active at that instant', async () => {
    const at = datasetTsFor('ai4i', CURRENT_TICK);
    const { body } = await get<PlantSnapshot>(
      `/api/state_at?plant_id=ai4i&dataset_ts=${at}`,
    );
    const alert = body.active_alerts.find((entry) => entry.alert_id === DEMO_ALERT_ID);
    expect(alert).toBeDefined();
    const explanation = body.active_explanations.find(
      (entry) => entry.alert_id === DEMO_ALERT_ID,
    );
    expect(explanation?.explanation_id).toBe(alert?.explanation_id);
    for (const active of body.active_alerts) {
      expect(Date.parse(active.dataset_ts)).toBeLessThanOrEqual(Date.parse(at));
      if (active.closed_dataset_ts !== null) {
        expect(Date.parse(active.closed_dataset_ts)).toBeGreaterThan(Date.parse(at));
      }
    }
  });

  it('422s a missing dataset_ts', async () => {
    expect((await get<Problem>('/api/state_at?plant_id=ai4i')).status).toBe(422);
  });
});

describe('POST /api/whatif', () => {
  it('recomputes a provisional probability from the overrides and its gradients', async () => {
    const started = performance.now();
    const { body } = await send<WhatIfResponse>('POST', '/api/whatif', {
      alert_id: DEMO_ALERT_ID,
      model: 'lgbm',
      overrides: { torque_p95_4h: 30 },
    });
    const elapsed = performance.now() - started;

    const alert = findAlert(DEMO_ALERT_ID);
    if (!alert) throw new Error('the demo alert must exist in the corpus');
    const explanation = makeExplanation(alert);
    expect(body.provisional).toBe(true);
    expect(body.shap_space).toBe('probability');
    expect(body.baseline_probability).toBe(alert.probability);
    expect(body.caveat).toBe(explanation.caveat);
    expect(body.probability).toBeLessThan(body.baseline_probability);
    expect(body.output_value).toBe(body.probability);
    expect(body.compute_ms).toBeGreaterThan(0);
    expect(body.compute_ms).toBeLessThan(50);
    expect(Object.keys(body.gradients)).toHaveLength(5);
    expect(elapsed).toBeLessThan(200);

    const sum = body.contributions.reduce((total, entry) => total + entry.shap, 0);
    expect(
      Math.abs(body.base_value + sum + body.other_contributions_shap - body.output_value),
    ).toBeLessThan(1e-9);

    // The moved feature's own contribution tracks the gradient it was told about.
    const moved = body.contributions.find((entry) => entry.feature === 'torque_p95_4h');
    const before = explanation.contributions.find(
      (entry) => entry.feature === 'torque_p95_4h',
    );
    expect(moved?.value).toBe(30);
    expect(moved?.shap).toBeCloseTo(
      (before?.shap ?? 0) +
        (body.gradients['torque_p95_4h'] ?? 0) * (30 - (before?.value ?? 0)),
      12,
    );
  });

  it('422s an override outside the top what-if features', async () => {
    const response = await send<Problem>('POST', '/api/whatif', {
      alert_id: DEMO_ALERT_ID,
      model: 'lgbm',
      overrides: { air_temp_std_4h: 1.2 },
    });
    expect(response.status).toBe(422);
    expect(response.contentType).toContain('application/problem+json');
    expect(response.body.detail).toBe('air_temp_std_4h');
  });

  it('404s an unknown alert', async () => {
    const response = await send<Problem>('POST', '/api/whatif', {
      alert_id: UNKNOWN_ALERT,
      model: 'lgbm',
      overrides: {},
    });
    expect(response.status).toBe(404);
  });
});

describe('GET /api/models', () => {
  it('returns a bare array with both families', async () => {
    const { body } = await get<ModelInfo[]>('/api/models');
    expect(Array.isArray(body)).toBe(true);
    expect(body.map((model) => model.family)).toEqual(['lgbm', 'rf']);
    expect(body.filter((model) => model.is_served)).toHaveLength(1);
    expect(body[0]?.n_features).toBe(154);
  });
});

describe('PUT /api/config', () => {
  it('applies a mutable key and mints a new run id', async () => {
    const before = await get<ConfigResponse>('/api/config');
    expect(before.body.run_id).toBe(RUN_IDS[0]);

    const response = await send<ConfigResponse>('PUT', '/api/config', {
      values: { 'alerting.probability_threshold': 0.42 },
    });
    expect(response.status).toBe(200);
    expect(response.body.values['alerting.probability_threshold']).toBe(0.42);
    expect(response.body.run_id).toBe(RUN_IDS[1]);
    expect(response.body.updated_at).not.toBeNull();

    const after = await get<ConfigResponse>('/api/config');
    expect(after.body.values['alerting.probability_threshold']).toBe(0.42);
  });

  it('409s a patch that touches replay.speed', async () => {
    const response = await send<Problem>('PUT', '/api/config', {
      values: { 'replay.speed': 20 },
    });
    expect(response.status).toBe(409);
    expect(response.contentType).toContain('application/problem+json');
    expect(response.body.type).toBe('https://xpm.local/errors/config-immutable');
    expect(response.body.detail).toBe('replay.speed');

    const after = await get<ConfigResponse>('/api/config');
    expect(after.body.run_id).toBe(RUN_IDS[0]);
  });
});

describe('an unknown plant_id', () => {
  it('422s instead of silently answering for the default plant', async () => {
    for (const path of [
      '/api/health?plant_id=nowhere',
      '/api/machines?plant_id=nowhere',
      `/api/state_at?plant_id=nowhere&dataset_ts=${datasetTsFor('ai4i', CURRENT_TICK)}`,
    ]) {
      const { status, body } = await get<Problem>(path);
      expect(status).toBe(422);
      expect(body.type).toBe('https://xpm.local/errors/unprocessable');
      expect(body.detail).toBe('nowhere');
    }

    const command = await send<Problem>('POST', '/api/replay/command', {
      schema_version: 1,
      command: 'pause',
      plant_id: 'nowhere',
      request_id: 'req_0009',
    });
    expect(command.status).toBe(422);
    expect(command.contentType).toContain('application/problem+json');
  });

  it('still defaults an absent plant_id to ai4i', async () => {
    const { status, body } = await get<{ plants_available: string[] }>('/api/health');
    expect(status).toBe(200);
    expect(body.plants_available).toEqual(['ai4i', 'ims']);
  });
});

describe('POST /api/replay/command', () => {
  it('serves alerts under the run the restart minted', async () => {
    const before = await get<Alert>(`/api/alerts/${DEMO_ALERT_ID}`);
    expect(before.body.run_id).toBe(RUN_IDS[0]);

    await send<ReplayState>('POST', '/api/replay/command', {
      schema_version: 1,
      command: 'restart',
      request_id: 'req_0008',
    });

    const after = await get<Alert>(`/api/alerts/${DEMO_ALERT_ID}`);
    expect(after.body.run_id).toBe(RUN_IDS[1]);
    const page = await get<AlertPage>('/api/alerts?limit=5');
    expect(page.body.items.every((alert) => alert.run_id === RUN_IDS[1])).toBe(true);
  });

  it('mints a new run id on restart and on nothing else', async () => {
    const paused = await send<ReplayState>('POST', '/api/replay/command', {
      schema_version: 1,
      command: 'pause',
      request_id: 'req_0001',
    });
    expect(paused.body.playing).toBe(false);
    expect(paused.body.run_id).toBe(RUN_IDS[0]);

    const sped = await send<ReplayState>('POST', '/api/replay/command', {
      schema_version: 1,
      command: 'set_speed',
      speed: 20,
      request_id: 'req_0002',
    });
    expect(sped.body.speed).toBe(20);
    expect(sped.body.run_id).toBe(RUN_IDS[0]);

    const restarted = await send<ReplayState>('POST', '/api/replay/command', {
      schema_version: 1,
      command: 'restart',
      request_id: 'req_0003',
    });
    expect(restarted.body.run_id).toBe(RUN_IDS[1]);
    expect(restarted.body.loop_index).toBe(1);
    expect(restarted.body.playing).toBe(true);
    expect(restarted.body.dataset_ts).toBe(datasetTsFor('ai4i', 0));
  });

  it('seeks to the row boundary at or below the requested time', async () => {
    const boundary = datasetTsFor('ai4i', 90);
    const between = new Date(Date.parse(boundary) + 61_000).toISOString();
    const { body } = await send<ReplayState>('POST', '/api/replay/command', {
      schema_version: 1,
      command: 'seek',
      dataset_ts: between,
      request_id: 'req_0004',
    });
    expect(body.dataset_ts).toBe(boundary);
  });
});
