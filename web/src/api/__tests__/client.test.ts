import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import { http, HttpResponse } from 'msw';
import { mockServer } from '@/mock/server';
import { ApiError, apiGet, buildQuery } from '../client';
import {
  getAlerts,
  getConfig,
  getExplanation,
  getMachine,
  getMachines,
  getPlants,
  getReplay,
  newRequestId,
  postReplayCommand,
} from '../queries';

beforeAll(() => mockServer.listen({ onUnhandledRequest: 'error' }));
afterEach(() => mockServer.resetHandlers());
afterAll(() => mockServer.close());

describe('buildQuery', () => {
  it('drops nullish values and repeats arrays', () => {
    expect(
      buildQuery({
        machine_id: 'ai4i-03',
        max_points: 2000,
        cursor: null,
        until: undefined,
        channels: ['torque', 'tool_wear', null],
        live: true,
      }),
    ).toBe('?machine_id=ai4i-03&max_points=2000&channels=torque&channels=tool_wear&live=true');
  });

  it('is empty for no params', () => {
    expect(buildQuery(undefined)).toBe('');
    expect(buildQuery({})).toBe('');
  });
});

describe('typed endpoints', () => {
  it('reads the contract shapes the shell boots from', async () => {
    const [config, plants, replay] = await Promise.all([
      getConfig(),
      getPlants(),
      getReplay(),
    ]);
    expect(config.values['api.ws_ping_seconds']).toBe(10);
    expect(plants.map((plant) => plant.plant_id)).toEqual(['ai4i', 'ims']);
    expect(replay.run_id).toMatch(/^run_[0-9a-f]{12}$/);
  });

  it('passes plant_id and machine ids through unencoded domain forms', async () => {
    const machines = await getMachines('ims');
    expect(machines).toHaveLength(4);
    expect(machines[0]?.machine_id).toBe('ims-01');

    const detail = await getMachine('ai4i-03');
    expect(detail.channels).toHaveLength(7);
  });

  it('reads the alert page envelope and an explanation', async () => {
    const page = await getAlerts({ plant_id: 'ai4i', limit: 50 });
    expect(page.next_cursor).toBeNull();
    const alertId = page.items[0]?.alert_id ?? '';
    const explanation = await getExplanation(alertId, 'lgbm');
    expect(explanation.shap_space).toBe('probability');
    expect(explanation.other_contributions_count).toBe(146);
  });

  it('posts transport commands over REST, never over the socket', async () => {
    const state = await postReplayCommand({
      command: 'set_speed',
      speed: 20,
      request_id: newRequestId(),
      schema_version: 1,
    });
    expect(state.speed).toBe(20);
  });

  it('mints request ids in the contract form', () => {
    expect(newRequestId()).toMatch(/^req_[0-9a-f]{4}$/);
  });

  it('raises ApiError carrying the RFC-9457 problem', async () => {
    await expect(getMachine('ai4i-99')).rejects.toBeInstanceOf(ApiError);
    await expect(getMachine('ai4i-99')).rejects.toMatchObject({
      status: 404,
      message: 'no such machine',
    });
  });

  it('raises ApiError for a non-problem error body', async () => {
    mockServer.use(
      http.get('/api/boom', () => new HttpResponse('nope', { status: 503 })),
    );
    await expect(apiGet('/api/boom')).rejects.toMatchObject({
      status: 503,
      problem: null,
    });
  });

  it('returns undefined for a 204', async () => {
    mockServer.use(http.get('/api/empty', () => new HttpResponse(null, { status: 204 })));
    await expect(apiGet('/api/empty')).resolves.toBeUndefined();
  });

  it('propagates an abort signal', async () => {
    const controller = new AbortController();
    controller.abort();
    await expect(getPlants({ signal: controller.signal })).rejects.toThrow();
  });
});
