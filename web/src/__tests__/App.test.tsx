import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { mockServer } from '@/mock/server';
import { resetStore, useStore } from '@/store';
import { clearRings } from '@/store/ringBuffer';
import { clearSlots } from '@/shell/slots';
import { stubViewport } from '@/shell/__tests__/testUtils';
import { App } from '../App';

beforeAll(() => mockServer.listen({ onUnhandledRequest: 'bypass' }));
afterEach(() => mockServer.resetHandlers());
afterAll(() => mockServer.close());

beforeEach(() => {
  resetStore();
  clearRings();
  clearSlots();
  stubViewport(true);
});

describe('App', () => {
  it('renders a complete chrome and boots the data plane from the API', async () => {
    render(<App />);

    expect(screen.getByTestId('app-shell')).toBeInTheDocument();
    expect(screen.getByTestId('top-bar')).toBeInTheDocument();
    expect(screen.getByTestId('right-rail')).toBeInTheDocument();

    await waitFor(() => expect(useStore.getState().plants.order).toEqual(['ai4i', 'ims']));
    expect(useStore.getState().config?.values['api.ws_ping_seconds']).toBe(10);
  });

  it('banners connection failures with designed copy and a retry', async () => {
    const user = userEvent.setup();
    render(<App />);

    expect(screen.queryByTestId('error-connection')).not.toBeInTheDocument();

    // Let the socket finish opening first: a successful connect clears any
    // previous error, which would otherwise race this assertion.
    await waitFor(() => expect(useStore.getState().connection.status).toBe('open'));
    useStore
      .getState()
      .setConnectionError('Cannot reach the API. 500 Internal Server Error');

    const banner = await screen.findByTestId('error-connection');
    expect(banner).toHaveTextContent(/Can.t reach the API/);
    // The transport's own words are kept, but out of the headline.
    expect(screen.getByTestId('error-connection-detail')).toHaveTextContent(
      '500 Internal Server Error',
    );

    const before = useStore.getState().connection.bootAttempt;
    await user.click(screen.getByTestId('error-connection-retry'));
    expect(useStore.getState().connection.bootAttempt).toBe(before + 1);
    expect(screen.queryByTestId('error-connection')).not.toBeInTheDocument();
  });

  it('keeps backpressure off the banner: it is a degraded pill, not an error', async () => {
    render(<App />);
    await waitFor(() => expect(useStore.getState().connection.status).toBe('open'));

    useStore.getState().setConnectionDegraded(true);
    expect(screen.queryByTestId('error-connection')).not.toBeInTheDocument();
    expect(await screen.findByTestId('connection-pill')).toHaveTextContent('DEGRADED');
  });
});
