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

  it('shows a dismissible banner for connection-level errors only', async () => {
    const user = userEvent.setup();
    render(<App />);

    expect(screen.queryByTestId('error-connection')).not.toBeInTheDocument();

    // Let the socket finish opening first: a successful connect clears any
    // previous error, which would otherwise race this assertion.
    await waitFor(() => expect(useStore.getState().connection.status).toBe('open'));
    useStore.getState().setConnectionError('api unreachable');
    const banner = await screen.findByTestId('error-connection');
    expect(banner).toHaveTextContent('api unreachable');

    // Backpressure is not an error: it never raises this banner.
    useStore.getState().setConnectionDegraded(true);
    await user.click(screen.getByRole('button', { name: 'Dismiss' }));
    expect(screen.queryByTestId('error-connection')).not.toBeInTheDocument();
    expect(useStore.getState().connection.degraded).toBe(true);
  });
});
