import { render } from '@testing-library/react';
import { StrictMode } from 'react';
import { http, HttpResponse } from 'msw';
import {
  afterAll,
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from 'vitest';
import { mockServer } from '@/mock/server';
import { makeConfig, makeReplayState, PLANTS } from '@/mock/fixtures';
import { resetStore, useStore } from '@/store';
import { clearRings } from '@/store/ringBuffer';
import type { SocketLike } from '../client';
import { useWsConnection } from '../useWsConnection';
import { socketFactory } from './fakeSocket';
import type { FakeSocket } from './fakeSocket';

beforeAll(() => mockServer.listen({ onUnhandledRequest: 'bypass' }));
afterEach(() => mockServer.resetHandlers());
afterAll(() => mockServer.close());

beforeEach(() => {
  resetStore();
  clearRings();
});

function Harness({ sockets }: { sockets: FakeSocket[] }) {
  const factory = socketFactory(sockets);
  useWsConnection({
    socketFactory: (url: string): SocketLike => factory(url),
    origin: 'http://xpm.test',
    random: () => 0.5,
  });
  return null;
}

/** Count what the boot sequence actually asked the API for. */
function countRequests(): { urls: string[]; stop: () => void } {
  const urls: string[] = [];
  const listener = ({ request }: { request: Request }): void => {
    urls.push(new URL(request.url).pathname);
  };
  mockServer.events.on('request:match', listener);
  return { urls, stop: () => mockServer.events.removeListener('request:match', listener) };
}

describe('useWsConnection', () => {
  it('survives StrictMode mount/unmount/mount and still opens the socket', async () => {
    // StrictMode aborts the first attempt's fetches; the boot must be idempotent
    // rather than once-only, or the dev server renders a permanently dead shell.
    const sockets: FakeSocket[] = [];
    const seen = countRequests();

    render(
      <StrictMode>
        <Harness sockets={sockets} />
      </StrictMode>,
    );

    await vi.waitFor(() => {
      expect(useStore.getState().config).not.toBeNull();
      expect(useStore.getState().plants.order.length).toBeGreaterThan(0);
      expect(sockets).toHaveLength(1);
    });

    // Exactly one *resolved* boot: config, plants and replay each landed once.
    expect(useStore.getState().plants.order).toEqual(['ai4i', 'ims']);
    expect(useStore.getState().playback.runId).toBe(makeReplayState('ai4i', 0).run_id);
    expect(useStore.getState().config?.values['api.ws_ping_seconds']).toBe(
      makeConfig().values['api.ws_ping_seconds'],
    );
    expect(sockets[0]?.url).toContain('plant_id=ai4i');
    seen.stop();
  });

  it('does not re-boot when an already-booted hook re-mounts', async () => {
    const sockets: FakeSocket[] = [];
    useStore.getState().applyConfig(makeConfig());
    useStore.getState().setPlants(PLANTS);

    const seen = countRequests();
    render(<Harness sockets={sockets} />);
    await vi.waitFor(() => {
      expect(sockets).toHaveLength(1);
    });

    expect(seen.urls).toEqual([]);
    seen.stop();
  });

  it('goes terminally offline when the API cannot be reached, and retries', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    mockServer.use(
      http.get('/api/config', () => HttpResponse.error()),
      http.get('/api/plants', () => HttpResponse.error()),
    );
    const sockets: FakeSocket[] = [];
    render(<Harness sockets={sockets} />);

    await vi.waitFor(() => {
      expect(useStore.getState().connection.error).not.toBeNull();
    });

    // Not "connecting" forever: the pill has a terminal state and the copy is
    // ours, with the transport's own words appended for the details disclosure.
    expect(useStore.getState().connection.status).toBe('closed');
    expect(useStore.getState().connection.error).toMatch(/^Cannot reach the API\./);
    expect(sockets).toHaveLength(0);

    // The retry is automatic and paced: a handful of attempts over a second,
    // not a hot loop against a down API (the backoff's first step is the floor).
    const attemptsBefore = useStore.getState().connection.bootAttempt;
    mockServer.resetHandlers();
    await vi.advanceTimersByTimeAsync(1200);
    const attemptsAfter = useStore.getState().connection.bootAttempt;
    expect(attemptsAfter).toBeGreaterThan(attemptsBefore);
    expect(attemptsAfter - attemptsBefore).toBeLessThan(6);

    await vi.waitFor(() => {
      expect(useStore.getState().plants.order.length).toBeGreaterThan(0);
    });
    vi.useRealTimers();
  });
});
